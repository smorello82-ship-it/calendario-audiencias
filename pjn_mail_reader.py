import urllib.request
import urllib.parse
import ssl
import json
import os
import re
import zipfile
import io
import base64
from datetime import datetime
import database
import extractor

class PJNWebmailClient:
    """
    Cliente para Zimbra Webmail del PJN (https://webmail.pjn.gov.ar)
    Soporta conexión directa por WebDAV (/dav/) mediante Contraseña de Aplicación
    y conexión tradicional SOAP/REST con 2FA.
    """
    def __init__(self, username, password, totp_secret=None, base_url="https://webmail.pjn.gov.ar"):
        self.raw_username = username.strip()
        self.password = password.strip()
        self.totp_secret = totp_secret.strip() if totp_secret else None
        self.base_url = base_url.rstrip("/")
        
        # Normalizar usuario completo con dominio
        self.full_username = self.raw_username if "@" in self.raw_username else f"{self.raw_username}@pjn.gov.ar"
        self.short_username = self.raw_username.split("@")[0]
        
        self.ssl_context = ssl.create_default_context()
        self.ssl_context.check_hostname = False
        self.ssl_context.verify_mode = ssl.CERT_NONE
        
        # Credenciales Basic Auth
        user_pass = f"{self.full_username}:{self.password}".encode('utf-8')
        self.auth_header = f"Basic {base64.b64encode(user_pass).decode('ascii')}"

    def search_and_sync_hearings(self, max_emails=30):
        """
        Sincroniza audiencias descargando cédulas en PDF desde el Webmail PJN.
        Intenta primero por WebDAV (/dav/) con Contraseña de Aplicación (más rápido y seguro),
        y si no, por la API SOAP/REST de Zimbra.
        """
        # 1. Probar WebDAV
        res_webdav = self._sync_via_webdav()
        if res_webdav.get("success"):
            return res_webdav
            
        # Si WebDAV falló por credenciales incorrectas, devolver el error claro
        if res_webdav.get("auth_failed"):
            return {
                "success": False,
                "error": "Contraseña de aplicación o usuario incorrecto en webmail.pjn.gov.ar. Verificá los datos ingresados."
            }
            
        # 2. Fallback: Probar SOAP/REST
        return self._sync_via_soap_rest(max_emails=max_emails)

    def _sync_via_webdav(self):
        """Descarga adjuntos PDF y ZIP directamente desde los buzones virtuales WebDAV de Zimbra"""
        headers = {
            "Authorization": self.auth_header,
            "User-Agent": "Mozilla/5.0"
        }
        
        # Verificar autenticación probando la raíz del usuario
        test_url = f"{self.base_url}/dav/{self.full_username}/"
        try:
            req_test = urllib.request.Request(test_url, headers=headers)
            with urllib.request.urlopen(req_test, context=self.ssl_context, timeout=8) as r_test:
                if r_test.status != 200:
                    return {"success": False, "auth_failed": True}
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                return {"success": False, "auth_failed": True}
            return {"success": False, "error": f"Error conectando con WebDAV PJN (HTTP {e.code})"}
        except Exception as e:
            return {"success": False, "error": f"Error de red con Webmail PJN: {str(e)}"}

        os.makedirs("uploads", exist_ok=True)
        existentes = database.get_audiencias(filtro="todas")
        
        nuevas_cargadas = 0
        ya_existentes = 0
        detalles = []
        archivos_procesados = set()

        # Revisar carpetas de adjuntos: hoy, última semana y último mes
        subcarpetas = ["today", "last-week", "last-month"]
        
        for sub in subcarpetas:
            url_folder = f"{self.base_url}/dav/{self.full_username}/attachments/by-type/pdf/{sub}/"
            req_folder = urllib.request.Request(
                url_folder, 
                headers={**headers, "Depth": "1"}, 
                method="PROPFIND"
            )
            
            try:
                with urllib.request.urlopen(req_folder, context=self.ssl_context, timeout=15) as r_f:
                    xml_content = r_f.read().decode('utf-8', errors='ignore')
            except Exception:
                continue

            # Extraer archivos PDF
            for m in re.finditer(r'<D:response>(.*?)</D:response>', xml_content, re.DOTALL):
                resp_xml = m.group(1)
                m_href = re.search(r'<D:href>([^<]+)</D:href>', resp_xml)
                if not m_href:
                    continue
                href = m_href.group(1)
                if not href.lower().endswith(".pdf"):
                    continue

                raw_filename = urllib.parse.unquote(href.split('/')[-1])
                clean_filename = "".join(c for c in raw_filename if c.isalnum() or c in (' ', '.', '_', '-')).strip()
                if not clean_filename.lower().endswith('.pdf'):
                    clean_filename += '.pdf'

                if clean_filename in archivos_procesados:
                    continue
                archivos_procesados.add(clean_filename)

                # Descargar el archivo PDF
                file_url = f"{self.base_url}{href}"
                try:
                    req_file = urllib.request.Request(file_url, headers=headers)
                    with urllib.request.urlopen(req_file, context=self.ssl_context, timeout=15) as r_file:
                        content_bytes = r_file.read()
                    
                    if not content_bytes.startswith(b'%PDF-'):
                        continue

                    dest_path = os.path.join("uploads", clean_filename)
                    with open(dest_path, "wb") as f_out:
                        f_out.write(content_bytes)

                    # Extraer datos con pdfplumber
                    extracted = extractor.extract_hearing_from_pdf(dest_path)

                    # Es audiencia válida si tiene carpeta o fecha con tipo de audiencia
                    has_carpeta = bool(extracted.get("carpeta"))
                    has_fecha = bool(extracted.get("fecha"))
                    has_aud = bool(extracted.get("audiencia_requerida"))

                    if has_carpeta or (has_fecha and has_aud):
                        # Evitar duplicados
                        duplicada = any(
                            (
                                has_carpeta and 
                                (a.get("carpeta") or "").strip().lower() == extracted["carpeta"].strip().lower() and
                                (a.get("fecha") or "").strip() == (extracted.get("fecha") or "").strip()
                            ) or (
                                not has_carpeta and 
                                (a.get("fecha") or "").strip() == (extracted.get("fecha") or "").strip() and
                                (a.get("audiencia_requerida") or "").strip().lower() == (extracted.get("audiencia_requerida") or "").strip().lower()
                            )
                            for a in existentes
                        )

                        if not duplicada:
                            extracted["orden"] = database.get_next_orden()
                            extracted["archivo_pdf"] = clean_filename
                            database.save_audiencia(extracted)
                            nuevas_cargadas += 1
                            detalles.append({
                                "carpeta": extracted.get("carpeta", ""),
                                "fecha": extracted.get("fecha", ""),
                                "hora": extracted.get("hora", ""),
                                "delito": extracted.get("tipo_delito", ""),
                                "modalidad": extracted.get("modalidad", ""),
                                "asunto": "Notificación Judicial (Webmail PJN)",
                                "pdf": clean_filename
                            })
                            existentes.append(extracted)
                        else:
                            ya_existentes += 1
                except Exception as ex:
                    # Si no se pudo descargar este archivo individual, continuar con el siguiente
                    pass

        now_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        return {
            "success": True,
            "nuevas_audiencias": nuevas_cargadas,
            "ya_existentes": ya_existentes,
            "total_mensajes_revisados": len(archivos_procesados),
            "ultima_sincronizacion": now_str,
            "detalles": detalles
        }

    def _sync_via_soap_rest(self, max_emails=30):
        """Método alternativo mediante SOAP y REST API tradicional"""
        # Autenticación SOAP
        usernames_to_try = [self.full_username, self.short_username]
        auth_token = None
        last_error = ""

        for u in usernames_to_try:
            soap_xml = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope">
  <soap:Header><context xmlns="urn:zimbra"/></soap:Header>
  <soap:Body>
    <AuthRequest xmlns="urn:zimbraAccount">
      <account by="name">{u}</account>
      <password>{self._escape_xml(self.password)}</password>
    </AuthRequest>
  </soap:Body>
</soap:Envelope>"""

            req = urllib.request.Request(
                f"{self.base_url}/service/soap",
                data=soap_xml.encode('utf-8'),
                headers={"Content-Type": "application/soap+xml; charset=utf-8", "User-Agent": "Mozilla/5.0"}
            )
            try:
                with urllib.request.urlopen(req, context=self.ssl_context, timeout=12) as resp:
                    xml_resp = resp.read().decode('utf-8')
                    m_token = re.search(r'<authToken>([^<]+)</authToken>', xml_resp)
                    if m_token:
                        auth_token = m_token.group(1).strip()
                        break
            except Exception as e:
                last_error = str(e)

        if not auth_token:
            return {"success": False, "error": f"Error de autenticación en Webmail PJN: {last_error}"}

        headers = {
            "Cookie": f"ZM_AUTH_TOKEN={auth_token}",
            "User-Agent": "Mozilla/5.0"
        }

        # Búsqueda REST de mensajes
        messages = []
        try:
            url_search = f"{self.base_url}/home/~/?query=has:attachment&types=message&limit={max_emails}&fmt=json"
            req_s = urllib.request.Request(url_search, headers=headers)
            with urllib.request.urlopen(req_s, context=self.ssl_context, timeout=15) as r:
                data = json.loads(r.read().decode('utf-8'))
                messages = data.get("m", [])
        except Exception as e:
            return {"success": False, "error": f"Error leyendo correos de Zimbra: {str(e)}"}

        nuevas_cargadas = 0
        ya_existentes = 0
        detalles = []
        os.makedirs("uploads", exist_ok=True)
        existentes = database.get_audiencias(filtro="todas")

        for m in messages:
            msg_id = m.get("id")
            subject = m.get("su") or "Sin Asunto"
            parts = m.get("mp", [])
            pdf_parts = self._find_pdf_parts(parts)

            for part_info in pdf_parts:
                part_id = part_info.get("part", "2")
                part_filename = part_info.get("name") or f"audiencia_{msg_id}.pdf"
                clean_filename = "".join(c for c in part_filename if c.isalnum() or c in (' ', '.', '_', '-')).strip()
                if not clean_filename.lower().endswith('.pdf'):
                    clean_filename += '.pdf'

                dest_path = os.path.join("uploads", clean_filename)
                url_part = f"{self.base_url}/home/~/?id={msg_id}&part={part_id}"
                
                try:
                    req_part = urllib.request.Request(url_part, headers=headers)
                    with urllib.request.urlopen(req_part, context=self.ssl_context, timeout=15) as resp_part:
                        content = resp_part.read()

                    if content.startswith(b'%PDF-'):
                        with open(dest_path, "wb") as f:
                            f.write(content)

                        extracted = extractor.extract_hearing_from_pdf(dest_path)
                        has_carpeta = bool(extracted.get("carpeta"))
                        has_fecha = bool(extracted.get("fecha"))

                        if has_carpeta or has_fecha:
                            duplicada = any(
                                (a.get("carpeta") or "").strip().lower() == (extracted.get("carpeta") or "").strip().lower() and
                                (a.get("fecha") or "").strip() == (extracted.get("fecha") or "").strip()
                                for a in existentes
                            )

                            if not duplicada:
                                extracted["orden"] = database.get_next_orden()
                                extracted["archivo_pdf"] = clean_filename
                                database.save_audiencia(extracted)
                                nuevas_cargadas += 1
                                detalles.append({
                                    "carpeta": extracted.get("carpeta", ""),
                                    "fecha": extracted.get("fecha", ""),
                                    "hora": extracted.get("hora", ""),
                                    "delito": extracted.get("tipo_delito", ""),
                                    "modalidad": extracted.get("modalidad", ""),
                                    "asunto": subject,
                                    "pdf": clean_filename
                                })
                                existentes.append(extracted)
                            else:
                                ya_existentes += 1
                except Exception:
                    pass

        now_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        return {
            "success": True,
            "nuevas_audiencias": nuevas_cargadas,
            "ya_existentes": ya_existentes,
            "total_mensajes_revisados": len(messages),
            "ultima_sincronizacion": now_str,
            "detalles": detalles
        }

    def _find_pdf_parts(self, parts):
        pdf_list = []
        if isinstance(parts, list):
            for p in parts:
                pdf_list.extend(self._find_pdf_parts(p))
        elif isinstance(parts, dict):
            ct = parts.get("ct", "").lower()
            filename = parts.get("filename") or parts.get("name") or ""
            part_id = parts.get("part")
            if "pdf" in ct or filename.lower().endswith(".pdf"):
                pdf_list.append({"part": part_id, "name": filename})
            if "mp" in parts:
                pdf_list.extend(self._find_pdf_parts(parts["mp"]))
        return pdf_list

    def _escape_xml(self, s):
        return (str(s).replace("&", "&amp;")
                      .replace("<", "&lt;")
                      .replace(">", "&gt;")
                      .replace('"', "&quot;")
                      .replace("'", "&apos;"))

def sync_pjn_mail():
    cfg = database.get_config()
    user = cfg.get("pjn_user")
    pwd = cfg.get("pjn_pass")

    if not user or not pwd:
        return {
            "success": False,
            "error": "Por favor configurá tu usuario y contraseña de aplicación de webmail.pjn.gov.ar en Configurar Envíos."
        }

    client = PJNWebmailClient(username=user, password=pwd)
    return client.search_and_sync_hearings()

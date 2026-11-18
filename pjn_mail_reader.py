import urllib.request
import urllib.parse
import ssl
import json
import os
import re
import time
import hmac
import hashlib
import struct
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

    @staticmethod
    def _generate_totp(secret: str) -> str:
        """Genera el código TOTP de 6 dígitos a partir del secreto Base32."""
        clean_secret = re.sub(r'\s+', '', secret).upper()
        padding = '=' * ((8 - len(clean_secret) % 8) % 8)
        key = base64.b32decode(clean_secret + padding, casefold=True)
        counter = int(time.time() // 30)
        msg = struct.pack('>Q', counter)
        digest = hmac.new(key, msg, hashlib.sha1).digest()
        offset = digest[-1] & 0x0F
        code = (struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7FFFFFFF) % 1000000
        return f"{code:06d}"

    def search_and_sync_hearings(self, max_emails=30):
        """
        Sincroniza audiencias descargando cédulas en PDF desde el Webmail PJN.
        Si hay secreto 2FA (TOTP), prioriza SOAP/REST porque descarga el 100% de los adjuntos
        (incluyendo nombres con espacios). Si falla (ej. si la clave guardada es de aplicación),
        usa WebDAV (/dav/) como respaldo.
        """
        if self.totp_secret:
            res_soap = self._sync_via_soap_rest(max_emails=max_emails)
            if res_soap.get("success"):
                return res_soap
            res_webdav = self._sync_via_webdav()
            if res_webdav.get("success"):
                return res_webdav
            return res_soap

        # Sin secreto 2FA: probar WebDAV primero y luego SOAP/REST
        res_webdav = self._sync_via_webdav()
        if res_webdav.get("success"):
            return res_webdav

        res_soap = self._sync_via_soap_rest(max_emails=max_emails)
        if res_soap.get("success"):
            return res_soap

        if res_webdav.get("auth_failed"):
            return {
                "success": False,
                "error": "Contraseña de aplicación o usuario incorrecto en webmail.pjn.gov.ar. Verificá los datos ingresados."
            }
        return res_soap

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
        existentes_pdfs = {(a.get("archivo_pdf") or "").strip() for a in existentes if a.get("archivo_pdf")}
        
        nuevas_cargadas = 0
        ya_existentes = 0
        detalles = []
        archivos_procesados = set()
        start_time = time.time()

        # Revisar carpetas de adjuntos: hoy, última semana y último mes
        subcarpetas = ["today", "last-week", "last-month"]
        
        for sub in subcarpetas:
            if time.time() - start_time > 20:
                break
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

                if clean_filename in existentes_pdfs:
                    ya_existentes += 1
                    continue

                dest_path = os.path.join("uploads", clean_filename)
                if os.path.exists(dest_path):
                    continue

                if time.time() - start_time > 20:
                    break

                # Descargar el archivo PDF
                file_url = f"{self.base_url}{href}"
                try:
                    req_file = urllib.request.Request(file_url, headers=headers)
                    with urllib.request.urlopen(req_file, context=self.ssl_context, timeout=8) as r_file:
                        content_bytes = r_file.read()
                    
                    if not content_bytes.startswith(b'%PDF-'):
                        continue

                    with open(dest_path, "wb") as f_out:
                        f_out.write(content_bytes)

                    # Extraer datos con pdfplumber
                    extracted = extractor.extract_hearing_from_pdf(dest_path)

                    # Es audiencia válida solo si tiene fecha, hora y datos reales de audiencia (evita oficios comunes)
                    has_carpeta = bool(extracted.get("carpeta"))
                    if extractor.is_valid_hearing(extracted):
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

        device_id = "calendario-audiencias-render"
        is_trusted_token = bool(self.totp_secret and self.totp_secret.startswith("0_"))

        for u in usernames_to_try:
            trusted_tags = ""
            if is_trusted_token:
                trusted_tags = f"\n      <trustedToken>{self._escape_xml(self.totp_secret)}</trustedToken>\n      <deviceId>{device_id}</deviceId>"

            soap_xml = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope">
  <soap:Header><context xmlns="urn:zimbra"/></soap:Header>
  <soap:Body>
    <AuthRequest xmlns="urn:zimbraAccount" persistAuthTokenCookie="1">
      <account by="name">{u}</account>
      <password>{self._escape_xml(self.password)}</password>{trusted_tags}
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
                    needs_2fa = '<twoFactorAuthRequired>true</twoFactorAuthRequired>' in xml_resp
                    if m_token and not needs_2fa:
                        auth_token = m_token.group(1).strip()
                        break
                    if m_token and needs_2fa and self.totp_secret and not is_trusted_token:
                        tfa_token = m_token.group(1).strip()
                        if re.fullmatch(r'\d{6}', self.totp_secret.strip()):
                            totp_code = self.totp_secret.strip()
                        else:
                            totp_code = self._generate_totp(self.totp_secret)
                        soap_2fa = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope">
  <soap:Header>
    <context xmlns="urn:zimbra">
      <authToken>{tfa_token}</authToken>
    </context>
  </soap:Header>
  <soap:Body>
    <AuthRequest xmlns="urn:zimbraAccount" persistAuthTokenCookie="1" deviceTrusted="1">
      <account by="name">{u}</account>
      <password>{self._escape_xml(self.password)}</password>
      <twoFactorCode>{totp_code}</twoFactorCode>
      <deviceId>{device_id}</deviceId>
    </AuthRequest>
  </soap:Body>
</soap:Envelope>"""
                        req2 = urllib.request.Request(
                            f"{self.base_url}/service/soap",
                            data=soap_2fa.encode('utf-8'),
                            headers={"Content-Type": "application/soap+xml; charset=utf-8", "User-Agent": "Mozilla/5.0"}
                        )
                        with urllib.request.urlopen(req2, context=self.ssl_context, timeout=12) as resp2:
                            xml_resp2 = resp2.read().decode('utf-8')
                            m_token2 = re.search(r'<authToken>([^<]+)</authToken>', xml_resp2)
                            if m_token2:
                                auth_token = m_token2.group(1).strip()
                                m_trusted = re.search(r'<trustedToken>([^<]+)</trustedToken>', xml_resp2)
                                if m_trusted:
                                    try:
                                        cfg = database.get_config()
                                        cfg["pjn_2fa_secret"] = m_trusted.group(1).strip()
                                        database.save_config(cfg)
                                    except Exception:
                                        pass
                                break
            except Exception as e:
                last_error = str(e)

        if not auth_token:
            return {"success": False, "error": f"Error de autenticación en Webmail PJN: {last_error}"}

        headers = {
            "Cookie": f"ZM_AUTH_TOKEN={auth_token}",
            "User-Agent": "Mozilla/5.0"
        }

        # Búsqueda SOAP JSON de mensajes recientes con adjuntos en Inbox
        messages = []
        try:
            soap_search = {
                "Header": {"context": {"_jsns": "urn:zimbra", "authToken": {"_content": auth_token}}},
                "Body": {
                    "SearchRequest": {
                        "_jsns": "urn:zimbraMail",
                        "types": "message",
                        "limit": max_emails,
                        "query": "in:inbox has:attachment"
                    }
                }
            }
            req_s = urllib.request.Request(
                f"{self.base_url}/service/soap",
                data=json.dumps(soap_search).encode('utf-8'),
                headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(req_s, context=self.ssl_context, timeout=15) as r:
                data = json.loads(r.read().decode('utf-8'))
                messages = data.get("Body", {}).get("SearchResponse", {}).get("m", [])
        except Exception as e:
            return {"success": False, "error": f"Error leyendo correos de Zimbra: {str(e)}"}

        nuevas_cargadas = 0
        ya_existentes = 0
        detalles = []
        os.makedirs("uploads", exist_ok=True)
        existentes = database.get_audiencias(filtro="todas")
        existentes_pdfs = {(a.get("archivo_pdf") or "").strip() for a in existentes if a.get("archivo_pdf")}
        start_time = time.time()

        for m in messages:
            if time.time() - start_time > 20:
                break
            msg_id = m.get("id")
            subject = m.get("su") or "Sin Asunto"

            # Obtener partes MIME reales mediante GetMsgRequest
            parts = m.get("mp", [])
            if not parts:
                try:
                    soap_get = {
                        "Header": {"context": {"_jsns": "urn:zimbra", "authToken": {"_content": auth_token}}},
                        "Body": {"GetMsgRequest": {"_jsns": "urn:zimbraMail", "m": {"id": msg_id}}}
                    }
                    req_g = urllib.request.Request(
                        f"{self.base_url}/service/soap",
                        data=json.dumps(soap_get).encode('utf-8'),
                        headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
                    )
                    with urllib.request.urlopen(req_g, context=self.ssl_context, timeout=10) as rg:
                        dg = json.loads(rg.read().decode('utf-8'))
                        parts = dg.get("Body", {}).get("GetMsgResponse", {}).get("m", [{}])[0].get("mp", [])
                except Exception:
                    parts = []

            pdf_parts = self._find_pdf_parts(parts)

            for part_info in pdf_parts:
                if time.time() - start_time > 20:
                    break
                part_id = part_info.get("part", "2")
                part_filename = part_info.get("name") or f"audiencia_{msg_id}.pdf"
                clean_filename = "".join(c for c in part_filename if c.isalnum() or c in (' ', '.', '_', '-')).strip()
                if not clean_filename.lower().endswith('.pdf'):
                    clean_filename += '.pdf'

                if clean_filename in existentes_pdfs:
                    ya_existentes += 1
                    continue

                dest_path = os.path.join("uploads", clean_filename)
                if os.path.exists(dest_path):
                    continue
                url_part = f"{self.base_url}/home/~/?id={msg_id}&part={part_id}"
                
                try:
                    req_part = urllib.request.Request(url_part, headers=headers)
                    with urllib.request.urlopen(req_part, context=self.ssl_context, timeout=15) as resp_part:
                        content = resp_part.read()

                    if content.startswith(b'%PDF-'):
                        with open(dest_path, "wb") as f:
                            f.write(content)

                        extracted = extractor.extract_hearing_from_pdf(dest_path)

                        if extractor.is_valid_hearing(extracted):
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
    totp_secret = cfg.get("pjn_2fa_secret")

    if not user or not pwd:
        return {
            "success": False,
            "error": "Por favor configurá tu usuario y contraseña de aplicación de webmail.pjn.gov.ar en Configurar Envíos."
        }

    client = PJNWebmailClient(username=user, password=pwd, totp_secret=totp_secret)
    return client.search_and_sync_hearings()

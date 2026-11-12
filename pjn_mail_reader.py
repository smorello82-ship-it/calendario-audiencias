import urllib.request
import urllib.parse
import ssl
import json
import os
import re
from datetime import datetime
import database
import extractor

class PJNWebmailClient:
    """
    Cliente oficial para Zimbra Webmail del PJN (https://webmail.pjn.gov.ar)
    Utiliza autenticación SOAP nativa y REST API para descargar PDFs de audiencias.
    """
    def __init__(self, username, password, base_url="https://webmail.pjn.gov.ar"):
        self.raw_username = username.strip()
        self.password = password.strip()
        self.base_url = base_url.rstrip("/")
        self.auth_token = None
        
        self.ssl_context = ssl.create_default_context()
        self.ssl_context.check_hostname = False
        self.ssl_context.verify_mode = ssl.CERT_NONE

    def login(self):
        """Autentica contra Zimbra SOAP (/service/soap)"""
        usernames_to_try = [self.raw_username]
        if "@" not in self.raw_username:
            usernames_to_try.insert(0, f"{self.raw_username}@pjn.gov.ar")

        last_error = ""

        for u in usernames_to_try:
            soap_xml = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope">
  <soap:Header>
    <context xmlns="urn:zimbra"/>
  </soap:Header>
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
                headers={
                    "Content-Type": "application/soap+xml; charset=utf-8",
                    "User-Agent": "Mozilla/5.0"
                }
            )

            try:
                with urllib.request.urlopen(req, context=self.ssl_context, timeout=12) as resp:
                    xml_resp = resp.read().decode('utf-8')
                    m_token = re.search(r'<authToken>([^<]+)</authToken>', xml_resp)
                    if m_token:
                        self.auth_token = m_token.group(1).strip()
                        return True, "Autenticación exitosa en Zimbra PJN"
            except urllib.error.HTTPError as e:
                err_content = e.read().decode('utf-8', errors='ignore')
                if "AUTH_FAILED" in err_content or "authentication failed" in err_content:
                    last_error = f"Usuario o contraseña incorrectos en webmail.pjn.gov.ar. Verifique que sus datos de acceso sean correctos."
                elif "account.ACCOUNT_LOCKED" in err_content:
                    return False, "La cuenta de correo judicial se encuentra bloqueada temporalmente."
                else:
                    last_error = f"Error en servidor Zimbra (HTTP {e.code})"
            except Exception as e:
                last_error = f"Error de conexión con {self.base_url}: {str(e)}"

        return False, last_error or "No se pudo iniciar sesión en webmail.pjn.gov.ar"

    def search_and_sync_hearings(self, max_emails=30):
        """Busca correos con PDFs adjuntos, los descarga y agenda las audiencias"""
        if not self.auth_token:
            ok, msg = self.login()
            if not ok:
                return {"success": False, "error": msg}

        queries_to_try = [
            "has:attachment filename:pdf",
            "filename:pdf",
            "has:attachment"
        ]

        messages = []
        headers = {
            "Cookie": f"ZM_AUTH_TOKEN={self.auth_token}",
            "User-Agent": "Mozilla/5.0"
        }

        for q in queries_to_try:
            encoded_query = urllib.parse.quote(q)
            url_search = f"{self.base_url}/home/~/?query={encoded_query}&types=message&limit={max_emails}&fmt=json"
            try:
                req = urllib.request.Request(url_search, headers=headers)
                with urllib.request.urlopen(req, context=self.ssl_context, timeout=18) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                    found = data.get("m", [])
                    if found:
                        messages = found
                        break
            except Exception as e:
                print(f"Error consultando query '{q}': {e}")

        if not messages:
            try:
                url_fallback = f"{self.base_url}/home/~/?types=message&limit={max_emails}&fmt=json"
                req = urllib.request.Request(url_fallback, headers=headers)
                with urllib.request.urlopen(req, context=self.ssl_context, timeout=18) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                    messages = data.get("m", [])
            except Exception as e:
                return {"success": False, "error": f"Error al leer la bandeja de Zimbra: {str(e)}"}

        nuevas_cargadas = 0
        ya_existentes = 0
        detalles = []
        os.makedirs("uploads", exist_ok=True)

        for m in messages:
            msg_id = m.get("id")
            subject = m.get("su") or "Sin Asunto"

            parts = m.get("mp", [])
            pdf_parts = self._find_pdf_parts(parts)

            if not pdf_parts:
                pdf_parts = [{"part": "2", "name": f"notificacion_{msg_id}.pdf"}]

            for part_info in pdf_parts:
                part_id = part_info.get("part", "2")
                part_filename = part_info.get("name") or f"audiencia_{msg_id}.pdf"
                if not part_filename.lower().endswith(".pdf"):
                    part_filename += ".pdf"

                clean_filename = "".join(c for c in part_filename if c.isalnum() or c in (' ', '.', '_', '-')).strip()
                dest_path = os.path.join("uploads", clean_filename)

                url_part = f"{self.base_url}/home/~/?id={msg_id}&part={part_id}"
                try:
                    req_part = urllib.request.Request(url_part, headers=headers)
                    with urllib.request.urlopen(req_part, context=self.ssl_context, timeout=20) as resp_part:
                        content = resp_part.read()

                    if content.startswith(b'%PDF'):
                        with open(dest_path, "wb") as f:
                            f.write(content)

                        extracted = extractor.extract_hearing_from_pdf(dest_path)

                        if extracted.get("carpeta"):
                            existentes = database.get_audiencias(filtro="todas")
                            duplicada = any(
                                (a.get("carpeta") or "").strip().lower() == extracted["carpeta"].strip().lower() and
                                (a.get("fecha") or "").strip() == extracted["fecha"].strip()
                                for a in existentes
                            )

                            if not duplicada:
                                extracted["orden"] = database.get_next_orden()
                                extracted["archivo_pdf"] = clean_filename
                                database.save_audiencia(extracted)
                                nuevas_cargadas += 1
                                detalles.append({
                                    "carpeta": extracted["carpeta"],
                                    "fecha": extracted["fecha"],
                                    "hora": extracted["hora"],
                                    "delito": extracted.get("tipo_delito", ""),
                                    "modalidad": extracted.get("modalidad", ""),
                                    "asunto": subject,
                                    "pdf": clean_filename
                                })
                            else:
                                ya_existentes += 1
                except Exception as ex_file:
                    print(f"Error procesando adjunto {msg_id}: {ex_file}")

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
            "error": "Por favor configurá tu usuario y contraseña de webmail.pjn.gov.ar en Configurar Envíos."
        }

    client = PJNWebmailClient(username=user, password=pwd)
    return client.search_and_sync_hearings()

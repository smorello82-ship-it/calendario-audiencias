import urllib.request
import urllib.parse
import http.cookiejar
import ssl
import json
import os
import re
from datetime import datetime
import database
import extractor

class PJNWebmailClient:
    """
    Cliente para interactuar directamente con el Webmail del PJN (Zimbra)
    a través del puerto seguro HTTPS (443).
    Permite autenticarse, buscar correos con PDFs adjuntos, descargarlos
    y extraer las audiencias automáticamente.
    """
    def __init__(self, username, password, base_url="https://webmail.pjn.gov.ar"):
        self.username = username.strip()
        # Si el usuario ingresó solo el nombre de usuario sin @pjn.gov.ar, normalizarlo si es necesario
        self.password = password.strip()
        self.base_url = base_url.rstrip("/")
        
        # Contexto SSL tolerante para certificados judiciales
        self.ssl_context = ssl.create_default_context()
        self.ssl_context.check_hostname = False
        self.ssl_context.verify_mode = ssl.CERT_NONE
        
        # Cookie jar para mantener la sesión abierta
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookie_jar),
            urllib.request.HTTPSHandler(context=self.ssl_context)
        )
        self.opener.addheaders = [
            ('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
        ]
        self.is_authenticated = False

    def login(self):
        """Inicia sesión en Zimbra Webmail y obtiene la cookie de autenticación ZM_AUTH_TOKEN"""
        # 1. Obtener la página principal y el token CSRF
        try:
            resp = self.opener.open(f"{self.base_url}/", timeout=12)
            html = resp.read().decode('utf-8', errors='ignore')
            
            m_csrf = re.search(r'name=["\']login_csrf["\']\s+value=["\']([^"\']+)["\']', html)
            login_csrf = m_csrf.group(1) if m_csrf else ""
        except Exception as e:
            return False, f"No se pudo conectar a {self.base_url}: {str(e)}"

        # 2. Enviar credenciales
        login_data = {
            "loginOp": "login",
            "login_csrf": login_csrf,
            "username": self.username,
            "password": self.password,
            "zrememberme": "1",
            "client": "preferred"
        }
        
        encoded_data = urllib.parse.urlencode(login_data).encode('utf-8')
        
        try:
            req = urllib.request.Request(f"{self.base_url}/", data=encoded_data, method="POST")
            login_resp = self.opener.open(req, timeout=15)
            login_html = login_resp.read().decode('utf-8', errors='ignore')

            # Verificar si se obtuvo la cookie ZM_AUTH_TOKEN
            cookies = {cookie.name: cookie.value for cookie in self.cookie_jar}
            if "ZM_AUTH_TOKEN" in cookies or "ZM_TEST" in cookies:
                self.is_authenticated = True
                return True, "Autenticación exitosa en Zimbra PJN"
            elif "zLoginError" in login_html or "nombre de usuario o contraseña incorrectos" in login_html.lower() or "login failed" in login_html.lower():
                return False, "Usuario o contraseña de webmail incorrectos"
            else:
                # Comprobar si hay redirección o cookie de sesión válida
                if any("auth" in c.lower() for c in cookies.keys()):
                    self.is_authenticated = True
                    return True, "Sesión iniciada"
                return False, "No se pudo autenticar. Verifique sus credenciales de PJN."
        except Exception as e:
            return False, f"Error durante el inicio de sesión: {str(e)}"

    def search_and_sync_hearings(self, max_emails=25):
        """
        Busca correos con adjuntos PDF en la bandeja de entrada, descarga los PDFs,
        extrae los datos de audiencias y los guarda en la base de datos si son nuevos.
        """
        if not self.is_authenticated:
            ok, msg = self.login()
            if not ok:
                return {"success": False, "error": msg}

        # Consultar la API REST de Zimbra
        # Query: correos con adjuntos de tipo pdf
        query = urllib.parse.quote('has:attachment filename:pdf')
        url_search = f"{self.base_url}/home/~/?query={query}&types=message&limit={max_emails}&fmt=json"
        
        try:
            req = urllib.request.Request(url_search)
            resp = self.opener.open(req, timeout=20)
            data_raw = resp.read().decode('utf-8', errors='ignore')
            data = json.loads(data_raw)
        except Exception as e:
            # Si el endpoint JSON directo no responde, intentar búsqueda general
            try:
                url_fallback = f"{self.base_url}/home/~/?types=message&limit={max_emails}&fmt=json"
                resp = self.opener.open(urllib.request.Request(url_fallback), timeout=20)
                data = json.loads(resp.read().decode('utf-8', errors='ignore'))
            except Exception as e2:
                return {"success": False, "error": f"Error al consultar la bandeja de Zimbra: {str(e2)}"}

        messages = data.get("m", [])
        if not messages and isinstance(data, list):
            messages = data

        nuevas_cargadas = 0
        ya_existentes = 0
        detalles = []

        os.makedirs("uploads", exist_ok=True)

        for m in messages:
            msg_id = m.get("id")
            subject = m.get("su") or m.get("subject") or "Sin Asunto"
            sender = ""
            if "e" in m and isinstance(m["e"], list):
                # Remitente
                for email_info in m["e"]:
                    if email_info.get("t") == "f": # From
                        sender = email_info.get("a", "")

            # Buscar partes del mensaje con adjuntos PDF
            # Endpoint para descargar mensaje completo o adjunto en Zimbra
            # Formato: /home/~/?id={msg_id}&part={part_id} o /home/~/?id={msg_id}
            # Revisar las partes si vienen en el JSON
            parts = m.get("mp", [])
            pdf_parts = self._find_pdf_parts(parts)

            if not pdf_parts:
                # Si no vinieron desglosadas las partes, intentar descargar el mensaje como .eml o inspeccionar
                pdf_parts = [{"part": "2", "name": f"notificacion_{msg_id}.pdf"}]

            for part_info in pdf_parts:
                part_id = part_info.get("part", "2")
                part_filename = part_info.get("name") or f"audiencia_msg_{msg_id}.pdf"
                if not part_filename.lower().endswith(".pdf"):
                    part_filename += ".pdf"

                # Limpiar nombre de archivo
                clean_filename = "".join(c for c in part_filename if c.isalnum() or c in (' ', '.', '_', '-')).strip()
                dest_path = os.path.join("uploads", clean_filename)

                # Descargar adjunto desde Zimbra
                url_part = f"{self.base_url}/home/~/?id={msg_id}&part={part_id}"
                try:
                    part_req = urllib.request.Request(url_part)
                    part_resp = self.opener.open(part_req, timeout=25)
                    content = part_resp.read()

                    # Validar si es un PDF real (cabecera %PDF)
                    if content.startswith(b'%PDF'):
                        with open(dest_path, "wb") as f:
                            f.write(content)

                        # Extraer datos de la audiencia con el extractor especializado
                        extracted = extractor.extract_hearing_from_pdf(dest_path)
                        
                        # Si tiene datos suficientes (carpeta judicial)
                        if extracted.get("carpeta"):
                            # Verificar si ya existe en la base de datos
                            existentes = database.get_audiencias(filtro="todas")
                            duplicada = any(
                                (a.get("carpeta") or "").strip().lower() == extracted["carpeta"].strip().lower() and
                                (a.get("fecha") or "").strip() == extracted["fecha"].strip()
                                for a in existentes
                            )

                            if not duplicada:
                                extracted["orden"] = database.get_next_orden()
                                extracted["archivo_pdf"] = clean_filename
                                new_id = database.save_audiencia(extracted)
                                nuevas_cargadas += 1
                                detalles.append({
                                    "carpeta": extracted["carpeta"],
                                    "fecha": extracted["fecha"],
                                    "hora": extracted["hora"],
                                    "asunto": subject,
                                    "pdf": clean_filename,
                                    "estado": "Cargada exitosamente"
                                })
                            else:
                                ya_existentes += 1
                except Exception as ex_down:
                    print(f"Error procesando adjunto {msg_id}: {ex_down}")

        # Guardar fecha de última sincronización
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
        """Busca recursivamente partes con archivos PDF dentro de la estructura de Zimbra"""
        pdf_list = []
        if isinstance(parts, list):
            for p in parts:
                pdf_list.extend(self._find_pdf_parts(p))
        elif isinstance(parts, dict):
            ct = p.get("ct", "").lower() # Content-Type
            filename = p.get("filename") or p.get("name") or ""
            part_id = p.get("part")
            if "pdf" in ct or filename.lower().endswith(".pdf"):
                pdf_list.append({"part": part_id, "name": filename})
            if "mp" in p:
                pdf_list.extend(self._find_pdf_parts(p["mp"]))
        return pdf_list

def sync_pjn_mail():
    """Función de utilidad que lee la configuración de la BD y ejecuta la sincronización"""
    cfg = database.get_config()
    user = cfg.get("pjn_user")
    pwd = cfg.get("pjn_pass")

    if not user or not pwd:
        return {
            "success": False,
            "error": "No se han configurado las credenciales del Webmail PJN en la sección de Configuración."
        }

    client = PJNWebmailClient(username=user, password=pwd)
    return client.search_and_sync_hearings()

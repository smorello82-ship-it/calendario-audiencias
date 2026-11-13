import re
import os
import pdfplumber
from datetime import datetime

DIAS_SEMANA = {
    0: "lunes",
    1: "martes",
    2: "miércoles",
    3: "jueves",
    4: "viernes",
    5: "sábado",
    6: "domingo"
}

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12
}

def clean_spacing(t: str) -> str:
    lines = [re.sub(r'[ \t]+', ' ', l).strip() for l in t.splitlines()]
    return "\n".join([l for l in lines if l])

def extract_hearing_from_pdf(pdf_path: str) -> dict:
    """
    Extrae los datos clave de una cédula o notificación de audiencia del Sistema Acusatorio:
    - Carpeta Judicial
    - Día, Fecha y Hora
    - Audiencia requerida
    - Modalidad y datos de Zoom (enlace, ID, código de acceso)
    - Tipo de Delito
    - Detenidos
    - Sede
    - Emails
    """
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"No se encontró el archivo: {pdf_path}")

    with pdfplumber.open(pdf_path) as pdf:
        pages_text = [page.extract_text() or "" for page in pdf.pages]

    raw_text = "\n".join(pages_text)
    full_text = clean_spacing(raw_text)

    # 1. SEDE
    sede = "Corrientes"
    if re.search(r"PASO DE LOS LIBRES", full_text, re.IGNORECASE):
        sede = "Paso de los Libres"
    elif re.search(r"GOYA", full_text, re.IGNORECASE):
        sede = "Goya"
    elif re.search(r"CORRIENTES", full_text, re.IGNORECASE):
        sede = "Corrientes"

    # 2. CARPETA JUDICIAL
    # Busca "CARPETA JUDICIAL N° 7456/2026/4", "CARPETA JUDICIAL N°: 8705/2026/3", "FCT 8648/2026/2" o número antes de CARPETA
    m_carpeta = re.search(r'(?:CARPETA\s+JUDICIAL\s+N[°º\.]*:?|FCT\s+)([0-9]{3,8}\/[0-9]{4}(?:\/[0-9]+)?)', full_text, re.IGNORECASE)
    if not m_carpeta:
        m_carpeta = re.search(r'CARPETA\s+JUDICIAL\s+N[°º\.]*:?\s*([\d\/\-]+)', full_text, re.IGNORECASE)
    if not m_carpeta:
        m_carpeta = re.search(r'([\d]{3,8}\/[\d]{4}(?:\/[\d]+)?)\s*.*?CARPETA\s+JUDICIAL', full_text, re.IGNORECASE)
    carpeta = m_carpeta.group(1).strip() if m_carpeta else ""

    # 3. FECHA Y HORA
    # Busca "el día miércoles 4 de noviembre del 2026, a las 10:00 horas" o "Miercoles 04 de noviembre de 2026 a las 08:00 horas"
    fecha_str = ""
    dia_str = ""
    hora_str = ""
    fecha_iso = ""

    # Primero buscar específicamente el bloque de fecha fijada si existe ("Lugar, fecha y hora de audiencia fijada : ...")
    m_fijada = re.search(r'(?:Lugar,\s*)?fecha\s+y\s+hora\s+de\s+audiencia\s+fijada\s*:\s*([^\n]+)', full_text, re.IGNORECASE)
    texto_fecha_busqueda = m_fijada.group(1) if m_fijada else full_text

    m_fh = re.search(
        r'(?:(?:el\s+d[ií]a\s+)?(lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)\s*,?\s*)?(\d{1,2})\s+de\s+([a-zA-Záéíóú]+)(?:\s+del?)?\s+(\d{4})\s*,?\s*a\s+las\s+(\d{1,2}:\d{2})',
        texto_fecha_busqueda,
        re.IGNORECASE
    )
    if not m_fh and m_fijada:
        m_fh = re.search(
            r'(?:(?:el\s+d[ií]a\s+)?(lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)\s*,?\s*)?(\d{1,2})\s+de\s+([a-zA-Záéíóú]+)(?:\s+del?)?\s+(\d{4})\s*,?\s*a\s+las\s+(\d{1,2}:\d{2})',
            full_text,
            re.IGNORECASE
        )

    if m_fh:
        dia_num = int(m_fh.group(2))
        mes_num = MESES.get(m_fh.group(3).lower(), 1)
        anio = int(m_fh.group(4))
        hora_str = m_fh.group(5)
        try:
            dt = datetime(anio, mes_num, dia_num)
            fecha_str = dt.strftime("%d/%m/%Y")
            fecha_iso = dt.strftime("%Y-%m-%d")
            dia_str = DIAS_SEMANA[dt.weekday()]
        except Exception:
            pass

    if not fecha_str:
        # Intento de formato alternativo DD/MM/YYYY
        m_alt = re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})', full_text)
        if m_alt:
            try:
                dt = datetime(int(m_alt.group(3)), int(m_alt.group(2)), int(m_alt.group(1)))
                fecha_str = dt.strftime("%d/%m/%Y")
                fecha_iso = dt.strftime("%Y-%m-%d")
                dia_str = DIAS_SEMANA[dt.weekday()]
            except Exception:
                fecha_str = m_alt.group(0)

    # 4. AUDIENCIA REQUERIDA
    # Busca el bloque correspondiente a "Audiencia requerida"
    m_aud = re.search(
        r'(?:\d+\.\s*)?Audiencia\s+requerida\s*:\s*(.*?)(?=\n(?:\d+\.|\bTipo de delito:|\bInvestigados:|\bPersona detenida|\bLugar,\s*fecha))',
        full_text,
        re.IGNORECASE | re.DOTALL
    )
    audiencia_req = ""
    if m_aud:
        audiencia_req = " ".join(m_aud.group(1).split())
        audiencia_req = re.sub(r'^\d+\.\s*', '', audiencia_req).strip()
    else:
        # Posible patrón inverso
        m_aud_inv = re.search(r'((?:Audiencia\s+|Multiprop[oó]sito\s+)[^\n]+(?:\n[^\n]+)*?)\s*\d+\.\s*Audiencia\s+requerida', full_text, re.IGNORECASE)
        if m_aud_inv:
            audiencia_req = " ".join(m_aud_inv.group(1).split())

    # 5. TIPO DE DELITO
    m_del = re.search(
        r'(?:\d+\.\s*)?(?:Tipo\s+de\s+delito|Delito\s+investigado)\s*:\s*(.*?)(?=\n(?:\d+\.|\bInvestigados?:|\bPersona detenida|\bInvestigado/a:|\bFecha del hecho:|\bSustancia))',
        full_text,
        re.IGNORECASE | re.DOTALL
    )
    delito = ""
    if m_del:
        delito = " ".join(m_del.group(1).split())
        delito = re.sub(r'^\d+\.\s*', '', delito).strip()

    # 6. MODALIDAD Y ZOOM
    modalidad_base = "PRESENCIAL"
    zoom_link = ""
    zoom_id = ""
    zoom_pass = ""

    # Buscar URL de Zoom
    m_zlink = re.search(r'(https://[^\s]*zoom\.us/j/[^\s]+)', raw_text)
    if m_zlink:
        zoom_link = m_zlink.group(1).strip()
        # Verificar si continúa en la línea siguiente con '=...' (parámetro pwd cortado)
        pos_fin = m_zlink.end()
        resto = raw_text[pos_fin:pos_fin+200]
        m_cont = re.search(r'^\s*\n?\s*(=[a-zA-Z0-9\.\-_]+)', resto)
        if m_cont:
            zoom_link += m_cont.group(1).strip()
        zoom_link = re.sub(r'[\s"\'\)]+$', '', zoom_link)

    # Buscar ID de reunión
    m_zid = re.search(r'(?:ID\s+de\s+reuni[oó]n|ID\.?\s+de\s+reuni[oó]n|ID)\s*:\s*([\d\s]+)', full_text, re.IGNORECASE)
    if m_zid:
        zoom_id = re.sub(r'\s+', ' ', m_zid.group(1).strip())

    # Buscar Código de acceso / Clave / Contraseña
    m_zpass = re.search(r'(?:C[oó]digo\s+de\s+acceso|clave(?:\s+de\s+acceso)?|contrase[ñn]a)\s*:\s*([a-zA-Z0-9]+)', full_text, re.IGNORECASE)
    if m_zpass:
        zoom_pass = m_zpass.group(1).strip()

    # Si dice expresamente PRESENCIAL en el bloque de audiencia fijada o modalidad asignada:
    es_presencial_explicito = bool(re.search(r'audiencia\s+(?:fijada|asignada|requerida)[^\n]*PRESENCIAL|\(\s*PRESENCIAL\s*\)', full_text, re.IGNORECASE))
    es_virtual = ("VIRTUAL" in full_text.upper() or
                  "MANERA REMOTA" in full_text.upper() or
                  bool(zoom_link) or
                  (bool(zoom_id) and bool(zoom_pass)))

    if es_virtual and not (es_presencial_explicito and not zoom_link and not zoom_id):
        modalidad_base = "VIRTUAL"
        if zoom_id and zoom_pass:
            modalidad = f"VIRTUAL (Zoom - ID: {zoom_id} / clave: {zoom_pass})"
        elif zoom_id:
            modalidad = f"VIRTUAL (Zoom - ID: {zoom_id})"
        else:
            modalidad = "VIRTUAL"
    else:
        modalidad = "PRESENCIAL"
        modalidad_base = "PRESENCIAL"

    # 7. DETENIDOS
    detenidos = "NO HAY PERSONAS DETENIDAS"
    # Formato Oficina Judicial Garantías:
    m_det_oj = re.search(
        r'Persona\s+detenida\s*-\s*Fecha\s+y\s+hora\s+de\s+detenci[oó]n\s*-\s*lugar\s+de\s+alojamiento\s*:\s*(.*?)(?=\n\s*(?:\d+\.|\bJuez\b|\bFiscal[ií]a\b|\bDefensa\b|\bNotif[ií]quese\b))',
        full_text,
        re.IGNORECASE | re.DOTALL
    )
    if m_det_oj:
        det_val = " ".join(m_det_oj.group(1).split()).strip()
        if re.search(r'no\s+se\s+hallan|no\s+hay', det_val, re.IGNORECASE):
            detenidos = "NO HAY PERSONAS DETENIDAS"
        else:
            # Buscar nombre del investigado para contexto si está disponible
            m_inv = re.search(r'(?:Investigado/a|IMPUTADO)\s*:\s*([^,\n]+)', full_text, re.IGNORECASE)
            imputado_nom = m_inv.group(1).strip() if m_inv else ""
            if imputado_nom and imputado_nom.lower() not in det_val.lower():
                detenidos = f"{imputado_nom}: {det_val}"
            else:
                detenidos = det_val
    elif re.search(r'NO\s+HAY\s+PERSONAS\s+DETENIDAS', full_text, re.IGNORECASE):
        detenidos = "NO HAY PERSONAS DETENIDAS"
    else:
        # Extraer imputados/investigados que tengan Detenido: SI
        det_matches = re.findall(
            r'Nombre\s+y\s+Apellido:\s*([^\n\.,]+).*?Detenido:\s*SI.*?Lugar\s+de\s+alojamiento:\s*([^\n]+)',
            full_text,
            re.IGNORECASE | re.DOTALL
        )
        if det_matches:
            det_parts = []
            for name, lugar in det_matches:
                clean_name = re.sub(r'\s+DNI.*', '', name).strip()
                # Limpiar texto residual de defensa o fecha
                clean_lugar = re.split(r'Defensa:|Fecha|DNI|b\)\s*Nombre', lugar, flags=re.IGNORECASE)[0].strip()
                clean_lugar = re.sub(r'[\.,;\s]+$', '', clean_lugar)
                det_parts.append(f"{clean_name} ({clean_lugar})")
            detenidos = "; ".join(det_parts)
        else:
            # Formato narrativo OFIJU: "• NOMBRE APELLIDO, DNI ... DETENIDO/A ... alojado/a (actualmente) en ..."
            oj_det_matches = re.findall(
                r'(?:^|\n)[•\-\*]?\s*([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{3,60}?),\s*DNI\s+N[°º\.]*[\s\S]{0,80}?\bDETENID[OA]\b[\s\S]{0,80}?alojad[oa](?:\s+actualmente)?\s+en\s+(?:el\s+|la\s+)?([^\.\(]+)',
                full_text,
                re.IGNORECASE
            )
            if oj_det_matches:
                det_parts = []
                for name, lugar in oj_det_matches:
                    clean_name = re.sub(r'\s+', ' ', name).strip()
                    clean_lugar = re.sub(r'\s+', ' ', lugar).strip(" .;,")
                    det_parts.append(f"{clean_name} ({clean_lugar})")
                detenidos = "; ".join(det_parts)
            elif re.search(r'Detenido:\s*SI|\bDETENID[OA]\b', full_text, re.IGNORECASE):
                detenidos = "SÍ"

    # 8. EMAILS
    emails = []
    for m in re.finditer(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', full_text):
        e = m.group(0).lower().strip()
        if e not in emails and not any(e.endswith(ext) for ext in [".png", ".jpg", ".jpeg"]):
            emails.append(e)

    # Ordenar y filtrar correos relevantes
    pjn_emails = [e for e in emails if "pjn.gov.ar" in e or "sper.gob.ar" in e]
    email_res = "; ".join(pjn_emails) if pjn_emails else "; ".join(emails)
    if not email_res:
        email_res = "jfcorrientes2@pjn.gov.ar; jfcorrientes2.secpenal@pjn.gov.ar"

    return {
        "carpeta": carpeta,
        "dia": dia_str,
        "fecha": fecha_str,
        "fecha_iso": fecha_iso,
        "hora": hora_str,
        "audiencia_requerida": audiencia_req,
        "modalidad": modalidad,
        "modalidad_tipo": modalidad_base,
        "zoom_link": zoom_link,
        "zoom_id": zoom_id,
        "zoom_pass": zoom_pass,
        "tipo_delito": delito,
        "detenidos": detenidos,
        "sede": sede,
        "email": email_res,
        "archivo_pdf": os.path.basename(pdf_path)
    }


def is_valid_hearing(extracted: dict) -> bool:
    """
    Determina si los datos extraídos corresponden realmente a una notificación
    o citación de audiencia (y no a un oficio común, resolución o agenda).
    """
    has_fecha = bool((extracted.get("fecha") or "").strip())
    has_hora = bool((extracted.get("hora") or "").strip())
    has_carpeta = bool((extracted.get("carpeta") or "").strip())
    has_aud = bool((extracted.get("audiencia_requerida") or "").strip())
    has_zoom = bool((extracted.get("zoom_link") or "").strip() or (extracted.get("zoom_id") or "").strip())

    # Toda audiencia fijada tiene fecha y hora, más al menos carpeta/audiencia/zoom
    return has_fecha and has_hora and (has_aud or has_zoom) and (has_carpeta or has_aud)

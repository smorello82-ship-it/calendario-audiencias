import sqlite3
import os
import openpyxl
from datetime import datetime, date

DB_PATH = "audiencias.db"

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS audiencias (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        orden INTEGER,
        dia TEXT,
        fecha TEXT,
        fecha_iso TEXT,
        hora TEXT,
        carpeta TEXT,
        audiencia_requerida TEXT,
        modalidad TEXT,
        modalidad_tipo TEXT,
        zoom_link TEXT,
        zoom_id TEXT,
        zoom_pass TEXT,
        tipo_delito TEXT,
        detenidos TEXT,
        sede TEXT,
        email TEXT,
        archivo_pdf TEXT,
        creado_el TEXT
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS configuracion (
        id INTEGER PRIMARY KEY,
        smtp_server TEXT,
        smtp_port INTEGER,
        smtp_user TEXT,
        smtp_pass TEXT,
        remitente TEXT,
        destinatarios TEXT,
        hora_envio TEXT,
        activo INTEGER DEFAULT 1,
        asunto TEXT
    )
    """)
    
    # Crear configuración por defecto si no existe
    cursor.execute("SELECT COUNT(*) FROM configuracion")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
        INSERT INTO configuracion (id, smtp_server, smtp_port, smtp_user, smtp_pass, remitente, destinatarios, hora_envio, activo, asunto)
        VALUES (1, 'smtp.gmail.com', 587, '', '', '', 'jfcorrientes2@pjn.gov.ar, jfcorrientes2.secpenal@pjn.gov.ar', '07:00', 1, '⚖️ Audiencias pendientes - Sistema Acusatorio')
        """)
    
    conn.commit()
    
    # Si la tabla de audiencias está vacía, importar desde el Excel existente
    cursor.execute("SELECT COUNT(*) FROM audiencias")
    total_aud = cursor.fetchone()[0]
    if total_aud == 0:
        importar_desde_excel(conn)
        
    conn.close()

def importar_desde_excel(conn):
    xlsx_files = [f for f in os.listdir(".") if f.endswith(".xlsx") and not f.startswith("~$")]
    if not xlsx_files:
        return
        
    excel_path = xlsx_files[0]
    try:
        wb = openpyxl.load_workbook(excel_path, data_only=True)
        if "Sistema Acusatorio" not in wb.sheetnames:
            return
            
        ws = wb["Sistema Acusatorio"]
        cursor = conn.cursor()
        
        for r in range(2, ws.max_row + 1):
            orden_val = ws.cell(r, 1).value
            carpeta_val = ws.cell(r, 5).value
            fecha_cell = ws.cell(r, 3).value
            
            # Solo importar si tiene número de carpeta o fecha real
            if not carpeta_val and not fecha_cell:
                continue
                
            orden = int(float(orden_val)) if orden_val is not None and str(orden_val).replace('.','',1).isdigit() else None
            if orden is None:
                continue
                
            dia = ws.cell(r, 2).value or ""
            fecha_cell = ws.cell(r, 3).value
            hora_cell = ws.cell(r, 4).value
            audiencia_req = ws.cell(r, 6).value or ""
            modalidad = ws.cell(r, 7).value or ""
            delito = ws.cell(r, 8).value or ""
            detenidos = ws.cell(r, 9).value or ""
            sede = ws.cell(r, 10).value or "Corrientes"
            email = ws.cell(r, 11).value or "jfcorrientes2@pjn.gov.ar; jfcorrientes2.secpenal@pjn.gov.ar"
            
            # Formatear Fecha
            fecha_str = ""
            fecha_iso = ""
            if isinstance(fecha_cell, (datetime, date)):
                fecha_str = fecha_cell.strftime("%d/%m/%Y")
                fecha_iso = fecha_cell.strftime("%Y-%m-%d")
            elif isinstance(fecha_cell, (int, float)):
                # Serial Excel date
                from datetime import timedelta
                base_date = datetime(1899, 12, 30)
                dt = base_date + timedelta(days=float(fecha_cell))
                fecha_str = dt.strftime("%d/%m/%Y")
                fecha_iso = dt.strftime("%Y-%m-%d")
            elif fecha_cell:
                fecha_str = str(fecha_cell).strip()
                try:
                    parts = fecha_str.split("/")
                    if len(parts) == 3:
                        dt = datetime(int(parts[2]), int(parts[1]), int(parts[0]))
                        fecha_iso = dt.strftime("%Y-%m-%d")
                except Exception:
                    pass

            # Formatear Hora
            hora_str = ""
            if isinstance(hora_cell, (datetime, date)):
                hora_str = hora_cell.strftime("%H:%M")
            elif hora_cell is not None:
                hora_str = str(hora_cell).strip()
                if len(hora_str) > 5 and ":" in hora_str:
                    hora_str = hora_str[:5]
                    
            # Modalidad y Zoom Link
            modalidad_str = str(modalidad).strip()
            es_virtual = "VIRTUAL" in modalidad_str.upper() or "ZOOM" in modalidad_str.upper()
            modalidad_tipo = "VIRTUAL" if es_virtual else "PRESENCIAL"
            
            zoom_link = ""
            zoom_id = ""
            zoom_pass = ""
            archivo_pdf = ""
            
            # Vincular PDFs existentes por carpeta
            carpeta_str = str(carpeta_val).strip() if carpeta_val else ""
            if "7456/2026/4" in carpeta_str:
                archivo_pdf = "audiencia virtual de Monsalvo.pdf"
                zoom_link = "https://pjn-gov-ar.zoom.us/j/81178426766?pwd=vMGLwMc3EQGOVQHauzBYKtsmeJvAZo.1"
                zoom_id = "811 7842 6766"
                zoom_pass = "110870"
            elif "8705/2026/3" in carpeta_str:
                archivo_pdf = "FCT 8705-2026-3 NOTIFICA AUDIENCIA DE FORMALIZACION.pdf"
                zoom_link = "https://pjn-gov-ar.zoom.us/j/89970322260?pwd=javyqX6bLBib1r6g3iTKW6rLTHyCc4.1"
                zoom_id = "899 7032 2260"
                zoom_pass = "598008"
            elif es_virtual:
                # Extraer zoom ID / pass si están en el texto de modalidad
                import re
                m_zid = re.search(r'ID:\s*([\d\s]+)', modalidad_str)
                if m_zid:
                    zoom_id = m_zid.group(1).strip()
                m_zpass = re.search(r'clave:\s*([a-zA-Z0-9]+)', modalidad_str)
                if m_zpass:
                    zoom_pass = m_zpass.group(1).strip()
                if zoom_id:
                    clean_id = zoom_id.replace(" ", "")
                    zoom_link = f"https://zoom.us/j/{clean_id}"

            cursor.execute("""
            INSERT INTO audiencias (
                orden, dia, fecha, fecha_iso, hora, carpeta, audiencia_requerida,
                modalidad, modalidad_tipo, zoom_link, zoom_id, zoom_pass,
                tipo_delito, detenidos, sede, email, archivo_pdf, creado_el
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                orden, str(dia).strip(), fecha_str, fecha_iso, hora_str, carpeta_str,
                str(audiencia_req).strip(), modalidad_str, modalidad_tipo,
                zoom_link, zoom_id, zoom_pass, str(delito).strip(),
                str(detenidos).strip(), str(sede).strip(), str(email).strip(),
                archivo_pdf, datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ))
            
        conn.commit()
        print(f"Importadas audiencias iniciales desde {excel_path}")
    except Exception as e:
        print(f"Error al importar Excel inicial: {e}")

def get_next_orden():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COALESCE(MAX(orden), 0) + 1 FROM audiencias")
    next_ord = cursor.fetchone()[0]
    conn.close()
    return next_ord

def get_audiencias(filtro="pendientes", sede=None, modalidad=None, busqueda=None):
    conn = get_connection()
    cursor = conn.cursor()
    
    today_iso = datetime.now().strftime("%Y-%m-%d")
    
    query = "SELECT * FROM audiencias WHERE 1=1"
    params = []
    
    if filtro == "pendientes":
        query += " AND (fecha_iso >= ? OR fecha_iso IS NULL OR fecha_iso = '')"
        params.append(today_iso)
    elif filtro == "hoy":
        query += " AND fecha_iso = ?"
        params.append(today_iso)
    elif filtro == "pasadas":
        query += " AND fecha_iso < ? AND fecha_iso != ''"
        params.append(today_iso)
        
    if sede and sede != "todas":
        query += " AND sede = ?"
        params.append(sede)
        
    if modalidad and modalidad != "todas":
        query += " AND modalidad_tipo = ?"
        params.append(modalidad)
        
    if busqueda:
        term = f"%{busqueda}%"
        query += " AND (carpeta LIKE ? OR audiencia_requerida LIKE ? OR tipo_delito LIKE ? OR detenidos LIKE ?)"
        params.extend([term, term, term, term])
        
    query += " ORDER BY CASE WHEN fecha_iso IS NULL OR fecha_iso = '' THEN 1 ELSE 0 END, fecha_iso ASC, hora ASC, orden ASC"
    
    cursor.execute(query, params)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

def get_audiencia_by_id(aud_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM audiencias WHERE id = ?", (aud_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def save_audiencia(data):
    conn = get_connection()
    cursor = conn.cursor()
    
    aud_id = data.get("id")
    orden = data.get("orden")
    if not orden:
        cursor.execute("SELECT COALESCE(MAX(orden), 0) + 1 FROM audiencias")
        orden = cursor.fetchone()[0]
        
    fecha = data.get("fecha", "").strip()
    fecha_iso = data.get("fecha_iso", "").strip()
    dia = data.get("dia", "").strip()
    
    # Calcular fecha_iso si no vino dada
    if fecha and not fecha_iso:
        try:
            parts = fecha.split("/")
            if len(parts) == 3:
                dt = datetime(int(parts[2]), int(parts[1]), int(parts[0]))
                fecha_iso = dt.strftime("%Y-%m-%d")
                if not dia:
                    from extractor import DIAS_SEMANA
                    dia = DIAS_SEMANA[dt.weekday()]
        except Exception:
            pass

    modalidad = data.get("modalidad", "").strip()
    modalidad_tipo = data.get("modalidad_tipo")
    if not modalidad_tipo:
        modalidad_tipo = "VIRTUAL" if ("VIRTUAL" in modalidad.upper() or "ZOOM" in modalidad.upper() or data.get("zoom_link")) else "PRESENCIAL"

    if aud_id:
        cursor.execute("""
        UPDATE audiencias SET
            orden = ?, dia = ?, fecha = ?, fecha_iso = ?, hora = ?, carpeta = ?,
            audiencia_requerida = ?, modalidad = ?, modalidad_tipo = ?,
            zoom_link = ?, zoom_id = ?, zoom_pass = ?, tipo_delito = ?,
            detenidos = ?, sede = ?, email = ?, archivo_pdf = ?
        WHERE id = ?
        """, (
            orden, dia, fecha, fecha_iso, data.get("hora", "").strip(),
            data.get("carpeta", "").strip(), data.get("audiencia_requerida", "").strip(),
            modalidad, modalidad_tipo, data.get("zoom_link", "").strip(),
            data.get("zoom_id", "").strip(), data.get("zoom_pass", "").strip(),
            data.get("tipo_delito", "").strip(), data.get("detenidos", "").strip(),
            data.get("sede", "Corrientes").strip(), data.get("email", "").strip(),
            data.get("archivo_pdf", "").strip(), aud_id
        ))
        res_id = aud_id
    else:
        cursor.execute("""
        INSERT INTO audiencias (
            orden, dia, fecha, fecha_iso, hora, carpeta, audiencia_requerida,
            modalidad, modalidad_tipo, zoom_link, zoom_id, zoom_pass,
            tipo_delito, detenidos, sede, email, archivo_pdf, creado_el
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            orden, dia, fecha, fecha_iso, data.get("hora", "").strip(),
            data.get("carpeta", "").strip(), data.get("audiencia_requerida", "").strip(),
            modalidad, modalidad_tipo, data.get("zoom_link", "").strip(),
            data.get("zoom_id", "").strip(), data.get("zoom_pass", "").strip(),
            data.get("tipo_delito", "").strip(), data.get("detenidos", "").strip(),
            data.get("sede", "Corrientes").strip(), data.get("email", "").strip(),
            data.get("archivo_pdf", "").strip(), datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ))
        res_id = cursor.lastrowid
        
    conn.commit()
    conn.close()
    return res_id

def delete_audiencia(aud_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM audiencias WHERE id = ?", (aud_id,))
    conn.commit()
    conn.close()

def get_config():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM configuracion WHERE id = 1")
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else {}

def save_config(cfg):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    UPDATE configuracion SET
        smtp_server = ?, smtp_port = ?, smtp_user = ?, smtp_pass = ?,
        remitente = ?, destinatarios = ?, hora_envio = ?, activo = ?, asunto = ?
    WHERE id = 1
    """, (
        cfg.get("smtp_server", "smtp.gmail.com").strip(),
        int(cfg.get("smtp_port", 587)),
        cfg.get("smtp_user", "").strip(),
        cfg.get("smtp_pass", "").strip(),
        cfg.get("remitente", "").strip(),
        cfg.get("destinatarios", "").strip(),
        cfg.get("hora_envio", "07:00").strip(),
        int(cfg.get("activo", 1)),
        cfg.get("asunto", "⚖️ Audiencias pendientes - Sistema Acusatorio").strip()
    ))
    conn.commit()
    conn.close()

def export_to_excel_file(output_path):
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    
    audiencias = get_audiencias(filtro="todas")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sistema Acusatorio"
    
    headers = [
        "Orden", "Día", "Fecha", "Hora", "Carpeta",
        "Audiencia requerida", "Modalidad", "Tipo de Delito",
        "Detenidos", "Sede", "Email", "Link Zoom", "Archivo PDF"
    ]
    ws.append(headers)
    
    # Estilo encabezado
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="1A3D7C", end_color="1A3D7C", fill_type="solid")
    center_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    thin_border = Border(
        left=Side(style='thin', color='DDDDDD'),
        right=Side(style='thin', color='DDDDDD'),
        top=Side(style='thin', color='DDDDDD'),
        bottom=Side(style='thin', color='DDDDDD')
    )
    
    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(1, col_idx)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center_align
    
    for row_idx, a in enumerate(audiencias, start=2):
        row_vals = [
            a["orden"],
            a["dia"],
            a["fecha"],
            a["hora"],
            a["carpeta"],
            a["audiencia_requerida"],
            a["modalidad"],
            a["tipo_delito"],
            a["detenidos"],
            a["sede"],
            a["email"],
            a["zoom_link"],
            a["archivo_pdf"]
        ]
        ws.append(row_vals)
        
        # Zebra striping
        row_fill = PatternFill(start_color="F5F8FC" if row_idx % 2 == 0 else "FFFFFF", fill_type="solid")
        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row_idx, col_idx)
            cell.fill = row_fill
            cell.border = thin_border
            if col_idx in [1, 2, 3, 4, 10]:
                cell.alignment = Alignment(horizontal="center", vertical="center")
            else:
                cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)

    # Anchos de columna
    col_widths = {1: 8, 2: 12, 3: 13, 4: 9, 5: 16, 6: 42, 7: 22, 8: 38, 9: 25, 10: 16, 11: 30, 12: 35, 13: 25}
    for col_idx, width in col_widths.items():
        col_letter = openpyxl.utils.get_column_letter(col_idx)
        ws.column_dimensions[col_letter].width = width
        
    wb.save(output_path)
    return output_path

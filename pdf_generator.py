import os
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas

class NumberedCanvas(canvas.Canvas):
    """Canvas para numeración dinámica 'Página X de Y'"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_number(num_pages)
            super().showPage()
        super().save()

    def draw_page_number(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#666666"))
        page_text = f"Página {self._pageNumber} de {page_count}"
        footer_text = "Sistema Acusatorio - Agenda Oficial de Audiencias | Documento listo para imprimir"
        
        # Ancho A4 apaisado: 841.89 puntos, alto: 595.27 puntos
        self.drawString(36, 20, footer_text)
        self.drawRightString(842 - 36, 20, page_text)
        self.restoreState()

def generate_hearings_pdf(audiencias, output_filename=None, solo_pendientes=True):
    """
    Genera el PDF oficial en formato A4 apaisado idéntico al emitido por el sistema judicial.
    Columnas: Orden | Día | Fecha | Hora | Carpeta | Audiencia requerida | Modalidad | Tipo de Delito | Detenidos | Sede
    """
    if not output_filename:
        os.makedirs("generated_reports", exist_ok=True)
        now_str = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        output_filename = os.path.join("generated_reports", f"Agenda_Audiencias_{now_str}.pdf")

    # Filtrar solo pendientes si se solicitó
    if solo_pendientes:
        today_iso = datetime.now().strftime("%Y-%m-%d")
        audiencias = [a for a in audiencias if (a.get("fecha_iso") or "") >= today_iso or not a.get("fecha_iso")]

    # Documento A4 Landscape con márgenes estrechos para máximo espacio de tabla
    doc = SimpleDocTemplate(
        output_filename,
        pagesize=landscape(A4),
        leftMargin=24,
        rightMargin=24,
        topMargin=24,
        bottomMargin=36
    )

    styles = getSampleStyleSheet()
    
    # Estilos de párrafo
    title_style = ParagraphStyle(
        'TitleStyle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=14,
        leading=16,
        textColor=colors.white,
        alignment=1 # Center
    )

    subtitle_style = ParagraphStyle(
        'SubtitleStyle',
        parent=styles['Normal'],
        fontName='Helvetica-Oblique',
        fontSize=9,
        leading=11,
        textColor=colors.HexColor("#1A3D7C"),
        alignment=1
    )

    cell_header_style = ParagraphStyle(
        'CellHeaderStyle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8.5,
        leading=10,
        textColor=colors.white,
        alignment=1
    )

    cell_body_style = ParagraphStyle(
        'CellBodyStyle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=7.5,
        leading=9.5,
        textColor=colors.HexColor("#222222")
    )

    cell_body_center = ParagraphStyle(
        'CellBodyCenter',
        parent=cell_body_style,
        alignment=1
    )

    cell_body_bold_center = ParagraphStyle(
        'CellBodyBoldCenter',
        parent=cell_body_style,
        fontName='Helvetica-Bold',
        alignment=1
    )

    story = []

    # 1. ENCABEZADO
    now = datetime.now()
    fecha_emision = now.strftime("%d/%m/%Y a las %H:%M hs")
    filtro_txt = "PENDIENTES DESDE HOY EN ADELANTE" if solo_pendientes else "TODAS LAS AUDIENCIAS REGISTRADAS"
    
    header_data = [
        [Paragraph("AGENDA DE AUDIENCIAS - SISTEMA ACUSATORIO", title_style)],
        [Paragraph(f"Emitido el {fecha_emision} | Total de audiencias: {len(audiencias)} ({filtro_txt})", subtitle_style)]
    ]
    
    header_table = Table(header_data, colWidths=[794])
    header_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, 0), colors.HexColor("#1A3D7C")),
        ('BACKGROUND', (0, 1), (0, 1), colors.HexColor("#E8EEF7")),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor("#1A3D7C")),
    ]))
    
    story.append(header_table)
    story.append(Spacer(1, 8))

    # 2. TABLA DE DATOS
    # Anchos de columnas para total 794 puntos:
    # Orden (28) | Día (48) | Fecha (52) | Hora (36) | Carpeta (60) | Aud. Req (170) | Mod (90) | Delito (160) | Detenidos (90) | Sede (60) = 794
    col_widths = [28, 48, 52, 36, 60, 170, 90, 160, 90, 60]
    
    table_headers = [
        Paragraph("<b>N°</b>", cell_header_style),
        Paragraph("<b>Día</b>", cell_header_style),
        Paragraph("<b>Fecha</b>", cell_header_style),
        Paragraph("<b>Hora</b>", cell_header_style),
        Paragraph("<b>Carpeta</b>", cell_header_style),
        Paragraph("<b>Audiencia requerida</b>", cell_header_style),
        Paragraph("<b>Modalidad</b>", cell_header_style),
        Paragraph("<b>Tipo de Delito</b>", cell_header_style),
        Paragraph("<b>Detenidos</b>", cell_header_style),
        Paragraph("<b>Sede</b>", cell_header_style),
    ]

    table_data = [table_headers]

    for idx, a in enumerate(audiencias, start=1):
        # Preparar texto de modalidad y Zoom
        mod_text = a.get("modalidad") or "PRESENCIAL"
        if a.get("zoom_id"):
            mod_text = f"<b>VIRTUAL</b><br/>ID: {a['zoom_id']}"
            if a.get("zoom_pass"):
                mod_text += f"<br/>Clave: {a['zoom_pass']}"
        elif "VIRTUAL" in mod_text.upper():
            mod_text = "<b>VIRTUAL</b>"
            
        row = [
            Paragraph(str(a.get("orden") or idx), cell_body_center),
            Paragraph(a.get("dia") or "", cell_body_center),
            Paragraph(f"<b>{a.get('fecha') or ''}</b>", cell_body_bold_center),
            Paragraph(a.get("hora") or "", cell_body_center),
            Paragraph(f"<b>{a.get('carpeta') or ''}</b>", cell_body_bold_center),
            Paragraph(a.get("audiencia_requerida") or "-", cell_body_style),
            Paragraph(mod_text, cell_body_center),
            Paragraph(a.get("tipo_delito") or "-", cell_body_style),
            Paragraph(a.get("detenidos") or "NO HAY", cell_body_style),
            Paragraph(a.get("sede") or "Corrientes", cell_body_center)
        ]
        table_data.append(row)

    if len(audiencias) == 0:
        empty_row = [Paragraph("<i>No se encontraron audiencias pendientes en el rango seleccionado.</i>", cell_body_center)] + [Paragraph("", cell_body_style)] * 9
        table_data.append(empty_row)

    data_table = Table(table_data, colWidths=col_widths, repeatRows=1)
    
    t_style = [
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#4A86E8")),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 3),
        ('RIGHTPADDING', (0, 0), (-1, -1), 3),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor("#1A3D7C")),
    ]

    # Zebra striping
    for r in range(1, len(table_data)):
        if r % 2 == 0:
            t_style.append(('BACKGROUND', (0, r), (-1, r), colors.HexColor("#F5F8FC")))
        else:
            t_style.append(('BACKGROUND', (0, r), (-1, r), colors.white))

    data_table.setStyle(TableStyle(t_style))
    story.append(data_table)

    # Construir PDF con NumberedCanvas
    doc.build(story, canvasmaker=NumberedCanvas)
    return output_filename

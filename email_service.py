import smtplib
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
import database
import pdf_generator

scheduler = BackgroundScheduler(timezone="America/Argentina/Buenos_Aires")

def enviar_email_audiencias(destinatarios_manual=None):
    """
    Genera el PDF con las audiencias pendientes desde hoy en adelante
    y lo envía por correo electrónico a los destinatarios configurados.
    """
    cfg = database.get_config()
    ahora = datetime.now()
    fecha_str = ahora.strftime("%d/%m/%Y")
    hora_str = ahora.strftime("%H:%M")

    # 1. Obtener audiencias pendientes
    pendientes = database.get_audiencias(filtro="pendientes")
    
    # 2. Generar el PDF
    os.makedirs("generated_reports", exist_ok=True)
    pdf_filename = os.path.join(
        "generated_reports",
        f"Agenda_Audiencias_{ahora.strftime('%Y-%m-%d')}.pdf"
    )
    pdf_generator.generate_hearings_pdf(pendientes, output_filename=pdf_filename, solo_pendientes=True)

    # 3. Determinar destinatarios
    if destinatarios_manual:
        dest_str = destinatarios_manual
    else:
        dest_str = cfg.get("destinatarios") or "jfcorrientes2@pjn.gov.ar, jfcorrientes2.secpenal@pjn.gov.ar"
        
    lista_destinatarios = [
        d.strip() for d in dest_str.replace(";", ",").split(",") if d.strip()
    ]
    
    if not lista_destinatarios:
        return {
            "success": False,
            "error": "No hay destinatarios de correo configurados.",
            "pdf_path": pdf_filename,
            "total_audiencias": len(pendientes)
        }

    # 4. Validar configuración SMTP
    smtp_server = cfg.get("smtp_server") or "smtp.gmail.com"
    smtp_port = cfg.get("smtp_port") or 587
    smtp_user = cfg.get("smtp_user") or ""
    smtp_pass = cfg.get("smtp_pass") or ""
    remitente = cfg.get("remitente") or smtp_user or "sistema-audiencias@pjn.gov.ar"
    asunto = f"{cfg.get('asunto', '⚖️ Audiencias pendientes - Sistema Acusatorio')} - {fecha_str}"

    if not smtp_user or not smtp_pass:
        return {
            "success": False,
            "simulado": True,
            "mensaje": "PDF generado correctamente. Para el envío real por correo, complete las credenciales SMTP en la pestaña de Configuración.",
            "pdf_path": pdf_filename,
            "total_audiencias": len(pendientes),
            "destinatarios": lista_destinatarios
        }

    # 5. Construir mensaje MIME
    msg = MIMEMultipart()
    msg['From'] = remitente
    msg['To'] = ", ".join(lista_destinatarios)
    msg['Subject'] = asunto

    cuerpo_texto = f"""Buen día,

Se adjunta la agenda de audiencias pendientes del Sistema Acusatorio desde hoy ({fecha_str}) en adelante.

Total de audiencias pendientes: {len(pendientes)}
Fecha de emisión: {fecha_str} {hora_str} hs

El archivo PDF adjunto se encuentra en formato A4 apaisado, listo para imprimir.

Saludos cordiales,
Sistema de Calendario y Audiencias Judiciales
"""

    cuerpo_html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: Arial, sans-serif; color: #333; line-height: 1.5; }}
  .box {{ max-width: 650px; margin: 0 auto; border: 1px solid #d0d7de; border-radius: 8px; overflow: hidden; }}
  .header {{ background-color: #1a3d7c; color: white; padding: 20px; text-align: center; }}
  .content {{ padding: 25px; background: #ffffff; }}
  .stat {{ display: inline-block; background-color: #e8eef7; color: #1a3d7c; padding: 10px 18px; border-radius: 6px; font-weight: bold; margin: 15px 0; }}
  .footer {{ background: #f6f8fa; padding: 15px; font-size: 12px; color: #666; text-align: center; border-top: 1px solid #eaecef; }}
</style>
</head>
<body>
  <div class="box">
    <div class="header">
      <h2 style="margin:0;">⚖️ SISTEMA ACUSATORIO</h2>
      <p style="margin:5px 0 0 0; opacity:0.9;">Agenda Oficial de Audiencias Pendientes</p>
    </div>
    <div class="content">
      <p>Estimados/as:</p>
      <p>Se adjunta el reporte oficial con todas las audiencias programadas del Sistema Acusatorio desde hoy <strong>{fecha_str}</strong> en adelante.</p>
      <div class="stat">📋 Total de Audiencias Pendientes: {len(pendientes)}</div>
      <p>El archivo PDF adjunto está formateado en hoja A4 horizontal y se encuentra <strong>listo para imprimir</strong>.</p>
      <p style="font-size:13px; color:#555;">Emitido automáticamente el {fecha_str} a las {hora_str} hs.</p>
    </div>
    <div class="footer">
      Sistema Automático de Gestión de Audiencias | Poder Judicial de la Nación
    </div>
  </div>
</body>
</html>
"""

    msg.attach(MIMEText(cuerpo_texto, 'plain', 'utf-8'))
    msg.attach(MIMEText(cuerpo_html, 'html', 'utf-8'))

    # Adjuntar PDF
    with open(pdf_filename, "rb") as f:
        part = MIMEApplication(f.read(), _subtype="pdf")
        part.add_header('Content-Disposition', 'attachment', filename=os.path.basename(pdf_filename))
        msg.attach(part)

    # 6. Conectar y Enviar
    try:
        if int(smtp_port) == 465:
            server = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=20)
        else:
            server = smtplib.SMTP(smtp_server, smtp_port, timeout=20)
            server.starttls()
            
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)
        server.quit()
        
        return {
            "success": True,
            "mensaje": f"Correo enviado exitosamente a {len(lista_destinatarios)} destinatario(s).",
            "pdf_path": pdf_filename,
            "total_audiencias": len(pendientes),
            "destinatarios": lista_destinatarios
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Error al conectar con el servidor SMTP: {str(e)}",
            "pdf_path": pdf_filename,
            "total_audiencias": len(pendientes)
        }

def scheduled_job():
    """Tarea que se ejecuta de lunes a viernes a las 07:00 AM"""
    cfg = database.get_config()
    if not cfg.get("activo", 1):
        print("Scheduler: Envío automático desactivado en configuración.")
        return
        
    print(f"Scheduler [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]: Ejecutando envío diario de audiencias pendientes...")
    res = enviar_email_audiencias()
    print("Scheduler resultado:", res)

def start_scheduler():
    """Inicia el programador para lunes a viernes a las 7:00 AM"""
    cfg = database.get_config()
    hora_str = cfg.get("hora_envio") or "07:00"
    try:
        hora, minuto = map(int, hora_str.split(":"))
    except Exception:
        hora, minuto = 7, 0

    # Días de lunes a viernes: mon-fri
    scheduler.add_job(
        scheduled_job,
        'cron',
        day_of_week='mon-fri',
        hour=hora,
        minute=minuto,
        id='envio_audiencias_diario',
        replace_existing=True
    )
    if not scheduler.running:
        scheduler.start()
        print(f"Scheduler iniciado: Envíos programados de lunes a viernes a las {hora:02d}:{minuto:02d} hs.")

import os
import sys
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_file, send_from_directory
from werkzeug.utils import secure_filename

import database
import extractor
import pdf_generator
import email_service

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
app.config['REPORTS_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'generated_reports')
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024  # 32 MB max

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['REPORTS_FOLDER'], exist_ok=True)

# Inicializar Base de Datos
database.init_db()

# Iniciar planificador de correos
email_service.start_scheduler()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/audiencias', methods=['GET'])
def list_audiencias():
    filtro = request.args.get('filtro', 'pendientes')
    sede = request.args.get('sede', 'todas')
    modalidad = request.args.get('modalidad', 'todas')
    busqueda = request.args.get('busqueda', '')
    
    auds = database.get_audiencias(filtro=filtro, sede=sede, modalidad=modalidad, busqueda=busqueda)
    
    # Agregar flags de estado respecto a hoy
    today_iso = datetime.now().strftime("%Y-%m-%d")
    for a in auds:
        f_iso = a.get("fecha_iso") or ""
        if f_iso == today_iso:
            a["estado_tiempo"] = "hoy"
        elif f_iso and f_iso < today_iso:
            a["estado_tiempo"] = "pasada"
        else:
            a["estado_tiempo"] = "pendiente"
            
    return jsonify({
        "success": True,
        "audiencias": auds,
        "total": len(auds),
        "fecha_actual": datetime.now().strftime("%d/%m/%Y")
    })

@app.route('/api/audiencias/<int:aud_id>', methods=['GET'])
def get_audiencia(aud_id):
    aud = database.get_audiencia_by_id(aud_id)
    if not aud:
        return jsonify({"success": False, "error": "Audiencia no encontrada"}), 404
    return jsonify({"success": True, "audiencia": aud})

@app.route('/api/audiencias', methods=['POST'])
def save_audiencia_endpoint():
    data = request.json or {}
    try:
        new_id = database.save_audiencia(data)
        saved = database.get_audiencia_by_id(new_id)
        return jsonify({"success": True, "id": new_id, "audiencia": saved})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

@app.route('/api/audiencias/<int:aud_id>', methods=['DELETE'])
def delete_audiencia_endpoint(aud_id):
    try:
        database.delete_audiencia(aud_id)
        return jsonify({"success": True, "message": "Audiencia eliminada"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

@app.route('/api/upload-pdf', methods=['POST'])
def upload_pdf():
    if 'pdf' not in request.files:
        return jsonify({"success": False, "error": "No se envió ningún archivo"}), 400
        
    file = request.files['pdf']
    if file.filename == '':
        return jsonify({"success": False, "error": "Archivo sin nombre"}), 400

    filename = secure_filename(file.filename)
    if not filename.lower().endswith('.pdf'):
        # Mantener nombre original seguro si secure_filename borra caracteres acentuados
        original_name = os.path.basename(file.filename)
        clean_name = "".join(c for c in original_name if c.isalnum() or c in (' ', '.', '_', '-')).strip()
        filename = clean_name if clean_name.lower().endswith('.pdf') else clean_name + ".pdf"

    saved_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(saved_path)

    # Extraer datos con el extractor especializado
    try:
        extracted = extractor.extract_hearing_from_pdf(saved_path)
        extracted["orden"] = database.get_next_orden()
        extracted["archivo_pdf"] = filename
        
        # Guardar automáticamente o devolver para confirmación
        auto_save = request.form.get("auto_save", "true").lower() in ("true", "1")
        if auto_save:
            new_id = database.save_audiencia(extracted)
            extracted["id"] = new_id

        return jsonify({
            "success": True,
            "extracted": extracted,
            "message": f"Archivo '{filename}' analizado y registrado correctamente."
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": f"Error al procesar el archivo PDF: {str(e)}"
        }), 500

@app.route('/uploads/<path:filename>')
def download_uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=True)

@app.route('/api/reporte-pdf', methods=['GET'])
def get_reporte_pdf():
    solo_pendientes = request.args.get('pendientes', 'true').lower() in ('true', '1')
    sede = request.args.get('sede', 'todas')
    modalidad = request.args.get('modalidad', 'todas')
    
    filtro_db = "pendientes" if solo_pendientes else "todas"
    auds = database.get_audiencias(filtro=filtro_db, sede=sede, modalidad=modalidad)
    
    now_str = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    pdf_path = os.path.join(app.config['REPORTS_FOLDER'], f"Agenda_Audiencias_{now_str}.pdf")
    pdf_generator.generate_hearings_pdf(auds, output_filename=pdf_path, solo_pendientes=solo_pendientes)
    
    download_name = f"Agenda_Audiencias_{datetime.now().strftime('%Y-%m-%d')}.pdf"
    return send_file(pdf_path, as_attachment=True, download_name=download_name)

@app.route('/api/export-excel', methods=['GET'])
def export_excel():
    now_str = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    output_path = os.path.join(app.config['REPORTS_FOLDER'], f"Audiencias_Acusatorio_{now_str}.xlsx")
    database.export_to_excel_file(output_path)
    return send_file(output_path, as_attachment=True, download_name=f"Audiencias_Sistema_Acusatorio_{datetime.now().strftime('%Y-%m-%d')}.xlsx")

@app.route('/api/config', methods=['GET'])
def get_config_endpoint():
    cfg = database.get_config()
    # Ocultar contraseña completa por seguridad
    safe_cfg = dict(cfg)
    if safe_cfg.get("smtp_pass"):
        safe_cfg["has_smtp_pass"] = True
        safe_cfg["smtp_pass_masked"] = "••••••••"
    else:
        safe_cfg["has_smtp_pass"] = False
        safe_cfg["smtp_pass_masked"] = ""
    return jsonify({"success": True, "config": safe_cfg})

@app.route('/api/config', methods=['POST'])
def save_config_endpoint():
    data = request.json or {}
    old_cfg = database.get_config()
    # Si la contraseña enviada está vacía pero ya había una, conservar la anterior
    if not data.get("smtp_pass") and old_cfg.get("smtp_pass"):
        data["smtp_pass"] = old_cfg.get("smtp_pass")
        
    database.save_config(data)
    # Actualizar scheduler
    email_service.start_scheduler()
    return jsonify({"success": True, "message": "Configuración guardada correctamente"})

@app.route('/api/enviar-email', methods=['POST'])
def trigger_email():
    data = request.json or {}
    destinatarios = data.get("destinatarios")
    resultado = email_service.enviar_email_audiencias(destinatarios_manual=destinatarios)
    return jsonify(resultado)

if __name__ == '__main__':
    print("Iniciando Sistema de Calendario y Audiencias del Sistema Acusatorio...")
    print("Acceso web disponible en: http://localhost:5000")
    app.run(host='0.0.0.0', port=5000, debug=False)

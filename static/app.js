// ========================================================
// SISTEMA ACUSATORIO - FRONTEND INTERACTIVO
// ========================================================

let state = {
  filtro: 'pendientes',
  sede: 'todas',
  modalidad: 'todas',
  busqueda: '',
  audiencias: [],
  currentEditingId: null
};

// Elementos DOM
const dropZone = document.getElementById('dropZone');
const pdfFileInput = document.getElementById('pdfFileInput');
const btnSelectFile = document.getElementById('btnSelectFile');
const uploadLoader = document.getElementById('uploadLoader');
const uploadLoaderText = document.getElementById('uploadLoaderText');

const tableBody = document.getElementById('tableBody');
const emptyState = document.getElementById('emptyState');
const tableResultsCount = document.getElementById('tableResultsCount');

const tabGroup = document.getElementById('tabGroup');
const filterSede = document.getElementById('filterSede');
const filterModalidad = document.getElementById('filterModalidad');
const searchInput = document.getElementById('searchInput');
const btnClearSearch = document.getElementById('btnClearSearch');

const btnDescargarPdf = document.getElementById('btnDescargarPdf');
const btnExportarExcel = document.getElementById('btnExportarExcel');
const btnEnviarEmailAhora = document.getElementById('btnEnviarEmailAhora');
const btnNuevaAudienciaManual = document.getElementById('btnNuevaAudienciaManual');
const btnOpenConfig = document.getElementById('btnOpenConfig');

// Modal Audiencia
const modalHearing = document.getElementById('modalHearing');
const formHearing = document.getElementById('formHearing');
const modalTitle = document.getElementById('modalTitle');
const modalAlertInfo = document.getElementById('modalAlertInfo');
const btnCloseModal = document.getElementById('btnCloseModal');
const btnCancelModal = document.getElementById('btnCancelModal');

// Modal Config
const modalConfig = document.getElementById('modalConfig');
const formConfig = document.getElementById('formConfig');
const btnCloseConfigModal = document.getElementById('btnCloseConfigModal');
const btnCancelConfigModal = document.getElementById('btnCancelConfigModal');

// Inicialización
document.addEventListener('DOMContentLoaded', () => {
  initLiveClock();
  setupEventListeners();
  loadAudiencias();
});

// Reloj en vivo
function initLiveClock() {
  const clockEl = document.getElementById('liveClock');
  const update = () => {
    const now = new Date();
    clockEl.textContent = now.toLocaleTimeString('es-AR', { hour12: false }) + ' hs';
  };
  update();
  setInterval(update, 1000);
}

// ========================================================
// EVENT LISTENERS
// ========================================================
function setupEventListeners() {
  // Pestañas
  tabGroup.addEventListener('click', (e) => {
    if (e.target.classList.contains('tab-btn')) {
      document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
      e.target.classList.add('active');
      state.filtro = e.target.dataset.filtro;
      loadAudiencias();
    }
  });

  // Filtros
  filterSede.addEventListener('change', (e) => {
    state.sede = e.target.value;
    loadAudiencias();
  });

  filterModalidad.addEventListener('change', (e) => {
    state.modalidad = e.target.value;
    loadAudiencias();
  });

  // Búsqueda con debounce
  let searchTimeout;
  searchInput.addEventListener('input', (e) => {
    state.busqueda = e.target.value.trim();
    btnClearSearch.style.display = state.busqueda ? 'inline' : 'none';
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(loadAudiencias, 250);
  });

  btnClearSearch.addEventListener('click', () => {
    searchInput.value = '';
    state.busqueda = '';
    btnClearSearch.style.display = 'none';
    loadAudiencias();
  });

  // Botón seleccionar archivo PDF
  btnSelectFile.addEventListener('click', (e) => {
    e.stopPropagation();
    pdfFileInput.click();
  });

  dropZone.addEventListener('click', () => {
    pdfFileInput.click();
  });

  pdfFileInput.addEventListener('change', (e) => {
    if (e.target.files.length > 0) {
      handleFilesUpload(e.target.files);
    }
  });

  // Drag & Drop
  ['dragenter', 'dragover'].forEach(eventName => {
    dropZone.addEventListener(eventName, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropZone.classList.add('dragover');
    });
  });

  ['dragleave', 'drop'].forEach(eventName => {
    dropZone.addEventListener(eventName, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropZone.classList.remove('dragover');
    });
  });

  dropZone.addEventListener('drop', (e) => {
    const dt = e.dataTransfer;
    const files = dt.files;
    if (files.length > 0) {
      handleFilesUpload(files);
    }
  });

  // Botón Descargar PDF
  btnDescargarPdf.addEventListener('click', () => {
    const url = `/api/reporte-pdf?pendientes=${state.filtro === 'pendientes' || state.filtro === 'hoy'}&sede=${state.sede}&modalidad=${state.modalidad}`;
    window.open(url, '_blank');
    showToast('Generando reporte PDF listo para imprimir...', 'info');
  });

  // Botón Exportar Excel
  btnExportarExcel.addEventListener('click', () => {
    window.open('/api/export-excel', '_blank');
    showToast('Exportando planilla Excel...', 'info');
  });

  // Botón Enviar Email
  btnEnviarEmailAhora.addEventListener('click', handleEnviarEmailManual);

  // Botón Nueva Audiencia Manual
  btnNuevaAudienciaManual.addEventListener('click', () => {
    openHearingModal();
  });

  // Modal Audiencia
  btnCloseModal.addEventListener('click', closeHearingModal);
  btnCancelModal.addEventListener('click', closeHearingModal);
  formHearing.addEventListener('submit', handleSaveHearing);

  // Modal Config
  btnOpenConfig.addEventListener('click', openConfigModal);
  btnCloseConfigModal.addEventListener('click', closeConfigModal);
  btnCancelConfigModal.addEventListener('click', closeConfigModal);
  formConfig.addEventListener('submit', handleSaveConfig);
}

// ========================================================
// CARGA Y RENDERIZADO DE AUDIENCIAS
// ========================================================
async function loadAudiencias() {
  try {
    const params = new URLSearchParams({
      filtro: state.filtro,
      sede: state.sede,
      modalidad: state.modalidad,
      busqueda: state.busqueda
    });

    const res = await fetch(`/api/audiencias?${params}`);
    const data = await res.json();

    if (data.success) {
      state.audiencias = data.audiencias;
      renderTable(data.audiencias);
      updateMetrics(data.audiencias, data.fecha_actual);
    }
  } catch (err) {
    console.error('Error cargando audiencias:', err);
    showToast('Error de conexión al cargar audiencias', 'error');
  }
}

function updateMetrics(audiencias, fechaActual) {
  document.getElementById('statHoyFecha').textContent = fechaActual;

  // Estadísticas globales (se basan en la base completa y filtrada)
  const pendientes = audiencias.filter(a => a.estado_tiempo !== 'pasada').length;
  const hoy = audiencias.filter(a => a.estado_tiempo === 'hoy').length;
  const virtuales = audiencias.filter(a => a.modalidad_tipo === 'VIRTUAL').length;
  const presenciales = audiencias.filter(a => a.modalidad_tipo === 'PRESENCIAL').length;

  document.getElementById('statPendientes').textContent = pendientes;
  document.getElementById('statHoy').textContent = hoy;
  document.getElementById('statVirtuales').textContent = virtuales;
  document.getElementById('statPresenciales').textContent = presenciales;
}

function renderTable(audiencias) {
  tableBody.innerHTML = '';

  if (audiencias.length === 0) {
    emptyState.style.display = 'block';
    tableResultsCount.textContent = '0 audiencias encontradas';
    return;
  }

  emptyState.style.display = 'none';
  tableResultsCount.textContent = `Mostrando ${audiencias.length} audiencia(s)`;

  audiencias.forEach(a => {
    const tr = document.createElement('tr');
    if (a.estado_tiempo === 'hoy') tr.classList.add('row-hoy');
    else if (a.estado_tiempo === 'pasada') tr.classList.add('row-pasada');

    // Formato de Modalidad y Zoom
    let modalidadHtml = '';
    const esVirtual = a.modalidad_tipo === 'VIRTUAL' || (a.modalidad && a.modalidad.toUpperCase().includes('VIRTUAL'));

    if (esVirtual) {
      modalidadHtml += `<span class="badge badge-virtual">📹 VIRTUAL</span>`;
      
      // Si tiene link o ID de Zoom, renderizar botón directo
      if (a.zoom_link) {
        modalidadHtml += `
          <div>
            <a href="${a.zoom_link}" target="_blank" rel="noopener noreferrer" class="btn-zoom" title="Abrir reunión en Zoom">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><path d="M17 10.5V7c0-.55-.45-1-1-1H4c-.55 0-1 .45-1 1v10c0 .55.45 1 1 1h12c.55 0 1-.45 1-1v-3.5l4 4v-11l-4 4z"/></svg>
              Entrar a Zoom
            </a>
          </div>
        `;
      }
      
      if (a.zoom_id) {
        modalidadHtml += `
          <div class="zoom-info-box">
            <strong>ID:</strong> ${a.zoom_id}
            ${a.zoom_pass ? `<br/><strong>Clave:</strong> ${a.zoom_pass}` : ''}
          </div>
        `;
      }
    } else {
      modalidadHtml = `<span class="badge badge-presencial">🏛️ PRESENCIAL</span>`;
    }

    // Detenidos badge
    let detenidosHtml = a.detenidos || '-';
    if (detenidosHtml && !detenidosHtml.toUpperCase().includes('NO HAY') && detenidosHtml !== '-') {
      detenidosHtml = `<span class="badge badge-detenido">⚠️ DETENIDOS</span><br/>${detenidosHtml}`;
    }

    // Botón descargar PDF original
    let archivoPdfHtml = '';
    if (a.archivo_pdf) {
      archivoPdfHtml = `
        <a href="/uploads/${encodeURIComponent(a.archivo_pdf)}" class="btn-download-pdf" title="Descargar notificación original (${a.archivo_pdf})" target="_blank">
          📄 PDF
        </a>
      `;
    }

    tr.innerHTML = `
      <td style="text-align:center; font-weight:bold;">${a.orden || '-'}</td>
      <td style="text-transform: capitalize;">${a.dia || '-'}</td>
      <td><strong>${a.fecha || '-'}</strong></td>
      <td style="font-weight:600; color: #1a3d7c;">${a.hora || '-'}</td>
      <td><strong style="color: #0f172a;">${a.carpeta || '-'}</strong></td>
      <td>${escapeHtml(a.audiencia_requerida || '-')}</td>
      <td>${modalidadHtml}</td>
      <td>${escapeHtml(a.tipo_delito || '-')}</td>
      <td>${detenidosHtml}</td>
      <td><span class="badge badge-sede">${a.sede || 'Corrientes'}</span></td>
      <td style="text-align:center; white-space:nowrap;">
        <div style="display:flex; gap:4px; justify-content:center; align-items:center;">
          ${archivoPdfHtml}
          <button class="btn-icon" onclick="editHearing(${a.id})" title="Editar audiencia">✏️</button>
          <button class="btn-icon btn-delete" onclick="deleteHearing(${a.id}, '${escapeHtml(a.carpeta || '')}')" title="Eliminar audiencia">🗑️</button>
        </div>
      </td>
    `;

    tableBody.appendChild(tr);
  });
}

// ========================================================
// PROCESAMIENTO DE ARCHIVOS PDF
// ========================================================
async function handleFilesUpload(files) {
  for (let i = 0; i < files.length; i++) {
    const file = files[i];
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      showToast(`El archivo ${file.name} no es un PDF`, 'error');
      continue;
    }

    uploadLoader.style.display = 'flex';
    uploadLoaderText.textContent = `Procesando y extrayendo datos de: ${file.name}...`;

    const formData = new FormData();
    formData.append('pdf', file);
    formData.append('auto_save', 'false'); // Queremos mostrar la confirmación previa con los datos extraídos

    try {
      const res = await fetch('/api/upload-pdf', {
        method: 'POST',
        body: formData
      });
      const data = await res.json();

      uploadLoader.style.display = 'none';

      if (data.success) {
        showToast(`Documento analizado con éxito`, 'success');
        // Abrir modal con los datos extraídos para verificación y guardado
        openHearingModal(data.extracted, true);
      } else {
        showToast(`Error: ${data.error}`, 'error');
      }
    } catch (err) {
      uploadLoader.style.display = 'none';
      console.error(err);
      showToast(`Error al subir ${file.name}`, 'error');
    }
  }

  pdfFileInput.value = '';
}

// ========================================================
// MODAL AUDIENCIA (CREAR / EDITAR / CONFIRMAR)
// ========================================================
function openHearingModal(data = null, isFromPdf = false) {
  modalHearing.style.display = 'flex';
  formHearing.reset();

  if (isFromPdf) {
    modalTitle.textContent = '✨ Confirmar Datos Extraídos del PDF';
    modalAlertInfo.style.display = 'block';
  } else if (data && data.id) {
    modalTitle.textContent = '✏️ Editar Audiencia';
    modalAlertInfo.style.display = 'none';
  } else {
    modalTitle.textContent = '➕ Nueva Audiencia (Carga Manual)';
    modalAlertInfo.style.display = 'none';
  }

  if (data) {
    document.getElementById('editId').value = data.id || '';
    document.getElementById('editArchivoPdf').value = data.archivo_pdf || '';
    document.getElementById('editModalidadTipo').value = data.modalidad_tipo || '';

    document.getElementById('inputOrden').value = data.orden || '';
    document.getElementById('inputCarpeta').value = data.carpeta || '';
    document.getElementById('inputFecha').value = data.fecha || '';
    document.getElementById('inputDia').value = data.dia || '';
    document.getElementById('inputHora').value = data.hora || '';
    document.getElementById('inputSede').value = data.sede || 'Corrientes';
    document.getElementById('inputAudiencia').value = data.audiencia_requerida || '';
    document.getElementById('inputModalidad').value = data.modalidad || 'VIRTUAL';
    document.getElementById('inputZoomLink').value = data.zoom_link || '';
    document.getElementById('inputZoomId').value = data.zoom_id || '';
    document.getElementById('inputZoomPass').value = data.zoom_pass || '';
    document.getElementById('inputDelito').value = data.tipo_delito || '';
    document.getElementById('inputDetenidos').value = data.detenidos || 'NO HAY PERSONAS DETENIDAS';
    document.getElementById('inputEmail').value = data.email || 'jfcorrientes2@pjn.gov.ar; jfcorrientes2.secpenal@pjn.gov.ar';
  } else {
    document.getElementById('editId').value = '';
    document.getElementById('editArchivoPdf').value = '';
    document.getElementById('inputEmail').value = 'jfcorrientes2@pjn.gov.ar; jfcorrientes2.secpenal@pjn.gov.ar';
    document.getElementById('inputDetenidos').value = 'NO HAY PERSONAS DETENIDAS';
    document.getElementById('inputModalidad').value = 'VIRTUAL';
    document.getElementById('inputSede').value = 'Corrientes';
  }
}

function closeHearingModal() {
  modalHearing.style.display = 'none';
  state.currentEditingId = null;
}

async function handleSaveHearing(e) {
  e.preventDefault();

  const payload = {
    id: document.getElementById('editId').value || null,
    orden: document.getElementById('inputOrden').value,
    carpeta: document.getElementById('inputCarpeta').value,
    fecha: document.getElementById('inputFecha').value,
    dia: document.getElementById('inputDia').value,
    hora: document.getElementById('inputHora').value,
    sede: document.getElementById('inputSede').value,
    audiencia_requerida: document.getElementById('inputAudiencia').value,
    modalidad: document.getElementById('inputModalidad').value,
    modalidad_tipo: document.getElementById('inputZoomLink').value ? 'VIRTUAL' : 'PRESENCIAL',
    zoom_link: document.getElementById('inputZoomLink').value,
    zoom_id: document.getElementById('inputZoomId').value,
    zoom_pass: document.getElementById('inputZoomPass').value,
    tipo_delito: document.getElementById('inputDelito').value,
    detenidos: document.getElementById('inputDetenidos').value,
    email: document.getElementById('inputEmail').value,
    archivo_pdf: document.getElementById('editArchivoPdf').value
  };

  try {
    const res = await fetch('/api/audiencias', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();

    if (data.success) {
      showToast('Audiencia guardada correctamente', 'success');
      closeHearingModal();
      loadAudiencias();
    } else {
      showToast(`Error al guardar: ${data.error}`, 'error');
    }
  } catch (err) {
    console.error(err);
    showToast('Error de conexión al guardar audiencia', 'error');
  }
}

window.editHearing = async function(id) {
  try {
    const res = await fetch(`/api/audiencias/${id}`);
    const data = await res.json();
    if (data.success) {
      openHearingModal(data.audiencia);
    }
  } catch (err) {
    showToast('Error al cargar datos para edición', 'error');
  }
};

window.deleteHearing = async function(id, carpeta) {
  if (!confirm(`¿Estás seguro de que deseas eliminar la audiencia de la carpeta ${carpeta}?`)) {
    return;
  }

  try {
    const res = await fetch(`/api/audiencias/${id}`, { method: 'DELETE' });
    const data = await res.json();
    if (data.success) {
      showToast('Audiencia eliminada', 'success');
      loadAudiencias();
    }
  } catch (err) {
    showToast('Error al eliminar audiencia', 'error');
  }
};

// ========================================================
// MODAL CONFIGURACIÓN SMTP Y ENVÍO AUTOMÁTICO
// ========================================================
async function openConfigModal() {
  modalConfig.style.display = 'flex';
  try {
    const res = await fetch('/api/config');
    const data = await res.json();
    if (data.success) {
      const c = data.config;
      document.getElementById('cfgHoraEnvio').value = c.hora_envio || '07:00';
      document.getElementById('cfgActivo').value = c.activo !== undefined ? c.activo : 1;
      document.getElementById('cfgAsunto').value = c.asunto || '⚖️ Audiencias pendientes - Sistema Acusatorio';
      document.getElementById('cfgDestinatarios').value = c.destinatarios || '';
      document.getElementById('cfgSmtpServer').value = c.smtp_server || 'smtp.gmail.com';
      document.getElementById('cfgSmtpPort').value = c.smtp_port || 587;
      document.getElementById('cfgSmtpUser').value = c.smtp_user || '';
      document.getElementById('cfgSmtpPass').value = '';
      if (c.has_smtp_pass) {
        document.getElementById('cfgSmtpPass').placeholder = '•••••••• (Contraseña guardada - Dejar vacío para no cambiar)';
      }
    }
  } catch (err) {
    showToast('Error al cargar la configuración', 'error');
  }
}

function closeConfigModal() {
  modalConfig.style.display = 'none';
}

async function handleSaveConfig(e) {
  e.preventDefault();

  const payload = {
    hora_envio: document.getElementById('cfgHoraEnvio').value,
    activo: parseInt(document.getElementById('cfgActivo').value),
    asunto: document.getElementById('cfgAsunto').value,
    destinatarios: document.getElementById('cfgDestinatarios').value,
    smtp_server: document.getElementById('cfgSmtpServer').value,
    smtp_port: parseInt(document.getElementById('cfgSmtpPort').value),
    smtp_user: document.getElementById('cfgSmtpUser').value,
    smtp_pass: document.getElementById('cfgSmtpPass').value
  };

  try {
    const res = await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (data.success) {
      showToast('Configuración guardada exitosamente', 'success');
      closeConfigModal();
    } else {
      showToast(`Error: ${data.error}`, 'error');
    }
  } catch (err) {
    showToast('Error al guardar configuración', 'error');
  }
}

// ========================================================
// ENVÍO DE EMAIL MANUAL
// ========================================================
async function handleEnviarEmailManual() {
  if (!confirm('¿Desea generar el PDF de audiencias pendientes y enviarlo por correo electrónico AHORA?')) {
    return;
  }

  showToast('Generando PDF y conectando con el servidor de correo...', 'info');

  try {
    const res = await fetch('/api/enviar-email', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({})
    });
    const data = await res.json();

    if (data.success) {
      showToast(`✅ ${data.mensaje}`, 'success');
    } else if (data.simulado) {
      showToast(`ℹ️ ${data.mensaje}`, 'info');
      // Abrir modal de configuración para que pueda completar credenciales
      setTimeout(openConfigModal, 1200);
    } else {
      showToast(`❌ Error al enviar correo: ${data.error}`, 'error');
    }
  } catch (err) {
    showToast('Error de conexión al enviar email', 'error');
  }
}

// ========================================================
// TOAST NOTIFICATIONS & UTILS
// ========================================================
function showToast(message, type = 'info') {
  const container = document.getElementById('toastContainer');
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  
  let icon = 'ℹ️';
  if (type === 'success') icon = '✅';
  if (type === 'error') icon = '⚠️';

  toast.innerHTML = `<span>${icon}</span> <span>${escapeHtml(message)}</span>`;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(10px)';
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

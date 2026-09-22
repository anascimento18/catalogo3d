// Script do Painel Administrativo 3D
let adminCategories = [];
let selectedFiles3D = [];
let selectedFileImg = null;
let selectedGalleryImgs = [];

document.addEventListener('DOMContentLoaded', () => {
  setupTabs();
  setupDropzones();
  loadAdminCategories();
  loadAdminModels();
  setupUploadForm();
  setupLogout();
});

// 1. Controle das Abas (Modelos / Novo Upload / Pedidos)
function setupTabs() {
  const tabs = document.querySelectorAll('.admin-tab');
  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      tabs.forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(c => c.style.display = 'none');

      tab.classList.add('active');
      const tabId = tab.dataset.tab;
      if (tabId === 'models') {
        document.getElementById('tabModels').style.display = 'block';
        loadAdminModels();
      } else if (tabId === 'upload') {
        document.getElementById('tabUpload').style.display = 'block';
      } else if (tabId === 'orders') {
        document.getElementById('tabOrders').style.display = 'block';
        loadAdminOrders();
      }
    });
  });
}

// 2. Carrega Categorias no Select de Upload
async function loadAdminCategories() {
  const select = document.getElementById('modelCategory');
  if (!select) return;

  try {
    const res = await fetch('/api/public/categories');
    const categories = await res.json();
    adminCategories = categories;

    select.innerHTML = categories.map(c => `
      <option value="${c.id}">${c.name}</option>
    `).join('');
  } catch (err) {
    console.error('Erro ao carregar categorias:', err);
  }
}

// 3. Carrega Lista de Modelos Cadastrados
async function loadAdminModels() {
  const tbody = document.getElementById('modelsTableBody');
  if (!tbody) return;

  tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; padding: 24px; color: #a1a1aa;">Carregando modelos...</td></tr>`;

  try {
    const res = await fetch('/api/admin/models');
    if (res.status === 401) {
      window.location.href = '/loginAdmin';
      return;
    }
    const models = await res.json();

    if (models.length === 0) {
      tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; padding: 32px; color: #71717a;">Nenhum modelo cadastrado ainda. Use a aba "Novo Upload" para adicionar seu primeiro arquivo.</td></tr>`;
      return;
    }

    tbody.innerHTML = models.map(m => {
      const priceText = m.price ? `R$ ${m.price.toFixed(2).replace('.', ',')}` : '0,00';
      const showPriceBadge = m.show_price 
        ? `<span style="color:#22c55e;font-weight:600;">Sim</span>` 
        : `<span style="color:#eab308;font-weight:600;">Sob Consulta</span>`;

      const partsInfo = m.parts_count && m.parts_count > 1 
        ? `<span style="color:#38bdf8;font-weight:600;">📦 ${m.parts_count} peças</span> • ` 
        : '';

      const photosInfo = m.gallery_images && m.gallery_images.length > 0
        ? `<span style="color:#a1a1aa;">📸 ${m.gallery_images.length + 1} fotos</span> • `
        : '';

      return `
        <tr>
          <td style="width: 60px;">
            <img src="/api/public/images/${m.image_filename}" style="width: 48px; height: 48px; object-fit: cover; border-radius: 6px;" alt="Foto">
          </td>
          <td>
            <strong>${escapeHtml(m.title)}</strong><br>
            <small style="color: #71717a;">${partsInfo}${photosInfo}${escapeHtml(m.file_3d_filename)}</small>
          </td>
          <td>${escapeHtml(m.category_name)}</td>
          <td><span class="badge-tag">${m.file_format}</span></td>
          <td>${priceText}</td>
          <td>${showPriceBadge}</td>
          <td>🔥 ${m.order_count || 0}</td>
          <td style="text-align: right; white-space: nowrap;">
            <a href="/api/admin/models/${m.id}/download" class="btn-action download" title="Baixar arquivo 3D original">
              <i data-lucide="download" style="width:14px;height:14px;"></i>
              <span>Download 3D</span>
            </a>
            <button class="btn-action delete" onclick="deleteModel(${m.id}, '${escapeHtml(m.title)}')" title="Excluir modelo">
              <i data-lucide="trash-2" style="width:14px;height:14px;"></i>
              <span>Excluir</span>
            </button>
          </td>
        </tr>
      `;
    }).join('');

    if (window.lucide) lucide.createIcons();
  } catch (err) {
    console.error('Erro ao listar modelos:', err);
    tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; padding: 24px; color: #ef233c;">Erro ao carregar dados do servidor.</td></tr>`;
  }
}

// 4. Download e Exclusão de Modelos
async function deleteModel(id, title) {
  if (!confirm(`Tem certeza que deseja excluir o modelo "${title}" e seus arquivos do servidor?`)) {
    return;
  }

  try {
    const res = await fetch(`/api/admin/models/${id}`, { method: 'DELETE' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Erro ao excluir');

    loadAdminModels();
  } catch (err) {
    alert(err.message || 'Erro ao excluir');
  }
}

// 5. Configuração dos Dropzones com Suporte a Múltiplos Arquivos e Galeria
function setupDropzones() {
  const drop3D = document.getElementById('dropzone3D');
  const input3D = document.getElementById('inputFile3D');
  const label3D = document.getElementById('label3D');

  const dropImg = document.getElementById('dropzoneImg');
  const inputImg = document.getElementById('inputFileImg');
  const labelImg = document.getElementById('labelImg');

  const dropGallery = document.getElementById('dropzoneGallery');
  const inputGallery = document.getElementById('inputFileGallery');
  const labelGallery = document.getElementById('labelGallery');

  // Dropzone 3D (Múltiplas Peças / Arquivos)
  drop3D.addEventListener('click', () => input3D.click());
  input3D.addEventListener('change', () => {
    if (input3D.files.length) {
      selectedFiles3D = Array.from(input3D.files);
      if (selectedFiles3D.length === 1) {
        label3D.innerHTML = `<span style="color:#22c55e;">✓ ${selectedFiles3D[0].name}</span> (${(selectedFiles3D[0].size/1024/1024).toFixed(2)} MB)`;
      } else {
        const totalSize = (selectedFiles3D.reduce((acc, f) => acc + f.size, 0)/1024/1024).toFixed(2);
        label3D.innerHTML = `<span style="color:#38bdf8;font-weight:700;">✓ ${selectedFiles3D.length} arquivos/peças selecionadas</span> (Total: ${totalSize} MB)`;
      }
    }
  });

  // Dropzone Imagem de Capa
  dropImg.addEventListener('click', () => inputImg.click());
  inputImg.addEventListener('change', () => {
    if (inputImg.files.length) {
      selectedFileImg = inputImg.files[0];
      labelImg.innerHTML = `<span style="color:#22c55e;">✓ ${selectedFileImg.name}</span> (${(selectedFileImg.size/1024).toFixed(1)} KB)`;
    }
  });

  // Dropzone Fotos da Galeria (Múltiplas)
  if (dropGallery && inputGallery) {
    dropGallery.addEventListener('click', () => inputGallery.click());
    inputGallery.addEventListener('change', () => {
      if (inputGallery.files.length) {
        selectedGalleryImgs = Array.from(inputGallery.files);
        labelGallery.innerHTML = `<span style="color:#22c55e;font-weight:700;">✓ ${selectedGalleryImgs.length} foto(s) adicional(is) selecionada(s)</span>`;
      }
    });
  }

  // Drag over effects
  const allZones = [drop3D, dropImg];
  if (dropGallery) allZones.push(dropGallery);

  allZones.forEach(zone => {
    zone.addEventListener('dragover', (e) => { e.preventDefault(); zone.classList.add('dragover'); });
    zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
  });

  drop3D.addEventListener('drop', (e) => {
    e.preventDefault();
    drop3D.classList.remove('dragover');
    if (e.dataTransfer.files.length) {
      selectedFiles3D = Array.from(e.dataTransfer.files);
      input3D.files = e.dataTransfer.files;
      if (selectedFiles3D.length === 1) {
        label3D.innerHTML = `<span style="color:#22c55e;">✓ ${selectedFiles3D[0].name}</span> (${(selectedFiles3D[0].size/1024/1024).toFixed(2)} MB)`;
      } else {
        const totalSize = (selectedFiles3D.reduce((acc, f) => acc + f.size, 0)/1024/1024).toFixed(2);
        label3D.innerHTML = `<span style="color:#38bdf8;font-weight:700;">✓ ${selectedFiles3D.length} arquivos/peças selecionadas</span> (Total: ${totalSize} MB)`;
      }
    }
  });

  dropImg.addEventListener('drop', (e) => {
    e.preventDefault();
    dropImg.classList.remove('dragover');
    if (e.dataTransfer.files.length) {
      selectedFileImg = e.dataTransfer.files[0];
      inputImg.files = e.dataTransfer.files;
      labelImg.innerHTML = `<span style="color:#22c55e;">✓ ${selectedFileImg.name}</span> (${(selectedFileImg.size/1024).toFixed(1)} KB)`;
    }
  });

  if (dropGallery && inputGallery) {
    dropGallery.addEventListener('drop', (e) => {
      e.preventDefault();
      dropGallery.classList.remove('dragover');
      if (e.dataTransfer.files.length) {
        selectedGalleryImgs = Array.from(e.dataTransfer.files);
        inputGallery.files = e.dataTransfer.files;
        labelGallery.innerHTML = `<span style="color:#22c55e;font-weight:700;">✓ ${selectedGalleryImgs.length} foto(s) adicional(is) selecionada(s)</span>`;
      }
    });
  }
}

// 6. Formulário de Upload
function setupUploadForm() {
  const form = document.getElementById('uploadForm');
  const alertBox = document.getElementById('uploadAlert');
  const btn = document.getElementById('btnUploadSubmit');

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    alertBox.style.display = 'none';

    if (!selectedFiles3D || selectedFiles3D.length === 0) {
      alert('Por favor, selecione pelo menos um arquivo 3D (.STL, .3MF, etc.).');
      return;
    }
    if (!selectedFileImg) {
      alert('Por favor, selecione a foto de capa principal do modelo.');
      return;
    }

    const title = document.getElementById('modelTitle').value.trim();
    const categoryId = document.getElementById('modelCategory').value;
    const price = parseFloat(document.getElementById('modelPrice').value || '0');
    const showPrice = document.getElementById('modelShowPrice').checked;
    const isFeatured = document.getElementById('modelFeatured').checked;
    const orderCount = parseInt(document.getElementById('modelOrderCount').value || '15');
    const desc = document.getElementById('modelDesc').value.trim();

    btn.disabled = true;
    btn.innerHTML = `<span>Gravando arquivos e publicando...</span>`;

    const formData = new FormData();
    formData.append('title', title);
    formData.append('category_id', categoryId);
    formData.append('price', price);
    formData.append('show_price', showPrice);
    formData.append('is_featured', isFeatured);
    formData.append('order_count', orderCount);
    formData.append('description', desc);

    // Adiciona todos os arquivos 3D
    selectedFiles3D.forEach(f => {
      formData.append('files_3d', f);
    });

    // Foto de Capa (Primária)
    formData.append('image', selectedFileImg);

    // Fotos Adicionais da Galeria
    selectedGalleryImgs.forEach(f => {
      formData.append('gallery_images', f);
    });

    try {
      const res = await fetch('/api/admin/models', {
        method: 'POST',
        body: formData
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Erro no upload');

      // Sucesso
      const partsMsg = data.parts_count > 1 ? ` (${data.parts_count} peças compactadas)` : '';
      const galMsg = data.gallery_count > 1 ? ` com ${data.gallery_count} fotos na galeria` : '';
      alertBox.textContent = `Modelo "${title}" cadastrado com sucesso!${partsMsg}${galMsg}`;
      alertBox.style.background = 'rgba(34, 197, 94, 0.15)';
      alertBox.style.border = '1px solid rgba(34, 197, 94, 0.3)';
      alertBox.style.color = '#86efac';
      alertBox.style.display = 'block';

      form.reset();
      selectedFiles3D = [];
      selectedFileImg = null;
      selectedGalleryImgs = [];
      document.getElementById('label3D').textContent = 'Arraste os arquivos 3D ou .ZIP aqui ou clique para selecionar';
      document.getElementById('labelImg').textContent = 'Arraste a foto de capa aqui ou clique para selecionar';
      if (document.getElementById('labelGallery')) {
        document.getElementById('labelGallery').textContent = 'Arraste fotos adicionais para a galeria ou clique para selecionar';
      }

      // Volta para a aba de modelos após 1.2s
      setTimeout(() => {
        document.querySelector('.admin-tab[data-tab="models"]').click();
      }, 1200);

    } catch (err) {
      alertBox.textContent = `Erro ao salvar: ${err.message}`;
      alertBox.style.background = 'rgba(239, 35, 60, 0.15)';
      alertBox.style.border = '1px solid rgba(239, 35, 60, 0.3)';
      alertBox.style.color = '#fca5a5';
      alertBox.style.display = 'block';
    } finally {
      btn.disabled = false;
      btn.innerHTML = `<i data-lucide="upload-cloud" style="width: 18px; height: 18px;"></i><span>Salvar e Publicar Modelo</span>`;
      if (window.lucide) lucide.createIcons();
    }
  });
}

// 7. Carrega Pedidos Recebidos
async function loadAdminOrders() {
  const tbody = document.getElementById('ordersTableBody');
  if (!tbody) return;

  tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding: 24px; color: #a1a1aa;">Carregando histórico de pedidos...</td></tr>`;

  try {
    const res = await fetch('/api/admin/orders');
    if (res.status === 401) {
      window.location.href = '/loginAdmin';
      return;
    }
    const orders = await res.json();

    if (orders.length === 0) {
      tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding: 32px; color: #71717a;">Nenhum pedido recebido ainda.</td></tr>`;
      return;
    }

    tbody.innerHTML = orders.map(o => {
      const cleanPhone = o.customer_phone.replace(/\D/g, '');
      const waUrl = `https://wa.me/55${cleanPhone}?text=${encodeURIComponent(`Olá ${o.customer_name}! Recebi seu pedido do modelo 3D "${o.model_title}". Vamos combinar os detalhes da impressão?`)}`;

      return `
        <tr>
          <td><small style="color: #71717a;">${o.created_at}</small></td>
          <td><strong>${escapeHtml(o.customer_name)}</strong></td>
          <td>${escapeHtml(o.customer_phone)}</td>
          <td>${escapeHtml(o.model_title)}</td>
          <td>${o.show_price && o.price_registered ? 'R$ ' + o.price_registered.toFixed(2) : 'Sob Consulta (R$ ' + o.price_registered.toFixed(2) + ')'}</td>
          <td><small style="color: #a1a1aa;">${escapeHtml(o.customer_notes || 'Nenhuma')}</small></td>
          <td style="text-align: right;">
            <a href="${waUrl}" target="_blank" class="btn-action" style="background: rgba(37, 211, 102, 0.15); color: #4ade80; border-color: rgba(37, 211, 102, 0.3);">
              <i data-lucide="message-circle" style="width:14px;height:14px;"></i>
              <span>Conversar</span>
            </a>
          </td>
        </tr>
      `;
    }).join('');

    if (window.lucide) lucide.createIcons();
  } catch (err) {
    console.error('Erro ao carregar pedidos:', err);
  }
}

// 8. Logout
function setupLogout() {
  const btn = document.getElementById('btnLogout');
  if (btn) {
    btn.addEventListener('click', async () => {
      await fetch('/api/auth/logout', { method: 'POST' });
      window.location.href = '/loginAdmin';
    });
  }
}

function escapeHtml(str) {
  if (!str) return '';
  return str.replace(/[&<>"']/g, m => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  })[m]);
}

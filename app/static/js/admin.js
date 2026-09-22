// Script Administrativo - 3A Field Service
let adminCategories = [];
let selectedFile3D = null;
let selectedFileImg = null;

document.addEventListener('DOMContentLoaded', () => {
  setupTabs();
  setupDropzones();
  loadAdminCategories();
  loadAdminModels();
  setupUploadForm();
  setupLogout();
});

// 1. Gerenciamento de Abas
function setupTabs() {
  document.querySelectorAll('.admin-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.admin-tab').forEach(t => t.classList.remove('active'));
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

// 2. Carrega Categorias para o Select de Upload
async function loadAdminCategories() {
  try {
    const res = await fetch('/api/public/categories');
    adminCategories = await res.json();
    const select = document.getElementById('modelCategory');
    if (select) {
      select.innerHTML = adminCategories.map(c => `<option value="${c.id}">${c.name}</option>`).join('');
    }
  } catch (err) {
    console.error('Erro ao carregar categorias:', err);
  }
}

// 3. Carrega Modelos Cadastrados
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

      return `
        <tr>
          <td style="width: 60px;">
            <img src="/api/public/images/${m.image_filename}" style="width: 48px; height: 48px; object-fit: cover; border-radius: 6px;" alt="Foto">
          </td>
          <td>
            <strong>${escapeHtml(m.title)}</strong><br>
            <small style="color: #71717a;">${escapeHtml(m.file_3d_filename)}</small>
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
    if (!res.ok) throw new Error('Falha ao excluir modelo.');
    loadAdminModels();
  } catch (err) {
    alert('Erro: ' + err.message);
  }
}

// 5. Configuração dos Dropzones para Upload
function setupDropzones() {
  const drop3D = document.getElementById('dropzone3D');
  const input3D = document.getElementById('inputFile3D');
  const label3D = document.getElementById('label3D');

  const dropImg = document.getElementById('dropzoneImg');
  const inputImg = document.getElementById('inputFileImg');
  const labelImg = document.getElementById('labelImg');

  // Dropzone 3D
  drop3D.addEventListener('click', () => input3D.click());
  input3D.addEventListener('change', () => {
    if (input3D.files.length) {
      selectedFile3D = input3D.files[0];
      label3D.innerHTML = `<span style="color:#22c55e;">✓ ${selectedFile3D.name}</span> (${(selectedFile3D.size/1024/1024).toFixed(2)} MB)`;
    }
  });

  // Dropzone Imagem
  dropImg.addEventListener('click', () => inputImg.click());
  inputImg.addEventListener('change', () => {
    if (inputImg.files.length) {
      selectedFileImg = inputImg.files[0];
      labelImg.innerHTML = `<span style="color:#22c55e;">✓ ${selectedFileImg.name}</span> (${(selectedFileImg.size/1024).toFixed(1)} KB)`;
    }
  });

  // Drag over effects
  [drop3D, dropImg].forEach(zone => {
    zone.addEventListener('dragover', (e) => { e.preventDefault(); zone.classList.add('dragover'); });
    zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
  });

  drop3D.addEventListener('drop', (e) => {
    e.preventDefault();
    drop3D.classList.remove('dragover');
    if (e.dataTransfer.files.length) {
      selectedFile3D = e.dataTransfer.files[0];
      input3D.files = e.dataTransfer.files;
      label3D.innerHTML = `<span style="color:#22c55e;">✓ ${selectedFile3D.name}</span> (${(selectedFile3D.size/1024/1024).toFixed(2)} MB)`;
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
}

// 6. Formulário de Upload
function setupUploadForm() {
  const form = document.getElementById('uploadForm');
  const alertBox = document.getElementById('uploadAlert');
  const btn = document.getElementById('btnUploadSubmit');

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    alertBox.style.display = 'none';

    if (!selectedFile3D) {
      alert('Por favor, selecione um arquivo 3D (.STL, .3MF, etc.).');
      return;
    }
    if (!selectedFileImg) {
      alert('Por favor, selecione a foto de capa do modelo.');
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
    formData.append('file_3d', selectedFile3D);
    formData.append('image', selectedFileImg);

    try {
      const res = await fetch('/api/admin/models', {
        method: 'POST',
        body: formData
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Erro no upload');

      // Sucesso
      alertBox.textContent = `Modelo "${title}" cadastrado com sucesso!`;
      alertBox.style.background = 'rgba(34, 197, 94, 0.15)';
      alertBox.style.border = '1px solid rgba(34, 197, 94, 0.3)';
      alertBox.style.color = '#86efac';
      alertBox.style.display = 'block';

      form.reset();
      selectedFile3D = null;
      selectedFileImg = null;
      document.getElementById('label3D').textContent = 'Arraste o arquivo 3D aqui ou clique para selecionar';
      document.getElementById('labelImg').textContent = 'Arraste a foto aqui ou clique para selecionar';

      // Volta para a aba de modelos após 1.5s
      setTimeout(() => {
        document.querySelector('.admin-tab[data-tab="models"]').click();
      }, 1200);

    } catch (err) {
      alertBox.textContent = 'Erro: ' + err.message;
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

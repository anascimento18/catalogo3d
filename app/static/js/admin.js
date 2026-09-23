// Script do Painel Administrativo 3D
let adminCategories = [];
let allAdminModels = [];
let selectedFiles3D = [];
let selectedFileImg = null;
let selectedGalleryImgs = [];

document.addEventListener('DOMContentLoaded', () => {
  setupTabs();
  setupDropzones();
  loadAdminCategories();
  loadAdminModels();
  setupUploadForm();
  setupEditForm();
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
    allAdminModels = models;

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

      const linkInfo = m.external_url 
        ? `<span style="color:#c084fc;font-weight:600;">🔗 Link do Site</span> • ` 
        : '';

      const fileOrUrlText = m.file_3d_filename 
        ? escapeHtml(m.file_3d_filename) 
        : (m.external_url ? `<a href="${escapeHtml(m.external_url)}" target="_blank" style="color:#c084fc;text-decoration:underline;">${escapeHtml(m.external_url.substring(0, 45))}...</a>` : 'Sem arquivo');

      const externalBtn = m.external_url ? `
        <a href="${escapeHtml(m.external_url)}" target="_blank" rel="noopener noreferrer" class="btn-action" style="background: rgba(168, 85, 247, 0.15); color: #c084fc; border-color: rgba(168, 85, 247, 0.35);" title="Abrir site/personalizador original em nova aba">
          <i data-lucide="external-link" style="width:14px;height:14px;"></i>
          <span>Abrir Site</span>
        </a>
      ` : '';

      const downloadBtn = m.file_3d_filename ? `
        <a href="/api/admin/models/${m.id}/download" class="btn-action download" title="Baixar arquivo 3D original">
          <i data-lucide="download" style="width:14px;height:14px;"></i>
          <span>Download 3D</span>
        </a>
      ` : '';

      return `
        <tr>
          <td style="width: 60px;">
            <img src="/api/public/images/${m.image_filename}" style="width: 48px; height: 48px; object-fit: cover; border-radius: 6px;" alt="Foto">
          </td>
          <td>
            <strong>${escapeHtml(m.title)}</strong><br>
            <small style="color: #71717a;">${partsInfo}${photosInfo}${linkInfo}${fileOrUrlText}</small>
          </td>
          <td>${escapeHtml(m.category_name)}</td>
          <td><span class="badge-tag">${m.file_format}</span></td>
          <td>${priceText}</td>
          <td>${showPriceBadge}</td>
          <td>🔥 ${m.order_count || 0}</td>
          <td style="text-align: right; white-space: nowrap;">
            <button class="btn-action edit" onclick="openEditModal(${m.id})" title="Editar dados e link" style="border-color: rgba(56, 189, 248, 0.4); color: #38bdf8;">
              <i data-lucide="edit-3" style="width:14px;height:14px;"></i>
              <span>Editar</span>
            </button>
            ${externalBtn}
            ${downloadBtn}
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

// 4. Download, Edição e Exclusão de Modelos
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

// Abre Modal de Edição com dados preenchidos
window.openEditModal = function(id) {
  const model = allAdminModels.find(m => m.id === id);
  if (!model) return;

  document.getElementById('editModelId').value = model.id;
  document.getElementById('editModelTitle').value = model.title || '';
  document.getElementById('editModelPrice').value = model.price !== undefined ? model.price : '0.00';
  document.getElementById('editModelShowPrice').checked = !!model.show_price;
  document.getElementById('editModelFeatured').checked = !!model.is_featured;
  document.getElementById('editModelOrderCount').value = model.order_count || 0;
  document.getElementById('editModelDesc').value = model.description || '';
  const urlInput = document.getElementById('editModelExternalUrl');
  if (urlInput) urlInput.value = model.external_url || '';

  // Popula categorias no select de edição
  const catSelect = document.getElementById('editModelCategory');
  if (catSelect && adminCategories.length) {
    catSelect.innerHTML = adminCategories.map(c => `
      <option value="${c.id}" ${c.id === model.category_id ? 'selected' : ''}>${c.name}</option>
    `).join('');
  }

  const alertBox = document.getElementById('editAlert');
  if (alertBox) alertBox.style.display = 'none';

  const modal = document.getElementById('editModal');
  if (modal) {
    modal.style.display = 'flex';
    modal.classList.add('active');
    document.body.style.overflow = 'hidden';
  }
  if (window.lucide) lucide.createIcons();
};

window.closeEditModal = function() {
  const modal = document.getElementById('editModal');
  if (modal) {
    modal.style.display = 'none';
    modal.classList.remove('active');
    document.body.style.overflow = '';
  }
};

function setupEditForm() {
  const form = document.getElementById('editForm');
  const alertBox = document.getElementById('editAlert');
  const btn = document.getElementById('btnSaveEdit');
  if (!form) return;

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const id = document.getElementById('editModelId').value;
    const title = document.getElementById('editModelTitle').value.trim();
    const categoryId = parseInt(document.getElementById('editModelCategory').value);
    const price = parseFloat(document.getElementById('editModelPrice').value || '0');
    const showPrice = document.getElementById('editModelShowPrice').checked;
    const isFeatured = document.getElementById('editModelFeatured').checked;
    const orderCount = parseInt(document.getElementById('editModelOrderCount').value || '0');
    const desc = document.getElementById('editModelDesc').value.trim();
    const externalUrl = (document.getElementById('editModelExternalUrl')?.value || '').trim();

    btn.disabled = true;
    btn.innerHTML = `<span>Salvando alterações...</span>`;

    try {
      const res = await fetch(`/api/admin/models/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title,
          category_id: categoryId,
          price,
          show_price: showPrice,
          is_featured: isFeatured,
          order_count: orderCount,
          description: desc,
          external_url: externalUrl
        })
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Erro ao salvar');

      alertBox.textContent = 'Modelo atualizado com sucesso!';
      alertBox.style.background = 'rgba(34, 197, 94, 0.15)';
      alertBox.style.border = '1px solid rgba(34, 197, 94, 0.3)';
      alertBox.style.color = '#86efac';
      alertBox.style.display = 'block';

      setTimeout(() => {
        closeEditModal();
        loadAdminModels();
      }, 700);

    } catch (err) {
      alertBox.textContent = `Erro: ${err.message}`;
      alertBox.style.background = 'rgba(239, 35, 60, 0.15)';
      alertBox.style.border = '1px solid rgba(239, 35, 60, 0.3)';
      alertBox.style.color = '#fca5a5';
      alertBox.style.display = 'block';
    } finally {
      btn.disabled = false;
      btn.innerHTML = `<i data-lucide="check" style="width: 16px; height: 16px;"></i><span>Salvar Alterações</span>`;
      if (window.lucide) lucide.createIcons();
    }
  });

  // Fechar ao clicar fora ou pressionar ESC
  const modal = document.getElementById('editModal');
  if (modal) {
    modal.addEventListener('click', (e) => {
      if (e.target === modal) closeEditModal();
    });
  }
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && modal && modal.classList.contains('active')) {
      closeEditModal();
    }
  });
}

// Controle de Alternância da Origem 3D (Arquivo Local vs Link do Personalizador)
window.switch3DSource = function(mode) {
  const containerFile = document.getElementById('containerFile3D');
  const containerLink = document.getElementById('containerLink3D');
  const badge = document.getElementById('sourceBadge');
  const btnFile = document.getElementById('btnSourceFile');
  const btnLink = document.getElementById('btnSourceLink');
  const btnBoth = document.getElementById('btnSourceBoth');

  const allBtns = [btnFile, btnLink, btnBoth].filter(Boolean);
  allBtns.forEach(b => {
    b.style.background = 'transparent';
    b.style.color = '#a1a1aa';
  });

  if (mode === 'file') {
    if (containerFile) containerFile.style.display = 'block';
    if (containerLink) containerLink.style.display = 'none';
    if (badge) {
      badge.textContent = 'Arquivo 3D Local';
      badge.style.color = '#38bdf8';
      badge.style.background = 'rgba(56, 189, 248, 0.15)';
    }
    if (btnFile) {
      btnFile.style.background = '#2563eb';
      btnFile.style.color = '#fff';
    }
  } else if (mode === 'link') {
    if (containerFile) containerFile.style.display = 'none';
    if (containerLink) containerLink.style.display = 'block';
    if (badge) {
      badge.textContent = 'Link do Site / Personalizador';
      badge.style.color = '#c084fc';
      badge.style.background = 'rgba(168, 85, 247, 0.15)';
    }
    if (btnLink) {
      btnLink.style.background = '#9333ea';
      btnLink.style.color = '#fff';
    }
  } else if (mode === 'both') {
    if (containerFile) containerFile.style.display = 'block';
    if (containerLink) containerLink.style.display = 'block';
    if (badge) {
      badge.textContent = 'Arquivo 3D + Link';
      badge.style.color = '#34d399';
      badge.style.background = 'rgba(52, 211, 153, 0.15)';
    }
    if (btnBoth) {
      btnBoth.style.background = '#059669';
      btnBoth.style.color = '#fff';
    }
  }
  if (window.lucide) lucide.createIcons();
};

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

  // Input 3D
  if (input3D) {
    input3D.addEventListener('change', () => {
      if (input3D.files && input3D.files.length) {
        handle3DFiles(input3D.files);
      }
    });
  }

  // Input Imagem Capa
  if (inputImg) {
    inputImg.addEventListener('change', () => {
      if (inputImg.files && inputImg.files.length) {
        handleCoverImage(inputImg.files[0]);
      }
    });
  }

  // Input Fotos da Galeria (Múltiplas)
  if (inputGallery) {
    inputGallery.addEventListener('change', () => {
      if (inputGallery.files && inputGallery.files.length) {
        addGalleryFiles(Array.from(inputGallery.files));
        inputGallery.value = ''; // Permite selecionar mais fotos ou re-selecionar
      }
    });
  }

  // Drag and Drop (Efeitos visuais)
  const allZones = [drop3D, dropImg, dropGallery].filter(Boolean);

  allZones.forEach(zone => {
    zone.addEventListener('dragover', (e) => {
      e.preventDefault();
      e.stopPropagation();
      zone.classList.add('dragover');
    });
    zone.addEventListener('dragleave', (e) => {
      e.preventDefault();
      e.stopPropagation();
      zone.classList.remove('dragover');
    });
  });

  // Drop Arquivos 3D
  if (drop3D && input3D) {
    drop3D.addEventListener('drop', (e) => {
      e.preventDefault();
      e.stopPropagation();
      drop3D.classList.remove('dragover');
      if (e.dataTransfer && e.dataTransfer.files.length) {
        handle3DFiles(e.dataTransfer.files);
      }
    });
  }

  // Drop Foto Capa
  if (dropImg && inputImg) {
    dropImg.addEventListener('drop', (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropImg.classList.remove('dragover');
      if (e.dataTransfer && e.dataTransfer.files.length) {
        handleCoverImage(e.dataTransfer.files[0]);
      }
    });
  }

  // Drop Fotos Galeria
  if (dropGallery && inputGallery) {
    dropGallery.addEventListener('drop', (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropGallery.classList.remove('dragover');
      if (e.dataTransfer && e.dataTransfer.files.length) {
        addGalleryFiles(Array.from(e.dataTransfer.files));
      }
    });
  }
}

// Manipulador de Arquivos 3D
function handle3DFiles(files) {
  if (!files || files.length === 0) return;
  selectedFiles3D = Array.from(files);
  const label3D = document.getElementById('label3D');
  if (!label3D) return;
  if (selectedFiles3D.length === 1) {
    label3D.innerHTML = `<span style="color:#22c55e;font-weight:700;">✓ ${selectedFiles3D[0].name}</span> (${(selectedFiles3D[0].size/1024/1024).toFixed(2)} MB)`;
  } else {
    const totalSize = (selectedFiles3D.reduce((acc, f) => acc + f.size, 0)/1024/1024).toFixed(2);
    label3D.innerHTML = `<span style="color:#38bdf8;font-weight:700;">✓ ${selectedFiles3D.length} peças/arquivos selecionados</span> (Total: ${totalSize} MB)`;
  }
}

// Manipulador de Foto de Capa
function handleCoverImage(file) {
  if (!file) return;
  selectedFileImg = file;
  const labelImg = document.getElementById('labelImg');
  if (labelImg) {
    labelImg.innerHTML = `<span style="color:#22c55e;font-weight:700;">✓ ${file.name}</span> (${(file.size/1024).toFixed(1)} KB)`;
  }

  const container = document.getElementById('coverPreviewContainer');
  const imgEl = document.getElementById('coverPreviewImg');
  const nameEl = document.getElementById('coverPreviewName');
  const sizeEl = document.getElementById('coverPreviewSize');

  if (container && imgEl) {
    imgEl.src = URL.createObjectURL(file);
    if (nameEl) nameEl.textContent = file.name;
    if (sizeEl) sizeEl.textContent = `${(file.size/1024).toFixed(1)} KB`;
    container.style.display = 'flex';
  }
}

// Adiciona Fotos na Galeria (acumulativo)
function addGalleryFiles(files) {
  for (const f of files) {
    if (f.type.startsWith('image/') || /\.(jpe?g|png|webp|gif|svg)$/i.test(f.name)) {
      if (!selectedGalleryImgs.some(existing => existing.name === f.name && existing.size === f.size)) {
        selectedGalleryImgs.push(f);
      }
    }
  }
  renderGalleryPreviews();
}

// Renderiza miniaturas das fotos adicionais na tela
function renderGalleryPreviews() {
  const labelGallery = document.getElementById('labelGallery');
  const previewList = document.getElementById('galleryPreviewList');
  if (labelGallery) {
    if (selectedGalleryImgs.length > 0) {
      labelGallery.innerHTML = `<span style="color:#22c55e;font-weight:700;">✓ ${selectedGalleryImgs.length} foto(s) na galeria</span> <span style="color:#a1a1aa;font-size:12px;">(Clique para adicionar mais)</span>`;
    } else {
      labelGallery.textContent = 'Arraste fotos adicionais para a galeria ou clique para selecionar';
    }
  }
  if (previewList) {
    previewList.innerHTML = selectedGalleryImgs.map((file, i) => {
      const url = URL.createObjectURL(file);
      return `
        <div style="position: relative; width: 66px; height: 66px; border-radius: 8px; overflow: hidden; border: 2px solid #ef233c; box-shadow: 0 4px 10px rgba(0,0,0,0.6); background: #000;">
          <img src="${url}" style="width: 100%; height: 100%; object-fit: cover;" alt="Foto ${i+1}">
          <button type="button" onclick="event.preventDefault(); event.stopPropagation(); removeGalleryImg(${i})" title="Remover esta foto" style="position: absolute; top: 2px; right: 2px; background: rgba(0,0,0,0.85); color: #ef233c; border: 1px solid #ef233c; border-radius: 50%; width: 19px; height: 19px; font-size: 11px; font-weight: bold; cursor: pointer; display: flex; align-items: center; justify-content: center; line-height: 1;">✕</button>
          <span style="position: absolute; bottom: 2px; left: 2px; background: rgba(0,0,0,0.75); font-size: 9px; padding: 1px 4px; border-radius: 3px; color: #fff;">#${i+1}</span>
        </div>
      `;
    }).join('');
  }
}

window.removeGalleryImg = function(index) {
  selectedGalleryImgs.splice(index, 1);
  renderGalleryPreviews();
};

// 6. Formulário de Upload
function setupUploadForm() {
  const form = document.getElementById('uploadForm');
  const alertBox = document.getElementById('uploadAlert');
  const btn = document.getElementById('btnUploadSubmit');

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    alertBox.style.display = 'none';

    const externalUrl = (document.getElementById('modelExternalUrl')?.value || '').trim();
    const hasFiles = selectedFiles3D && selectedFiles3D.length > 0;

    if (!hasFiles && !externalUrl) {
      alert('Por favor, selecione pelo menos um arquivo 3D (.STL, .3MF, .ZIP) OU insira o link do site/personalizador.');
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
    formData.append('external_url', externalUrl);

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
      const linkMsg = externalUrl ? ' com link do site salvo' : '';
      alertBox.textContent = `Modelo "${title}" cadastrado com sucesso!${partsMsg}${galMsg}${linkMsg}`;
      alertBox.style.background = 'rgba(34, 197, 94, 0.15)';
      alertBox.style.border = '1px solid rgba(34, 197, 94, 0.3)';
      alertBox.style.color = '#86efac';
      alertBox.style.display = 'block';

      form.reset();
      selectedFiles3D = [];
      selectedFileImg = null;
      selectedGalleryImgs = [];
      renderGalleryPreviews();
      const coverPreview = document.getElementById('coverPreviewContainer');
      if (coverPreview) coverPreview.style.display = 'none';
      document.getElementById('label3D').textContent = 'Arraste os arquivos 3D ou .ZIP aqui ou clique para selecionar';
      document.getElementById('labelImg').textContent = 'Arraste a foto de capa aqui ou clique para selecionar';
      if (document.getElementById('modelExternalUrl')) {
        document.getElementById('modelExternalUrl').value = '';
      }
      switch3DSource('file');
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

      const siteBtn = o.external_url ? `
        <a href="${escapeHtml(o.external_url)}" target="_blank" rel="noopener noreferrer" class="btn-action" style="background: rgba(168, 85, 247, 0.15); color: #c084fc; border-color: rgba(168, 85, 247, 0.35);" title="Abrir site/personalizador deste modelo em nova aba">
          <i data-lucide="external-link" style="width:14px;height:14px;"></i>
          <span>Abrir Site</span>
        </a>
      ` : '';

      return `
        <tr>
          <td><small style="color: #71717a;">${o.created_at}</small></td>
          <td><strong>${escapeHtml(o.customer_name)}</strong></td>
          <td>${escapeHtml(o.customer_phone)}</td>
          <td>${escapeHtml(o.model_title)}</td>
          <td>${o.show_price && o.price_registered ? 'R$ ' + o.price_registered.toFixed(2) : 'Sob Consulta (R$ ' + o.price_registered.toFixed(2) + ')'}</td>
          <td><small style="color: #a1a1aa;">${escapeHtml(o.customer_notes || 'Nenhuma')}</small></td>
          <td style="text-align: right; white-space: nowrap;">
            ${siteBtn}
            <a href="${waUrl}" target="_blank" class="btn-action" style="background: rgba(37, 211, 102, 0.15); color: #4ade80; border-color: rgba(37, 211, 102, 0.3);" title="Conversar no WhatsApp">
              <i data-lucide="message-circle" style="width:14px;height:14px;"></i>
              <span>Conversar</span>
            </a>
            <button class="btn-action delete" onclick="deleteOrder(${o.id})" title="Excluir este orçamento">
              <i data-lucide="trash-2" style="width:14px;height:14px;"></i>
              <span>Excluir</span>
            </button>
          </td>
        </tr>
      `;
    }).join('');

    if (window.lucide) lucide.createIcons();
  } catch (err) {
    console.error('Erro ao carregar pedidos:', err);
  }
}

// Exclui um pedido individual
window.deleteOrder = async function(id) {
  if (!confirm('Deseja excluir este orçamento do histórico?')) return;
  try {
    const res = await fetch(`/api/admin/orders/${id}`, { method: 'DELETE' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Erro ao excluir orçamento');
    loadAdminOrders();
  } catch (err) {
    alert(err.message || 'Erro ao excluir');
  }
};

// Limpa todo o histórico de pedidos
window.clearAllOrders = async function() {
  if (!confirm('ATENÇÃO: Deseja apagar TODO o histórico de orçamentos e pedidos de teste?\nEsta ação removerá todos os registros da tabela.')) {
    return;
  }
  try {
    const res = await fetch('/api/admin/orders', { method: 'DELETE' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Erro ao limpar histórico');
    alert('Histórico de orçamentos limpo com sucesso!');
    loadAdminOrders();
  } catch (err) {
    alert(err.message || 'Erro ao limpar histórico');
  }
};

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

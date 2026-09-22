// Script da Vitrine Pública - Catálogo & Impressão 3D
// Segurança: Este script não possui chaves de API, senhas ou URLs de arquivos 3D brutos.

let allCategories = [];
let allModels = [];
let activeCategory = 'all';
let searchTimeout = null;

document.addEventListener('DOMContentLoaded', () => {
  loadCategories();
  loadCatalog();
  setupSearch();
  setupPhoneMask();
  setupModalEvents();
});

// 1. Carrega Categorias
async function loadCategories() {
  try {
    const res = await fetch('/api/public/categories');
    if (!res.ok) return;
    allCategories = await res.json();
    renderCategories();
  } catch (err) {
    console.error('Erro ao carregar categorias:', err);
  }
}

function renderCategories() {
  const container = document.getElementById('categoriesContainer');
  if (!container) return;

  let html = `<div class="category-pill ${activeCategory === 'all' ? 'active' : ''}" data-id="all">Todos os Modelos</div>`;
  allCategories.forEach(cat => {
    html += `<div class="category-pill ${activeCategory == cat.id ? 'active' : ''}" data-id="${cat.id}">${cat.name}</div>`;
  });
  container.innerHTML = html;

  // Eventos de clique nas pílulas de categoria
  container.querySelectorAll('.category-pill').forEach(pill => {
    pill.addEventListener('click', () => {
      container.querySelectorAll('.category-pill').forEach(p => p.classList.remove('active'));
      pill.classList.add('active');
      activeCategory = pill.dataset.id;
      loadCatalog();
    });
  });
}

// 2. Carrega Catálogo de Modelos
async function loadCatalog() {
  const grid = document.getElementById('modelsGrid');
  const countLabel = document.getElementById('modelCountLabel');
  const emptyState = document.getElementById('emptyState');
  const searchVal = document.getElementById('searchInput').value.trim();

  let url = `/api/public/catalog?`;
  if (activeCategory !== 'all') {
    url += `category_id=${activeCategory}&`;
  }
  if (searchVal) {
    url += `search=${encodeURIComponent(searchVal)}&`;
  }

  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error('Falha ao carregar modelos');
    allModels = await res.json();

    if (countLabel) {
      countLabel.textContent = `${allModels.length} modelo(s) encontrado(s)`;
    }

    if (allModels.length === 0) {
      grid.innerHTML = '';
      emptyState.style.display = 'block';
    } else {
      emptyState.style.display = 'none';
      renderModels(allModels);
    }
  } catch (err) {
    console.error('Erro:', err);
    if (countLabel) countLabel.textContent = 'Erro ao carregar modelos.';
  }
}

function renderModels(models) {
  const grid = document.getElementById('modelsGrid');
  if (!grid) return;

  grid.innerHTML = models.map(m => {
    const priceHtml = m.show_price && m.price
      ? `<div class="price-box"><span class="price-label">Valor</span><span class="price-value">R$ ${m.price.toFixed(2).replace('.', ',')}</span></div>`
      : `<div class="price-box"><span class="price-label">Orçamento</span><span class="price-value consult">Sob Consulta</span></div>`;

    const featuredBadge = m.is_featured 
      ? `<span class="badge-tag badge-featured">★ Mais Pedido</span>` 
      : '';

    const galleryCountBadge = m.gallery && m.gallery.length > 1
      ? `<span class="badge-tag" style="background: rgba(0,0,0,0.75);"><i data-lucide="camera" style="width:11px;height:11px;margin-right:3px;"></i>${m.gallery.length} fotos</span>`
      : '';

    return `
      <article class="model-card animate-fade-in" data-id="${m.id}">
        <div class="card-media" onclick="openOrderModal(${m.id})" style="cursor: pointer;" title="Clique para ver fotos e detalhes">
          <img src="${m.image_url}" alt="${escapeHtml(m.title)}" class="card-img" loading="lazy">
          <div class="badge-top-right" style="display: flex; gap: 4px; flex-direction: column; align-items: flex-end;">
            ${featuredBadge}
            ${galleryCountBadge}
          </div>
        </div>

        <div class="card-body">
          <span class="card-category">${escapeHtml(m.category_name || 'Geral')}</span>
          <h3 class="card-title" onclick="openOrderModal(${m.id})" style="cursor: pointer;" title="Clique para ver fotos e detalhes">${escapeHtml(m.title)}</h3>
          <p class="card-desc">${escapeHtml(m.description || 'Modelo sob demanda de alta precisão.')}</p>

          <div class="card-meta">
            ${priceHtml}
            <div class="order-counter" title="Contador de pedidos já solicitados deste modelo">
              <span>🔥</span>
              <span>${m.order_count || 12} pedidos</span>
            </div>
          </div>

          <button class="btn-order" type="button" onclick="openOrderModal(${m.id})">
            <i data-lucide="eye" style="width:16px;height:16px;"></i>
            <span>Ver Detalhes & Pedir</span>
          </button>
        </div>
      </article>
    `;
  }).join('');

  if (window.lucide) {
    lucide.createIcons();
  }
}

// 3. Busca Instantânea com Debounce
function setupSearch() {
  const searchInput = document.getElementById('searchInput');
  if (!searchInput) return;

  searchInput.addEventListener('input', () => {
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => {
      loadCatalog();
    }, 250);
  });
}

// 4. Modal de Pedido
function openOrderModal(modelId) {
  const model = allModels.find(m => m.id === modelId);
  if (!model) return;

  document.getElementById('orderModelId').value = model.id;
  document.getElementById('modalModelName').textContent = model.title;
  document.getElementById('modalModelCategory').textContent = model.category_name || 'Geral';
  document.getElementById('modalImg').src = model.image_url;

  const priceEl = document.getElementById('modalModelPrice');
  if (model.show_price && model.price) {
    priceEl.textContent = `R$ ${model.price.toFixed(2).replace('.', ',')}`;
  } else {
    priceEl.textContent = 'Sob Consulta';
  }

  // Gerencia Galeria de Fotos no Modal
  const gallery = (model.gallery && model.gallery.length > 0) ? model.gallery : [model.image_url];
  const thumbsContainer = document.getElementById('modalThumbnails');
  
  if (gallery.length > 1) {
    thumbsContainer.style.display = 'flex';
    thumbsContainer.innerHTML = gallery.map((imgUrl, i) => `
      <div class="thumb-item ${i === 0 ? 'active' : ''}" data-url="${imgUrl}" title="Ver foto ${i+1}">
        <img src="${imgUrl}" alt="Miniatura ${i+1}">
      </div>
    `).join('');

    thumbsContainer.querySelectorAll('.thumb-item').forEach(thumb => {
      thumb.addEventListener('click', () => {
        thumbsContainer.querySelectorAll('.thumb-item').forEach(t => t.classList.remove('active'));
        thumb.classList.add('active');
        const modalImg = document.getElementById('modalImg');
        modalImg.style.opacity = '0.3';
        setTimeout(() => {
          modalImg.src = thumb.dataset.url;
          modalImg.style.opacity = '1';
        }, 120);
      });
    });
  } else {
    thumbsContainer.style.display = 'none';
    thumbsContainer.innerHTML = '';
  }

  // Descrição Completa no Modal
  const descEl = document.getElementById('modalModelDesc');
  if (descEl) {
    descEl.textContent = model.description || 'Modelo de alta precisão pronto para impressão sob demanda.';
  }

  // Reseta visualização do modal
  document.getElementById('modalFormContainer').style.display = 'block';
  document.getElementById('modalSuccessContainer').style.display = 'none';
  document.getElementById('orderForm').reset();
  document.getElementById('submitOrderBtn').disabled = false;
  document.getElementById('submitOrderBtn').innerHTML = `<i data-lucide="send" style="width: 18px; height: 18px;"></i><span>Pedir no WhatsApp</span>`;

  document.getElementById('orderModal').classList.add('active');
  document.body.style.overflow = 'hidden';
  if (window.lucide) lucide.createIcons();
}

function closeOrderModal() {
  document.getElementById('orderModal').classList.remove('active');
  document.body.style.overflow = '';
}

function setupModalEvents() {
  const closeBtn = document.getElementById('modalCloseBtn');
  const modal = document.getElementById('orderModal');
  const form = document.getElementById('orderForm');

  if (closeBtn) closeBtn.addEventListener('click', closeOrderModal);

  // Fecha ao clicar fora do modal
  if (modal) {
    modal.addEventListener('click', (e) => {
      if (e.target === modal) closeOrderModal();
    });
  }

  // Tecla ESC fecha o modal
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeOrderModal();
  });

  // Envio do formulário
  if (form) {
    form.addEventListener('submit', async (e) => {
      e.preventDefault();

      const modelId = parseInt(document.getElementById('orderModelId').value);
      const custName = document.getElementById('custName').value.trim();
      const custPhone = document.getElementById('custPhone').value.trim();
      const custNotes = document.getElementById('custNotes').value.trim();
      const btn = document.getElementById('submitOrderBtn');

      if (!modelId || !custName || !custPhone) {
        alert('Por favor, preencha seu nome e WhatsApp.');
        return;
      }

      btn.disabled = true;
      btn.innerHTML = `<span>Enviando para o WhatsApp...</span>`;

      try {
        const res = await fetch('/api/public/order', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            model_id: modelId,
            customer_name: custName,
            customer_phone: custPhone,
            customer_notes: custNotes
          })
        });

        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Erro ao enviar pedido');

        // Exibe estado de sucesso
        document.getElementById('modalFormContainer').style.display = 'none';
        const successContainer = document.getElementById('modalSuccessContainer');
        successContainer.style.display = 'block';

        if (data.wa_direct_link) {
          document.getElementById('directWaLink').href = data.wa_direct_link;
        }

        if (window.lucide) lucide.createIcons();

        // Atualiza a vitrine para refletir o novo contador de pedidos
        loadCatalog();

      } catch (err) {
        alert('Erro ao enviar pedido: ' + err.message);
        btn.disabled = false;
        btn.innerHTML = `<i data-lucide="send" style="width: 18px; height: 18px;"></i><span>Tentar Novamente</span>`;
        if (window.lucide) lucide.createIcons();
      }
    });
  }
}

// 5. Máscara de Telefone WhatsApp
function setupPhoneMask() {
  const phoneInput = document.getElementById('custPhone');
  if (!phoneInput) return;

  phoneInput.addEventListener('input', (e) => {
    let v = e.target.value.replace(/\D/g, '');
    if (v.length > 11) v = v.slice(0, 11);

    if (v.length > 10) {
      // Formato (XX) XXXXX-XXXX
      v = v.replace(/^(\d{2})(\d{5})(\d{4})$/, '($1) $2-$3');
    } else if (v.length > 6) {
      // Formato (XX) XXXX-XXXX
      v = v.replace(/^(\d{2})(\d{4})(\d{0,4})$/, '($1) $2-$3');
    } else if (v.length > 2) {
      v = v.replace(/^(\d{2})(\d{0,5})$/, '($1) $2');
    }
    e.target.value = v;
  });
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

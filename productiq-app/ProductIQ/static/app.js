(() => {
  'use strict';

  const MAX_BATCH = Number(document.body.dataset.maxBatch || 25);
  const state = {
    queue: [],
    importedRows: [],
    importedColumns: [],
    results: JSON.parse(localStorage.getItem('productiq-results-v2') || '[]'),
    captchaResolve: null,
    captchaReject: null,
    captchaImageUrl: '',
    resultSearch: '',
    resultStatus: ''
  };

  const $ = selector => document.querySelector(selector);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, character => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  })[character]);

  function toast(message) {
    const element = $('#toast');
    element.textContent = message;
    element.classList.remove('hidden');
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => element.classList.add('hidden'), 3200);
  }

  function saveResults() {
    localStorage.setItem('productiq-results-v2', JSON.stringify(state.results));
    renderResults();
  }

  async function enrichCatalog() {
    if (!state.results.length) return;
    try {
      const response = await fetch('/api/catalog/enrich', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ results: state.results })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Catalog analysis failed.');
      state.results = data.results || state.results;
      localStorage.setItem('productiq-results-v2', JSON.stringify(state.results));
      renderResults();
    } catch (error) {
      console.warn('Catalog enrichment skipped:', error);
    }
  }

  function kind(value) {
    if (/amazon\.|^https?:/i.test(value)) return 'Amazon URL';
    if (/^[A-Z0-9]{10}$/i.test(value)) return 'ASIN';
    return 'Product name';
  }

  function queueItem(value) {
    value = value.trim();
    if (kind(value) === 'Amazon URL') return { url: value, asin: '', name: '' };
    if (kind(value) === 'ASIN') return { asin: value.toUpperCase(), url: '', name: '' };
    return { name: value, asin: '', url: '' };
  }

  function label(item) {
    return item.asin || item.url || item.name || item.upc || item.model || item.sku || 'Unknown product';
  }

  function addItems(items) {
    for (const item of items) {
      if (state.queue.length >= MAX_BATCH) break;
      if (!state.queue.some(existing => label(existing) === label(item))) state.queue.push(item);
    }
    renderQueue();
  }

  function renderQueue() {
    const body = $('#queue-body');
    body.innerHTML = state.queue.map((item, index) => `
      <tr>
        <td>${esc(label(item))}</td>
        <td>${esc(item.asin ? 'ASIN' : item.url ? 'Amazon URL' : item.upc ? 'UPC/EAN' : item.model ? 'Model' : 'Product name')}</td>
        <td><button class="text-button remove" data-index="${index}" type="button">Remove</button></td>
      </tr>`).join('');
    $('#queue-empty').classList.toggle('hidden', state.queue.length > 0);
    $('#queue-wrap').classList.toggle('hidden', !state.queue.length);
    $('#queue-count').textContent = `${state.queue.length} product${state.queue.length === 1 ? '' : 's'}`;
    $('#run-research').disabled = !state.queue.length;
    document.querySelectorAll('.remove').forEach(button => {
      button.onclick = () => {
        state.queue.splice(Number(button.dataset.index), 1);
        renderQueue();
      };
    });
  }

  function guess(columns, patterns) {
    return columns.find(column => patterns.some(pattern => pattern.test(column))) || '';
  }

  function fillSelect(id, selected = '') {
    const select = $(id);
    select.innerHTML = '<option value="">Not mapped</option>' + state.importedColumns
      .map(column => `<option ${column === selected ? 'selected' : ''}>${esc(column)}</option>`)
      .join('');
  }

  $('#add-lines').onclick = () => {
    const lines = $('#product-input').value.split(/\n+/).map(value => value.trim()).filter(Boolean);
    addItems(lines.map(queueItem));
    $('#product-input').value = '';
  };

  $('#clear-queue').onclick = () => {
    state.queue = [];
    renderQueue();
  };

  function embeddedSampleProducts() {
    const element = document.getElementById('sample-products-data');
    if (!element) return [];
    try {
      const items = JSON.parse(element.textContent || '[]');
      return Array.isArray(items) ? items : [];
    } catch (_) {
      return [];
    }
  }

  async function loadSampleProducts(trigger) {
    const button = trigger;
    const originalText = button?.textContent || '';
    if (button) { button.disabled = true; button.textContent = 'Loading…'; }
    try {
      let items = embeddedSampleProducts();
      if (!items.length) {
        const sampleUrl = document.body.dataset.sampleUrl || '/api/sample';
        const response = await fetch(sampleUrl, { cache: 'no-store' });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Could not load the sample data.');
        items = data.items || [];
      }
      if (!items.length) throw new Error('The included sample data is empty.');
      const before = state.queue.length;
      addItems(items);
      const added = state.queue.length - before;
      const skipped = items.length - added;
      toast(added
        ? `${added} sample product${added === 1 ? '' : 's'} added to the queue${skipped ? ` (${skipped} already queued or over the batch limit)` : ''}.`
        : 'The sample products are already in the queue.');
      $('#research').scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (error) {
      toast(error.message);
    } finally {
      if (button) { button.disabled = false; button.textContent = originalText; }
    }
  }

  $('#load-sample').onclick = event => loadSampleProducts(event.currentTarget);
  $('#hero-load-sample').onclick = event => loadSampleProducts(event.currentTarget);

  $('#file-input').onchange = async event => {
    const file = event.target.files[0];
    if (!file) return;
    $('#file-label').textContent = file.name;
    const form = new FormData();
    form.append('file', file);
    $('#upload-message').textContent = 'Reading spreadsheet…';
    $('#upload-message').classList.remove('hidden');
    try {
      const response = await fetch('/api/import', { method: 'POST', body: form });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error);
      state.importedRows = data.rows;
      state.importedColumns = data.columns;
      fillSelect('#map-asin', guess(data.columns, [/^asin$/i, /amazon.*id/i]));
      fillSelect('#map-url', guess(data.columns, [/url/i, /link/i]));
      fillSelect('#map-name', guess(data.columns, [/product.*name/i, /title/i, /^name$/i]));
      fillSelect('#map-sku', guess(data.columns, [/^sku$/i, /item.*sku/i]));
      fillSelect('#map-upc', guess(data.columns, [/^upc$/i, /^ean$/i, /gtin/i]));
      fillSelect('#map-model', guess(data.columns, [/model/i, /mpn/i, /part.*number/i]));
      fillSelect('#map-brand', guess(data.columns, [/brand/i, /manufacturer/i]));
      fillSelect('#map-cost', guess(data.columns, [/cost/i, /purchase.*price/i, /price.*paid/i]));
      fillSelect('#map-quantity', guess(data.columns, [/quantity/i, /^qty$/i, /stock/i]));
      $('#mapping').classList.remove('hidden');
      $('#upload-message').textContent = `Loaded ${data.count} rows. Confirm the column mapping.`;
    } catch (error) {
      $('#upload-message').textContent = error.message;
    }
  };

  $('#add-upload').onclick = () => {
    const asinColumn = $('#map-asin').value;
    const urlColumn = $('#map-url').value;
    const nameColumn = $('#map-name').value;
    const skuColumn = $('#map-sku').value, upcColumn = $('#map-upc').value, modelColumn = $('#map-model').value;
    const brandColumn = $('#map-brand').value, costColumn = $('#map-cost').value, quantityColumn = $('#map-quantity').value;
    if (!asinColumn && !urlColumn && !nameColumn && !upcColumn && !modelColumn) return toast('Map at least one product identifier or name column.');
    const items = state.importedRows.map(row => ({
      asin: asinColumn ? String(row[asinColumn] || '').trim() : '',
      url: urlColumn ? String(row[urlColumn] || '').trim() : '',
      name: nameColumn ? String(row[nameColumn] || '').trim() : '',
      sku: skuColumn ? String(row[skuColumn] || '').trim() : '', upc: upcColumn ? String(row[upcColumn] || '').trim() : '',
      model: modelColumn ? String(row[modelColumn] || '').trim() : '', brand: brandColumn ? String(row[brandColumn] || '').trim() : '',
      cost: costColumn ? String(row[costColumn] || '').trim() : '', quantity: quantityColumn ? String(row[quantityColumn] || '').trim() : ''
    })).filter(item => item.asin || item.url || item.name || item.upc || item.model);
    addItems(items);
    toast(`${Math.min(items.length, MAX_BATCH)} imported rows added.`);
  };

  let activeCaptchaJob = null;

  function setCaptchaImage(url) {
    const image = $('#captcha-image');
    const loading = $('#captcha-loading');
    const error = $('#captcha-image-error');
    state.captchaImageUrl = url || '';
    image.hidden = true;
    error.classList.add('hidden');
    loading.classList.remove('hidden');
    if (!url) {
      loading.classList.add('hidden');
      error.classList.remove('hidden');
      return;
    }
    image.onload = () => {
      loading.classList.add('hidden');
      error.classList.add('hidden');
      image.hidden = false;
      $('#captcha-answer').focus();
    };
    image.onerror = () => {
      loading.classList.add('hidden');
      image.hidden = true;
      error.classList.remove('hidden');
    };
    const separator = url.includes('?') ? '&' : '?';
    image.src = `${url}${separator}reload=${Date.now()}`;
  }

  async function requestCaptchaAnswer(jobId, data) {
    activeCaptchaJob = jobId;
    $('#captcha-message').textContent = data.message || 'Amazon requires human verification.';
    $('#captcha-answer').value = '';
    setCaptchaImage(data.captchaImage);
    $('#captcha-dialog').showModal();
    return new Promise((resolve, reject) => {
      state.captchaResolve = resolve;
      state.captchaReject = reject;
    });
  }

  $('#captcha-reload').onclick = () => setCaptchaImage(state.captchaImageUrl);

  $('#captcha-form').onsubmit = async event => {
    event.preventDefault();
    const answer = $('#captcha-answer').value.trim();
    if (!answer) return;
    const submitButton = $('#captcha-form button[type="submit"]');
    submitButton.disabled = true;
    submitButton.textContent = 'Checking…';
    try {
      const response = await fetch(`/api/jobs/${activeCaptchaJob}/captcha`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ answer })
      });
      const data = await response.json();
      if (!response.ok || !data.accepted) {
        $('#captcha-message').textContent = data.message || data.error || 'That answer was not accepted.';
        if (data.captchaImage) setCaptchaImage(data.captchaImage);
        $('#captcha-answer').value = '';
        return;
      }
      $('#captcha-dialog').close();
      state.captchaResolve?.();
      state.captchaResolve = null;
      state.captchaReject = null;
    } finally {
      submitButton.disabled = false;
      submitButton.textContent = 'Submit and continue';
    }
  };

  $('#captcha-cancel').onclick = () => {
    $('#captcha-dialog').close();
    state.captchaReject?.(new Error('Research stopped at the CAPTCHA checkpoint.'));
    state.captchaResolve = null;
    state.captchaReject = null;
  };

  $('#run-research').onclick = async () => {
    if (!state.queue.length) return;
    $('#run-research').disabled = true;
    $('#progress-section').classList.remove('hidden');
    $('#progress-section').scrollIntoView({ behavior: 'smooth' });
    try {
      let response = await fetch('/api/jobs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ items: state.queue })
      });
      let data = await response.json();
      if (!response.ok) throw new Error(data.error);
      const id = data.jobId;
      const total = data.count;
      let completed = 0;
      while (completed < total) {
        setProgress(completed, total, `Researching ${label(state.queue[completed])}`);
        response = await fetch(`/api/jobs/${id}/next`, { method: 'POST' });
        data = await response.json();
        if (!response.ok) throw new Error(data.error);
        if (data.captchaRequired) {
          setProgress(completed, total, 'Amazon requires a CAPTCHA. Complete it to resume this same session.');
          await requestCaptchaAnswer(id, data);
          continue;
        }
        state.results.unshift(data.result);
        saveResults();
        completed = data.processed;
      }
      setProgress(total, total, 'Research complete. Categorizing the catalog and building cross-sell / upsell suggestions…');
      await enrichCatalog();
      setProgress(total, total, 'Research complete. Review the results below.');
      state.queue = [];
      renderQueue();
      $('#results').scrollIntoView({ behavior: 'smooth' });
      toast('Product research complete.');
    } catch (error) {
      setProgress(0, 1, error.message);
      toast(error.message);
    } finally {
      $('#run-research').disabled = !state.queue.length;
    }
  };

  function setProgress(done, total, message) {
    $('#progress-number').textContent = `${done} / ${total}`;
    $('#progress-bar').style.width = `${total ? done / total * 100 : 0}%`;
    $('#progress-message').textContent = message;
  }

  function renderMetrics() {
    $('#metric-total').textContent = state.results.length;
    $('#metric-complete').textContent = state.results.filter(item => item.status === 'Complete').length;
    $('#metric-review').textContent = state.results.filter(item => item.status === 'Needs review').length;
    $('#metric-error').textContent = state.results.filter(item => item.status === 'Error').length;
    $('#metric-competitors').textContent = state.results.reduce((n,item)=>n+(item.competitors?.length||0),0);
    const margins=state.results.map(x=>x.pricing?.estimatedMargin).filter(x=>Number.isFinite(x));
    $('#metric-margin').textContent = margins.length ? `${(margins.reduce((a,b)=>a+b,0)/margins.length).toFixed(1)}%` : '—';
  }

  function filteredResults() {
    const query = state.resultSearch.trim().toLowerCase();
    return state.results.filter(result => {
      const matchesStatus = !state.resultStatus || result.status === state.resultStatus;
      const haystack = [result.title, result.asin, result.brand, result.status, result.seller, result.price, result.catalogCategory?.category, result.catalogCategory?.subcategory]
        .filter(Boolean).join(' ').toLowerCase();
      return matchesStatus && (!query || haystack.includes(query));
    });
  }

  function renderResults() {
    renderMetrics();
    const list = $('#results-list');
    const visible = filteredResults();
    $('#results-empty').classList.toggle('hidden', visible.length > 0);
    $('#results-empty').textContent = state.results.length ? 'No saved results match these filters.' : 'Completed products will appear here.';
    $('#export-xlsx').disabled = !state.results.length;
    $('#export-csv').disabled = !state.results.length;
    $('#retry-incomplete').disabled = !state.results.some(result => result.status !== 'Complete');
    list.innerHTML = visible.map(result => {
      const index = state.results.indexOf(result);
      return `<article class="card result-card">
        <div class="result-image">${result.images?.[0] ? `<img src="${esc(result.images[0])}" alt="">` : 'No image available'}</div>
        <div>
          <div class="result-top">
            <div><p class="eyebrow">${esc(result.asin || 'Amazon product')}</p><h3>${esc(result.title || 'Product research failed')}</h3></div>
            <span class="status ${esc((result.status || '').toLowerCase().replace(/\s/g, '-'))}">${esc(result.status || 'Unknown')}</span>
          </div>
          ${result.error ? `<p class="error-message">${esc(result.error)}</p>` : ''}
          <div class="meta">
            ${result.price ? `<span>${esc(result.price)}</span>` : ''}
            ${result.brand ? `<span>${esc(result.brand)}</span>` : ''}
            ${result.rating ? `<span>${esc(result.rating)}</span>` : ''}
            ${result.reviewCount ? `<span>${esc(result.reviewCount)}</span>` : ''}
            ${result.availability ? `<span>${esc(result.availability)}</span>` : ''}
          </div>
          ${result.catalogCategory ? `<p class="catalog-path"><strong>${esc(result.catalogCategory.category || '')}</strong>${result.catalogCategory.subcategory ? ` <span>›</span> ${esc(result.catalogCategory.subcategory)}` : ''}</p>` : ''}
          ${result.url ? `<p><a href="${esc(result.url)}" target="_blank" rel="noopener">Open Amazon listing</a></p>` : ''}
          ${result.pricing ? `<div class="intelligence-grid">
            <span><small>Input cost</small><b>${result.pricing.cost != null ? '$'+Number(result.pricing.cost).toFixed(2) : '—'}</b></span>
            <span><small>Market average</small><b>${result.pricing.marketAverage != null ? '$'+Number(result.pricing.marketAverage).toFixed(2) : '—'}</b></span>
            <span><small>Suggested price</small><b>${result.pricing.suggestedPrice != null ? '$'+Number(result.pricing.suggestedPrice).toFixed(2) : '—'}</b></span>
            <span><small>Est. margin</small><b>${result.pricing.estimatedMargin != null ? result.pricing.estimatedMargin+'%' : '—'}</b></span>
          </div>` : ''}
          ${result.competitors?.length ? `<details><summary>Competitor research (${result.competitors.length})</summary><div class="competitor-list">${result.competitors.map(c=>`<p><strong>${esc(c.retailer)}</strong>${c.domain ? ` <small>${esc(c.domain)}</small>` : ''} ${c.price ? ' · $'+Number(c.price).toFixed(2) : ''} · ${esc(c.matchConfidence||'')}${Number.isFinite(c.matchScore) ? ` (${c.matchScore}%)` : ''} ${c.url ? `<a href="${esc(c.url)}" target="_blank" rel="noopener">View listing</a>`:''}</p>`).join('')}</div></details>` : ''}
          ${result.crossSells?.length ? `<details><summary>Cross-sell ideas from this catalog (${result.crossSells.length})</summary><div class="recommendation-list">${result.crossSells.map(x=>`<div class="recommendation-row">${x.image ? `<img src="${esc(x.image)}" alt="">` : ''}<span><strong>${esc(x.title)}</strong><small>${esc(x.reason || '')}${x.price != null ? ` · $${Number(x.price).toFixed(2)}` : ''}</small></span></div>`).join('')}</div></details>` : ''}
          ${result.upsells?.length ? `<details><summary>Upsell ideas from this catalog (${result.upsells.length})</summary><div class="recommendation-list">${result.upsells.map(x=>`<div class="recommendation-row">${x.image ? `<img src="${esc(x.image)}" alt="">` : ''}<span><strong>${esc(x.title)}</strong><small>${esc(x.reason || '')}${x.price != null ? ` · $${Number(x.price).toFixed(2)}` : ''}</small></span></div>`).join('')}</div></details>` : ''}
          <details>
            <summary>Extracted listing details</summary>
            ${result.bullets?.length ? `<h4>Bullet points</h4><ul>${result.bullets.map(value => `<li>${esc(value)}</li>`).join('')}</ul>` : ''}
            ${result.description ? `<h4>Description</h4><p>${esc(result.description)}</p>` : ''}
            ${result.categories?.length ? `<h4>Category</h4><p>${esc(result.categories.join(' > '))}</p>` : ''}
            ${result.details && Object.keys(result.details).length ? `<h4>Technical details</h4><ul>${Object.entries(result.details).map(([key, value]) => `<li><strong>${esc(key)}:</strong> ${esc(value)}</li>`).join('')}</ul>` : ''}
          </details>
          <button class="text-button delete-result" data-index="${index}" type="button">Delete result</button>
        </div>
      </article>`;
    }).join('');
    document.querySelectorAll('.delete-result').forEach(button => {
      button.onclick = () => {
        state.results.splice(Number(button.dataset.index), 1);
        saveResults();
      };
    });
  }

  $('#result-search').oninput = event => { state.resultSearch = event.target.value; renderResults(); };
  $('#result-status').onchange = event => { state.resultStatus = event.target.value; renderResults(); };

  $('#retry-incomplete').onclick = () => {
    const retryItems = state.results
      .filter(result => result.status !== 'Complete')
      .map(result => result.sourceInput || { asin: result.asin || '', url: result.url || '', name: result.title || '' })
      .filter(item => item.asin || item.url || item.name);
    const before = state.queue.length;
    addItems(retryItems);
    const added = state.queue.length - before;
    toast(added ? `${added} incomplete product${added === 1 ? '' : 's'} requeued.` : 'No additional products could be added to the current queue.');
    if (added) $('#research').scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  $('#clear-results').onclick = () => {
    if (confirm('Delete all saved ProductIQ results from this browser?')) {
      state.results = [];
      saveResults();
    }
  };

  async function exportResults(format) {
    const response = await fetch(`/api/export/${format}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ results: state.results })
    });
    if (!response.ok) {
      const data = await response.json();
      return toast(data.error);
    }
    const blob = await response.blob();
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `productiq-amazon-research.${format}`;
    link.click();
    URL.revokeObjectURL(link.href);
  }

  $('#export-xlsx').onclick = () => exportResults('xlsx');
  $('#export-csv').onclick = () => exportResults('csv');

  renderQueue();
  renderResults();
  if (state.results.length) enrichCatalog();
})();

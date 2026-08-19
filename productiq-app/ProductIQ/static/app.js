(() => {
  'use strict';

  const MAX_BATCH = Number(document.body.dataset.maxBatch || 25);
  const STORAGE_KEY = 'productiq-results-v2';
  const state = {
    queue: [],
    importedRows: [],
    importedColumns: [],
    results: JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]'),
    captchaResolve: null,
    captchaReject: null,
    activeCaptchaJob: null,
    activeResearchJob: null,
    browserPollTimer: null,
    resultSearch: '',
    resultStatus: ''
  };

  const $ = selector => document.querySelector(selector);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, character => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  })[character]);

  async function readJson(response) {
    const text = await response.text();
    if (!text) return {};
    try {
      return JSON.parse(text);
    } catch (_) {
      throw new Error(
        response.ok
          ? 'ProductIQ returned an unreadable response.'
          : `ProductIQ server error (HTTP ${response.status}). Check the Render log for the matching request.`
      );
    }
  }

  function toast(message) {
    const element = $('#toast');
    if (!element) return;
    element.textContent = message;
    element.classList.remove('hidden');
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => element.classList.add('hidden'), 3500);
  }

  function identity(result) {
    const source = result?.sourceInput || {};
    return String(
      result?.asin || source.asin || source.sku || source.upc || source.model ||
      source.url || source.name || result?.url || result?.title || ''
    ).trim().toLowerCase();
  }

  function upsertResult(result) {
    if (!result) return;
    const id = identity(result);
    const index = id ? state.results.findIndex(existing => identity(existing) === id) : -1;
    if (index >= 0) state.results[index] = result;
    else state.results.unshift(result);
  }

  function saveResults() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state.results));
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
      const data = await readJson(response);
      if (!response.ok) throw new Error(data.error || 'Catalog analysis failed.');
      state.results = data.results || state.results;
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state.results));
      renderResults();
    } catch (error) {
      console.warn('Catalog enrichment skipped:', error);
    }
  }

  function kind(value) {
    if (/amazon\.|^https?:/i.test(value)) return 'Amazon URL';
    if (/^[A-Z0-9]{10}$/i.test(value)) return 'ASIN';
    if (/^\d{8,14}$/.test(value.replace(/[\s-]/g, ''))) return 'UPC/EAN';
    return 'Product name';
  }

  function queueItem(value) {
    value = value.trim();
    const type = kind(value);
    if (type === 'Amazon URL') return { url: value, asin: '', name: '' };
    if (type === 'ASIN') return { asin: value.toUpperCase(), url: '', name: '' };
    if (type === 'UPC/EAN') return { upc: value.replace(/[\s-]/g, ''), asin: '', url: '', name: '' };
    return { name: value, asin: '', url: '' };
  }

  function label(item) {
    return item.asin || item.url || item.name || item.upc || item.model || item.sku || 'Unknown product';
  }

  function addItems(items) {
    for (const item of items) {
      if (state.queue.length >= MAX_BATCH) break;
      const id = label(item).trim().toLowerCase();
      if (!state.queue.some(existing => label(existing).trim().toLowerCase() === id)) {
        state.queue.push(item);
      }
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
    if (button) {
      button.disabled = true;
      button.textContent = 'Loading...';
    }

    try {
      let items = embeddedSampleProducts();
      if (!items.length) {
        const sampleUrl = document.body.dataset.sampleUrl || '/api/sample';
        const response = await fetch(sampleUrl, { cache: 'no-store' });
        const data = await readJson(response);
        if (!response.ok) throw new Error(data.error || 'Could not load the sample data.');
        items = data.items || [];
      }

      items = items.slice(0, MAX_BATCH);
      if (!items.length) throw new Error('The included sample data is empty.');

      const before = state.queue.length;
      addItems(items);
      const added = state.queue.length - before;
      const skipped = items.length - added;

      toast(added
        ? `${added} sample product${added === 1 ? '' : 's'} added${skipped ? ` (${skipped} already queued or over the batch limit)` : ''}.`
        : 'The sample products are already in the queue.');

      $('#research').scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (error) {
      toast(error.message);
    } finally {
      if (button) {
        button.disabled = false;
        button.textContent = originalText;
      }
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
    $('#upload-message').textContent = 'Reading spreadsheet...';
    $('#upload-message').classList.remove('hidden');

    try {
      const response = await fetch('/api/import', { method: 'POST', body: form });
      const data = await readJson(response);
      if (!response.ok) throw new Error(data.error);

      state.importedRows = data.rows;
      state.importedColumns = data.columns;

      fillSelect('#map-asin', guess(data.columns, [/^asin$/i, /amazon.*id/i]));
      fillSelect('#map-url', guess(data.columns, [/url/i, /link/i]));
      fillSelect('#map-name', guess(data.columns, [/product.*name/i, /title/i, /^name$/i, /description/i]));
      fillSelect('#map-sku', guess(data.columns, [/^sku$/i, /item.*sku/i, /seller.*sku/i]));
      fillSelect('#map-upc', guess(data.columns, [/^upc$/i, /^ean$/i, /gtin/i, /barcode/i]));
      fillSelect('#map-model', guess(data.columns, [/model/i, /mpn/i, /part.*number/i]));
      fillSelect('#map-brand', guess(data.columns, [/brand/i, /manufacturer/i]));
      fillSelect('#map-cost', guess(data.columns, [/cost/i, /purchase.*price/i, /price.*paid/i]));
      fillSelect('#map-quantity', guess(data.columns, [/quantity/i, /^qty$/i, /stock/i, /on.*hand/i]));
      fillSelect('#map-shipping-cost', guess(data.columns, [/shipping.*cost/i, /inbound.*shipping/i]));
      fillSelect('#map-fees', guess(data.columns, [/fixed.*fee/i, /^fees?$/i]));
      fillSelect('#map-fee-rate', guess(data.columns, [/fee.*rate/i, /fee.*%/i]));
      fillSelect('#map-category', guess(data.columns, [/^category$/i, /department/i]));
      fillSelect('#map-subcategory', guess(data.columns, [/sub.*category/i, /product.*type/i]));
      fillSelect('#map-condition', guess(data.columns, [/condition/i]));
      fillSelect('#map-pack-count', guess(data.columns, [/pack.*count/i, /units.*pack/i, /^count$/i]));

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
    const skuColumn = $('#map-sku').value;
    const upcColumn = $('#map-upc').value;
    const modelColumn = $('#map-model').value;
    const brandColumn = $('#map-brand').value;
    const costColumn = $('#map-cost').value;
    const quantityColumn = $('#map-quantity').value;
    const shippingColumn = $('#map-shipping-cost').value;
    const feesColumn = $('#map-fees').value;
    const feeRateColumn = $('#map-fee-rate').value;
    const categoryColumn = $('#map-category').value;
    const subcategoryColumn = $('#map-subcategory').value;
    const conditionColumn = $('#map-condition').value;
    const packCountColumn = $('#map-pack-count').value;

    if (!asinColumn && !urlColumn && !nameColumn && !upcColumn && !modelColumn) {
      return toast('Map at least one product identifier or name column.');
    }

    const items = state.importedRows.map(row => ({
      asin: asinColumn ? String(row[asinColumn] || '').trim() : '',
      url: urlColumn ? String(row[urlColumn] || '').trim() : '',
      name: nameColumn ? String(row[nameColumn] || '').trim() : '',
      sku: skuColumn ? String(row[skuColumn] || '').trim() : '',
      upc: upcColumn ? String(row[upcColumn] || '').trim() : '',
      model: modelColumn ? String(row[modelColumn] || '').trim() : '',
      brand: brandColumn ? String(row[brandColumn] || '').trim() : '',
      cost: costColumn ? String(row[costColumn] || '').trim() : '',
      quantity: quantityColumn ? String(row[quantityColumn] || '').trim() : '',
      shipping_cost: shippingColumn ? String(row[shippingColumn] || '').trim() : '',
      fees: feesColumn ? String(row[feesColumn] || '').trim() : '',
      fee_rate: feeRateColumn ? String(row[feeRateColumn] || '').trim() : '',
      category: categoryColumn ? String(row[categoryColumn] || '').trim() : '',
      subcategory: subcategoryColumn ? String(row[subcategoryColumn] || '').trim() : '',
      condition: conditionColumn ? String(row[conditionColumn] || '').trim() : '',
      pack_count: packCountColumn ? String(row[packCountColumn] || '').trim() : ''
    })).filter(item => item.asin || item.url || item.name || item.upc || item.model);

    addItems(items);
    toast(`${Math.min(items.length, MAX_BATCH)} imported rows added.`);
  };

  async function waitForCaptcha(jobId) {
    while (state.activeCaptchaJob === jobId && state.captchaResolve) {
      await new Promise(resolve => setTimeout(resolve, 1600));
      try {
        const response = await fetch(`/api/jobs/${jobId}`, { cache: 'no-store' });
        const data = await readJson(response);
        if (response.ok && data.status !== 'captcha_required') {
          $('#captcha-dialog').close();
          const resolve = state.captchaResolve;
          state.captchaResolve = null;
          state.captchaReject = null;
          state.activeCaptchaJob = null;
          resolve?.();
          return;
        }
      } catch (_) {}
    }
  }

  async function requestCaptchaAnswer(jobId, data) {
    state.activeCaptchaJob = jobId;

    if (data.partialResult) {
      upsertResult(data.partialResult);
      saveResults();
    }

    $('#captcha-message').textContent =
      data.message || 'Amazon paused this product for human verification.';

    const link = $('#captcha-open');
    link.href = data.verificationUrl || `/verify/${jobId}`;
    $('#captcha-dialog').showModal();

    return new Promise((resolve, reject) => {
      state.captchaResolve = resolve;
      state.captchaReject = reject;
      waitForCaptcha(jobId);
    });
  }

  $('#captcha-cancel').onclick = () => {
    $('#captcha-dialog').close();
    const reject = state.captchaReject;
    state.captchaResolve = null;
    state.captchaReject = null;
    state.activeCaptchaJob = null;
    reject?.(new Error('Research stopped at the Amazon verification checkpoint.'));
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
      let data = await readJson(response);
      if (!response.ok) throw new Error(data.error);

      const id = data.jobId;
      const total = data.count;
      let completed = 0;
      startBrowserPolling(id);

      while (completed < total) {
        setProgress(completed, total, `Researching ${label(state.queue[completed])}`);

        response = await fetch(`/api/jobs/${id}/next`, { method: 'POST' });
        data = await readJson(response);
        if (!response.ok) throw new Error(data.error);

        if (data.captchaRequired) {
          setProgress(
            completed,
            total,
            'Amazon needs verification. Open the verification tab, complete it, then come back here.'
          );
          await requestCaptchaAnswer(id, data);
          continue;
        }

        if (data.result) {
          upsertResult(data.result);
          saveResults();
        }
        completed = data.processed;
      }

      setProgress(
        total,
        total,
        'Research complete. Updating categories and catalog relationships...'
      );
      await enrichCatalog();
      setProgress(total, total, 'Research complete. Review the results below.');

      state.queue = [];
      renderQueue();
      $('#results').scrollIntoView({ behavior: 'smooth' });
      toast('Product research complete.');
      stopBrowserPolling();
    } catch (error) {
      const message = error?.message || String(error) || 'Product research failed.';
      setProgress(0, 1, message);
      toast(message);
    } finally {
      stopBrowserPolling();
      $('#run-research').disabled = !state.queue.length;
    }
  };

  function ensureBrowserPanel() {
    let panel = document.getElementById('browser-activity');
    if (panel) return panel;
    const progressCard = document.querySelector('#progress-section .progress-card');
    if (!progressCard) return null;

    panel = document.createElement('details');
    panel.id = 'browser-activity';
    panel.className = 'browser-activity';
    panel.innerHTML = `
      <summary>Browser activity</summary>
      <div style="display:grid;gap:10px;margin-top:12px">
        <div id="browser-current" class="notice">Waiting for browser activity...</div>
        <img id="browser-screenshot" alt="Current Amazon browser view"
             style="display:none;width:100%;max-height:520px;object-fit:contain;background:#fff;border-radius:12px">
        <div id="browser-events" style="display:grid;gap:6px"></div>
      </div>`;
    progressCard.appendChild(panel);
    return panel;
  }

  async function refreshBrowserActivity(jobId) {
    if (!jobId) return;
    ensureBrowserPanel();
    try {
      const response = await fetch(`/api/jobs/${jobId}/browser-debug?ts=${Date.now()}`, {cache:'no-store'});
      const data = await readJson(response);
      if (!response.ok) return;

      const current = document.getElementById('browser-current');
      if (current) {
        const parts = [];
        if (data.title) parts.push(data.title);
        if (data.url) parts.push(data.url);
        current.textContent = parts.join(' | ') || 'Browser is running...';
      }

      const events = document.getElementById('browser-events');
      if (events) {
        const rows = (data.events || []).slice(-12).reverse();
        events.innerHTML = rows.map(item => `
          <div style="padding:8px 10px;border:1px solid rgba(255,255,255,.08);border-radius:10px">
            <strong>${esc(item.event || '')}</strong>
            ${item.detail ? `<div>${esc(item.detail)}</div>` : ''}
            ${item.url ? `<small>${esc(item.url)}</small>` : ''}
          </div>`).join('');
      }

      const img = document.getElementById('browser-screenshot');
      if (img && data.hasScreenshot) {
        img.src = `/api/jobs/${jobId}/browser-screenshot?ts=${Date.now()}`;
        img.style.display = 'block';
      }
    } catch (_) {}
  }

  function startBrowserPolling(jobId) {
    state.activeResearchJob = jobId;
    clearInterval(state.browserPollTimer);
    refreshBrowserActivity(jobId);
    state.browserPollTimer = setInterval(() => refreshBrowserActivity(jobId), 1200);
  }

  function stopBrowserPolling() {
    clearInterval(state.browserPollTimer);
    state.browserPollTimer = null;
  }

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
    $('#metric-competitors').textContent = state.results.reduce(
      (count, item) => count + (item.competitors?.length || 0), 0
    );
    const margins = state.results
      .map(item => item.pricing?.estimatedMargin)
      .filter(value => Number.isFinite(value));
    $('#metric-margin').textContent = margins.length
      ? `${(margins.reduce((a, b) => a + b, 0) / margins.length).toFixed(1)}%`
      : '0%';
  }

  function filteredResults() {
    const query = state.resultSearch.trim().toLowerCase();
    return state.results.filter(result => {
      const matchesStatus = !state.resultStatus || result.status === state.resultStatus;
      const haystack = [
        result.title, result.asin, result.brand, result.status, result.seller,
        result.price, result.sourceInput?.upc, result.sourceInput?.model,
        result.catalogCategory?.category, result.catalogCategory?.subcategory
      ].filter(Boolean).join(' ').toLowerCase();
      return matchesStatus && (!query || haystack.includes(query));
    });
  }

  function competitorDiagnostics(result) {
    const info = result.competitorResearch || {};
    if (result.competitors?.length) return '';
    if (!info.queriesTried?.length && !info.message) return '';
    const providers = Object.entries(info.providers || {})
      .map(([name, status]) => `${name}: ${status}`)
      .join(' | ');
    return `<details>
      <summary>Competitor search details</summary>
      ${info.message ? `<p>${esc(info.message)}</p>` : ''}
      ${info.queriesTried?.length ? `<p><strong>Queries tried:</strong> ${info.queriesTried.map(esc).join(' | ')}</p>` : ''}
      ${providers ? `<p><strong>Search providers:</strong> ${esc(providers)}</p>` : ''}
    </details>`;
  }

  function renderResults() {
    renderMetrics();

    const list = $('#results-list');
    const visible = filteredResults();
    $('#results-empty').classList.toggle('hidden', visible.length > 0);
    $('#results-empty').textContent = state.results.length
      ? 'No saved results match these filters.'
      : 'Completed products will appear here.';

    $('#export-xlsx').disabled = !state.results.length;
    $('#export-csv').disabled = !state.results.length;
    $('#retry-incomplete').disabled = !state.results.some(result => result.status !== 'Complete');

    list.innerHTML = visible.map(result => {
      const index = state.results.indexOf(result);
      const category = result.catalogCategory || {};
      const pricing = result.pricing || {};
      return `<article class="card result-card">
        <div class="result-image">${result.images?.[0] ? `<img src="${esc(result.images[0])}" alt="">` : 'No image available'}</div>
        <div>
          <div class="result-top">
            <div>
              <p class="eyebrow">${esc(result.asin || result.sourceInput?.upc || result.sourceInput?.model || 'Inventory product')}</p>
              <h3>${esc(result.title || 'Product research result')}</h3>
            </div>
            <span class="status ${esc((result.status || '').toLowerCase().replace(/\s/g, '-'))}">
              ${esc(result.status || 'Unknown')}
            </span>
          </div>

          ${result.error ? `<p class="error-message">${esc(result.error)}</p>` : ''}
          ${result.intelligenceError ? `<p class="notice">Market research warning: ${esc(result.intelligenceError)}</p>` : ''}

          <div class="meta">
            ${result.price ? `<span>${esc(result.price)}</span>` : ''}
            ${result.brand ? `<span>${esc(result.brand)}</span>` : ''}
            ${result.rating ? `<span>${esc(result.rating)}</span>` : ''}
            ${result.reviewCount ? `<span>${esc(result.reviewCount)}</span>` : ''}
            ${result.availability ? `<span>${esc(result.availability)}</span>` : ''}
          </div>

          ${category.category ? `<p class="catalog-path">
            <strong>${esc(category.category)}</strong>
            ${category.subcategory ? ` <span>âº</span> ${esc(category.subcategory)}` : ''}
            ${category.confidence != null ? ` <small>(${esc(category.confidence)}% category confidence)</small>` : ''}
          </p>` : ''}

          ${result.url ? `<p><a href="${esc(result.url)}" target="_blank" rel="noopener">Open product listing</a></p>` : ''}

          <div class="intelligence-grid">
            <span><small>Input cost</small><b>${pricing.cost != null ? '$' + Number(pricing.cost).toFixed(2) : 'N/A'}</b></span>
            <span><small>Market average</small><b>${pricing.marketAverage != null ? '$' + Number(pricing.marketAverage).toFixed(2) : 'N/A'}</b></span>
            <span><small>Suggested price</small><b>${pricing.suggestedPrice != null ? '$' + Number(pricing.suggestedPrice).toFixed(2) : 'N/A'}</b></span>
            <span><small>Est. margin</small><b>${pricing.estimatedMargin != null ? pricing.estimatedMargin + '%' : 'N/A'}</b></span>
          </div>

          ${result.competitors?.length ? `<details>
            <summary>Competitor research (${result.competitors.length})</summary>
            <div class="competitor-list">${result.competitors.map(candidate => `
              <p>
                <strong>${esc(candidate.retailer)}</strong>
                ${candidate.domain ? ` <small>${esc(candidate.domain)}</small>` : ''}
                ${candidate.price != null ? ` | $${Number(candidate.price).toFixed(2)}` : ' | price unavailable'}
                | ${esc(candidate.matchConfidence || '')}
                ${Number.isFinite(candidate.matchScore) ? ` (${candidate.matchScore}%)` : ''}
                ${candidate.matchReason ? ` | ${esc(candidate.matchReason)}` : ''}
                ${candidate.url ? ` <a href="${esc(candidate.url)}" target="_blank" rel="noopener">View listing</a>` : ''}
              </p>`).join('')}
            </div>
          </details>` : competitorDiagnostics(result)}

          ${result.crossSells?.length ? `<details>
            <summary>Cross-sells from this catalog (${result.crossSells.length})</summary>
            <div class="recommendation-list">${result.crossSells.map(item => `
              <div class="recommendation-row">
                ${item.image ? `<img src="${esc(item.image)}" alt="">` : ''}
                <span><strong>${esc(item.title)}</strong><small>${esc(item.reason || '')}${item.price != null ? ` | $${Number(item.price).toFixed(2)}` : ''}</small></span>
              </div>`).join('')}
            </div>
          </details>` : ''}

          ${result.upsells?.length ? `<details>
            <summary>Upsells from this catalog (${result.upsells.length})</summary>
            <div class="recommendation-list">${result.upsells.map(item => `
              <div class="recommendation-row">
                ${item.image ? `<img src="${esc(item.image)}" alt="">` : ''}
                <span><strong>${esc(item.title)}</strong><small>${esc(item.reason || '')}${item.price != null ? ` | $${Number(item.price).toFixed(2)}` : ''}</small></span>
              </div>`).join('')}
            </div>
          </details>` : ''}

          <details>
            <summary>Extracted listing details</summary>
            ${result.bullets?.length ? `<h4>Bullet points</h4><ul>${result.bullets.map(value => `<li>${esc(value)}</li>`).join('')}</ul>` : ''}
            ${result.description ? `<h4>Description</h4><p>${esc(result.description)}</p>` : ''}
            ${result.categories?.length ? `<h4>Marketplace category</h4><p>${esc(result.categories.join(' > '))}</p>` : ''}
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

  $('#result-search').oninput = event => {
    state.resultSearch = event.target.value;
    renderResults();
  };

  $('#result-status').onchange = event => {
    state.resultStatus = event.target.value;
    renderResults();
  };

  $('#retry-incomplete').onclick = () => {
    const retryItems = state.results
      .filter(result => result.status !== 'Complete')
      .map(result => result.sourceInput || {
        asin: result.asin || '',
        url: result.url || '',
        name: result.title || ''
      })
      .filter(item => item.asin || item.url || item.name || item.upc || item.model);

    const before = state.queue.length;
    addItems(retryItems);
    const added = state.queue.length - before;
    toast(added
      ? `${added} incomplete product${added === 1 ? '' : 's'} requeued.`
      : 'No additional products could be added to the current queue.');

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
      const data = await readJson(response);
      return toast(data.error);
    }

    const blob = await response.blob();
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `productiq-research.${format}`;
    link.click();
    URL.revokeObjectURL(link.href);
  }

  $('#export-xlsx').onclick = () => exportResults('xlsx');
  $('#export-csv').onclick = () => exportResults('csv');

  renderQueue();
  renderResults();
  if (state.results.length) enrichCatalog();
})();

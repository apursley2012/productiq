document.addEventListener('DOMContentLoaded', () => {
  const { $, esc, money, load, save, title, category, subcategory } = PIQ;
  let results = load();
  const select = $('#market-product');

  select.innerHTML = results.length
    ? results.map((result, index) => `<option value="${index}">${esc(title(result))}</option>`).join('')
    : '<option>No saved products</option>';

  const wanted = new URLSearchParams(location.search).get('product');
  if (wanted) {
    const index = results.findIndex(result => (result.asin || title(result)) === wanted);
    if (index >= 0) select.value = index;
  }

  function diagnostics(result) {
    const info = result?.competitorResearch || {};
    if (!info.queriesTried?.length && !info.message) return '';
    const providers = Object.entries(info.providers || {})
      .map(([name, value]) => `${name}: ${value}`)
      .join(' · ');
    return `<div class="notice">
      ${info.message ? `<p>${esc(info.message)}</p>` : ''}
      ${info.queriesTried?.length ? `<p><strong>Queries tried:</strong> ${info.queriesTried.map(esc).join(' · ')}</p>` : ''}
      ${providers ? `<p><strong>Search providers:</strong> ${esc(providers)}</p>` : ''}
    </div>`;
  }

  function render() {
    const result = results[Number(select.value)];
    if (!result) {
      $('#competitor-table').innerHTML = '<div class="empty">Research products first.</div>';
      return;
    }

    const minimum = Number($('#market-score').value || 0);
    const all = result.competitors || [];
    const matches = all
      .filter(candidate => (candidate.matchScore || 0) >= minimum)
      .sort((a, b) => (a.price ?? 1e12) - (b.price ?? 1e12));

    $('#market-summary').innerHTML = `
      <article class="metric-card"><span>Listings found</span><strong>${all.length}</strong></article>
      <article class="metric-card"><span>Market low</span><strong>${money(result.pricing?.marketLow)}</strong></article>
      <article class="metric-card"><span>Market average</span><strong>${money(result.pricing?.marketAverage)}</strong></article>
      <article class="metric-card"><span>Market high</span><strong>${money(result.pricing?.marketHigh)}</strong></article>`;

    $('#market-product-summary').innerHTML = `
      <article class="card">
        <p class="catalog-path"><strong>${esc(category(result))}</strong> › ${esc(subcategory(result))}</p>
        <h2>${esc(title(result))}</h2>
        <p>${esc(result.identification?.status || '')}</p>
      </article>`;

    if (matches.length) {
      $('#competitor-table').innerHTML = `<table>
        <thead><tr><th>Store</th><th>Listing</th><th>Price</th><th>Match</th><th></th></tr></thead>
        <tbody>${matches.map(candidate => `<tr>
          <td><strong>${esc(candidate.retailer)}</strong><br><small>${esc(candidate.domain || '')}</small></td>
          <td>${esc(candidate.title || '')}<br><small>${esc(candidate.discoveredVia || '')}</small></td>
          <td>${money(candidate.price)}</td>
          <td>
            ${esc(candidate.matchConfidence || '')} ${Number.isFinite(candidate.matchScore) ? `(${candidate.matchScore}%)` : ''}
            <br><small>${esc(candidate.matchReason || '')}${candidate.variantConflicts?.length ? ` · ${esc(candidate.variantConflicts.join('; '))}` : ''}</small>
          </td>
          <td>${candidate.url ? `<a href="${esc(candidate.url)}" target="_blank" rel="noopener">Open</a>` : ''}</td>
        </tr>`).join('')}</tbody>
      </table>`;
    } else {
      $('#competitor-table').innerHTML = `
        <div class="empty">No competitor listings meet the current ${minimum}% match threshold.</div>
        ${diagnostics(result)}`;
    }
  }

  select.onchange = render;
  $('#market-score').oninput = render;

  $('#refresh-competitors').onclick = async () => {
    const result = results[Number(select.value)];
    if (!result) return;

    const button = $('#refresh-competitors');
    button.disabled = true;
    button.textContent = 'Researching…';

    try {
      const response = await fetch('/api/competitors/research', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({result})
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Research failed');

      result.competitors = data.competitors || [];
      result.pricing = data.pricing || result.pricing || {};
      result.catalogCategory = data.catalogCategory || result.catalogCategory || {};
      result.competitorResearch = data.competitorResearch || {};
      save(results);
      render();
    } catch (error) {
      alert(error.message);
    } finally {
      button.disabled = false;
      button.textContent = 'Research this product again';
    }
  };

  render();
});


(() => {
  const STORAGE = 'productiq-results-v2';
  const $ = s => document.querySelector(s);
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const money = v => Number.isFinite(Number(v)) ? `$${Number(v).toFixed(2)}` : '—';
  const load = () => { try { const x=JSON.parse(localStorage.getItem(STORAGE)||'[]'); return Array.isArray(x)?x:[]; } catch { return []; } };
  const save = x => localStorage.setItem(STORAGE, JSON.stringify(x));
  const price = r => Number(r.pricing?.suggestedPrice ?? String(r.price||'').replace(/[^0-9.]/g,'')) || null;
  const title = r => r.title || r.sourceInput?.name || r.asin || 'Untitled product';
  const img = r => r.images?.[0] || '';
  const category = r => r.catalogCategory?.category || 'Uncategorized';
  const subcategory = r => r.catalogCategory?.subcategory || 'General Merchandise';
  window.PIQ = { $, esc, money, load, save, price, title, img, category, subcategory };
})();

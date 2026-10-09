/* View Data: server-side search + paging over the CSV files in data/. All cell text goes in via textContent. */
(function () {
  'use strict';
  const page = document.getElementById('page-data');
  if (!page) return;

  const tableUrl = page.dataset.tableUrl;
  const importUrl = page.dataset.importUrl;   // only present for administrators
  const scrapeUrl = page.dataset.scrapeUrl;
  const sourceSel = document.getElementById('data-source');
  const searchEl = document.getElementById('data-search');
  const exportBtn = document.getElementById('export-btn');
  const table = document.getElementById('view-table');
  const countEl = document.getElementById('table-count');
  const pager = document.getElementById('pager');
  const prevBtn = document.getElementById('pager-prev');
  const nextBtn = document.getElementById('pager-next');
  const pagerInfo = document.getElementById('pager-info');

  let pageNo = 1, ticket = 0, timer = null, lastPages = 1;
  const nf = new Intl.NumberFormat();

  function setExportLink() {
    exportBtn.href = exportBtn.dataset.urlTemplate.replace('KEY', encodeURIComponent(sourceSel.value));
  }

  function clearTable() { while (table.firstChild) table.removeChild(table.firstChild); }

  function showMessage(text, withLinks) {
    clearTable();
    pager.hidden = true;
    const tbody = table.createTBody();
    const td = tbody.insertRow().insertCell();
    td.className = 'table-empty';
    td.appendChild(document.createTextNode(text));
    if (withLinks && importUrl) {
      td.appendChild(document.createTextNode(' '));
      const a1 = document.createElement('a'); a1.href = importUrl; a1.textContent = 'Import data';
      const a2 = document.createElement('a'); a2.href = scrapeUrl; a2.textContent = 'scrape data';
      td.appendChild(a1); td.appendChild(document.createTextNode(' or ')); td.appendChild(a2);
      td.appendChild(document.createTextNode(' to get started.'));
    }
  }

  function render(d) {
    clearTable();
    const head = table.createTHead().insertRow();
    d.columns.forEach(c => { const th = document.createElement('th'); th.textContent = c; head.appendChild(th); });
    const tbody = table.createTBody();
    if (!d.rows.length) {
      const td = tbody.insertRow().insertCell();
      td.colSpan = Math.max(1, d.columns.length);
      td.className = 'table-empty';
      td.textContent = 'No matching rows.';
    }
    d.rows.forEach(r => {
      const tr = tbody.insertRow();
      r.forEach(v => {
        const td = tr.insertCell();
        td.textContent = v;
        if (v.length > 90) td.className = 'is-long';
      });
    });
    countEl.textContent = d.matched === d.total
      ? nf.format(d.total) + ' rows'
      : nf.format(d.matched) + ' of ' + nf.format(d.total) + ' rows match';
    pageNo = d.page; lastPages = d.pages;
    pager.hidden = d.pages <= 1;
    prevBtn.disabled = d.page <= 1;
    nextBtn.disabled = d.page >= d.pages;
    pagerInfo.textContent = 'Page ' + nf.format(d.page) + ' of ' + nf.format(d.pages);
  }

  function load() {
    const my = ++ticket;
    setExportLink();
    const qs = new URLSearchParams({ source: sourceSel.value, q: searchEl.value, page: pageNo });
    fetch(tableUrl + '?' + qs, { headers: { 'Accept': 'application/json' }, credentials: 'same-origin' })
      .then(r => r.json().then(j => ({ ok: r.ok, j })))
      .then(({ ok, j }) => {
        if (my !== ticket) return;                 // a newer request is in flight
        if (!ok || !j.ok) { showMessage(j.error || 'Could not load this table.'); countEl.textContent = ''; return; }
        if (!j.exists) { showMessage('No data here yet.', true); countEl.textContent = ''; return; }
        render(j);
      })
      .catch(() => { if (my === ticket) { showMessage('Could not reach the server.'); countEl.textContent = ''; } });
  }

  sourceSel.addEventListener('change', () => { searchEl.value = ''; pageNo = 1; load(); });
  searchEl.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(() => { pageNo = 1; load(); }, 250); });
  prevBtn.addEventListener('click', () => { if (pageNo > 1) { pageNo--; load(); } });
  nextBtn.addEventListener('click', () => { if (pageNo < lastPages) { pageNo++; load(); } });

  load();
})();

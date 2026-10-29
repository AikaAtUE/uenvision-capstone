/* View Data: server-side search, per-column sort + filter, and paging over the CSV files in data/.
   All cell text goes in via textContent. */
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
  // Per-column sort / filter, by column index. Reset when another file is picked.
  let sortCol = null, sortDesc = false, filters = {}, headerKey = '';
  const nf = new Intl.NumberFormat();

  // Administrators: "Delete file" for the files that may be deleted (never the raw job postings), and
  // "Clear Kalibrr / Trabajo postings" on Extracted Skills. Both confirm in the same dialog.
  const delForm = document.getElementById('delete-file-form');
  const clearForm = document.getElementById('clear-source-form');
  const delBackdrop = document.getElementById('delete-file-backdrop');
  let pendingForm = null;

  function setExportLink() {
    exportBtn.href = exportBtn.dataset.urlTemplate.replace('KEY', encodeURIComponent(sourceSel.value));
    const opt = sourceSel.selectedOptions[0];
    if (delForm) {
      delForm.hidden = !(opt && opt.dataset.deleteNote && opt.dataset.exists);
      delForm.action = delForm.dataset.urlTemplate.replace('KEY', encodeURIComponent(sourceSel.value));
    }
    if (clearForm) clearForm.hidden = !(opt && opt.value === 'extracted' && opt.dataset.exists);
  }

  function confirmBox(form, heading, note, yesText) {
    pendingForm = form;
    document.getElementById('delete-file-heading').textContent = heading;
    document.getElementById('delete-file-note').textContent = note;
    document.getElementById('delete-file-yes').textContent = yesText;
    delBackdrop.classList.add('is-active');
  }

  if (delForm && delBackdrop) {
    document.getElementById('delete-file-btn').addEventListener('click', () => {
      const opt = sourceSel.selectedOptions[0];
      confirmBox(delForm, 'Delete ' + opt.textContent.trim() + '?', opt.dataset.deleteNote, 'Yes, delete');
    });
    document.getElementById('delete-file-cancel').addEventListener('click', () => delBackdrop.classList.remove('is-active'));
    document.getElementById('delete-file-yes').addEventListener('click', () => { if (pendingForm) pendingForm.submit(); });
  }
  if (clearForm && delBackdrop) {
    clearForm.addEventListener('click', e => {
      const btn = e.target.closest('[data-clear-source]');
      if (!btn) return;
      const label = btn.dataset.label;
      clearForm.action = clearForm.dataset.urlTemplate.replace('SRC', encodeURIComponent(btn.dataset.clearSource));
      confirmBox(clearForm, 'Clear all ' + label + ' job postings from Extracted Skills?',
        'Their rows are removed from Extracted Skills, and Hard Skills and Soft Skills are rebuilt without them. ' +
        'The raw ' + label + ' job postings are kept, so the next ' + label + ' extraction run extracts them again.',
        'Yes, clear');
    });
  }

  function clearTable() { while (table.firstChild) table.removeChild(table.firstChild); headerKey = ''; }

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

  // The header (sort buttons + filter boxes) is built once per file, so typing in a filter box keeps focus.
  function buildHeader(columns) {
    clearTable();
    headerKey = sourceSel.value + '\n' + columns.join('\n');
    const thead = table.createTHead();
    const names = thead.insertRow();
    const boxes = thead.insertRow();
    boxes.className = 'filter-row';
    columns.forEach((c, i) => {
      const th = document.createElement('th');
      th.scope = 'col';
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'sort-btn';
      btn.dataset.col = i;
      btn.title = 'Sort by ' + c;
      btn.appendChild(document.createTextNode(c));
      const ind = document.createElement('span');
      ind.className = 'sort-ind';
      ind.setAttribute('aria-hidden', 'true');
      btn.appendChild(ind);
      th.appendChild(btn);
      names.appendChild(th);

      const fth = document.createElement('th');
      const input = document.createElement('input');
      input.type = 'search';
      input.className = 'col-filter';
      input.dataset.col = i;
      input.placeholder = 'Filter';
      input.setAttribute('aria-label', 'Filter ' + c);
      input.value = filters[i] || '';
      fth.appendChild(input);
      boxes.appendChild(fth);
    });
    names.addEventListener('click', e => {
      const btn = e.target.closest('.sort-btn');
      if (!btn) return;
      const col = Number(btn.dataset.col);
      // ascending -> descending -> unsorted
      if (sortCol !== col) { sortCol = col; sortDesc = false; }
      else if (!sortDesc) { sortDesc = true; }
      else { sortCol = null; sortDesc = false; }
      pageNo = 1; load();
    });
    boxes.addEventListener('input', e => {
      const input = e.target.closest('.col-filter');
      if (!input) return;
      if (input.value.trim()) filters[input.dataset.col] = input.value; else delete filters[input.dataset.col];
      clearTimeout(timer); timer = setTimeout(() => { pageNo = 1; load(); }, 250);
    });
    table.createTBody();
  }

  function showSort() {
    table.querySelectorAll('thead tr:first-child th').forEach((th, i) => {
      const on = sortCol === i;
      if (on) th.setAttribute('aria-sort', sortDesc ? 'descending' : 'ascending'); else th.removeAttribute('aria-sort');
      th.querySelector('.sort-ind').textContent = on ? (sortDesc ? '▼' : '▲') : '↕';
    });
  }

  function render(d) {
    const key = sourceSel.value + '\n' + d.columns.join('\n');
    if (key !== headerKey) buildHeader(d.columns);
    showSort();
    const old = table.tBodies[0];
    const tbody = document.createElement('tbody');
    table.replaceChild(tbody, old);
    if (!d.rows.length) {
      const td = tbody.insertRow().insertCell();
      td.colSpan = Math.max(1, d.columns.length);
      td.className = 'table-empty';
      td.textContent = 'No matching rows.';
    }
    const toggle = e => {
      const c = e.target.closest('.cell-clamp');
      if (!c) return;
      if (e.type === 'keydown' && e.key !== 'Enter' && e.key !== ' ') return;
      e.preventDefault();
      c.classList.toggle('is-open');
      c.title = c.classList.contains('is-open') ? 'Click to collapse' : 'Click to show all';
    };
    tbody.addEventListener('click', toggle);
    tbody.addEventListener('keydown', toggle);
    d.rows.forEach(r => {
      const tr = tbody.insertRow();
      r.forEach(v => {
        const td = tr.insertCell();
        if (v.length > 90) {
          // long text (job descriptions...) is clamped to 3 lines; click to expand
          td.className = 'is-long';
          const clamp = document.createElement('div');
          clamp.className = 'cell-clamp';
          clamp.textContent = v;
          clamp.tabIndex = 0;
          clamp.title = 'Click to show all';
          td.appendChild(clamp);
        } else {
          td.textContent = v;
        }
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
    if (sortCol !== null) { qs.set('sort', sortCol); qs.set('dir', sortDesc ? 'desc' : 'asc'); }
    Object.keys(filters).forEach(i => qs.set('f' + i, filters[i]));
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

  sourceSel.addEventListener('change', () => {
    searchEl.value = ''; pageNo = 1; sortCol = null; sortDesc = false; filters = {}; headerKey = '';
    load();
  });
  searchEl.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(() => { pageNo = 1; load(); }, 250); });
  prevBtn.addEventListener('click', () => { if (pageNo > 1) { pageNo--; load(); } });
  nextBtn.addEventListener('click', () => { if (pageNo < lastPages) { pageNo++; load(); } });

  load();
})();

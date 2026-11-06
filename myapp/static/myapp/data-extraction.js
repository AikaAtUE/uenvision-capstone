/* Data > Data Extraction: the Single / Multiple search switch, the search count, the
   Automation fields, and the collapsible sections (their open / closed state is remembered
   in this browser). The page works without this file: every field is then simply shown. */
(function () {
  'use strict';
  const form = document.getElementById('extraction-form');
  if (!form) return;

  // ---- Single / Multiple search ----
  const panels = form.querySelectorAll('.dx-mode');
  const scrapeMeta = document.getElementById('scrape-meta');
  function mode() {
    const on = form.querySelector('input[name="search_mode"]:checked');
    return on ? on.value : 'single';
  }
  function showMode() {
    const m = mode();
    panels.forEach((p) => { p.hidden = p.dataset.mode !== m; });
  }
  form.querySelectorAll('input[name="search_mode"]').forEach((r) => r.addEventListener('change', () => { showMode(); updateMeta(); }));
  showMode();

  // ---- How many searches the multiple list has ----
  const extra = document.getElementById('extra-searches');
  const count = document.getElementById('search-count');
  const locked = count ? parseInt(count.dataset.locked, 10) || 0 : 0;
  const lockedTerms = new Set(Array.from(form.querySelectorAll('.dx-locked .dx-term')).map((el) => el.textContent.trim().toLowerCase()));
  function extraTerms() {
    const seen = new Set();
    return (extra ? extra.value : '').split(/\r?\n/).map((l) => l.trim().replace(/\s+/g, ' ')).filter((l) => {
      const k = l.toLowerCase();
      if (!l || lockedTerms.has(k) || seen.has(k)) return false;
      seen.add(k);
      return true;
    });
  }
  function updateCount() {
    if (!count) return;
    const n = extraTerms().length;
    count.textContent = (locked + n) + ' searches in all: ' + locked + ' from CHED and ' + n + ' added.';
  }
  function updateMeta() {
    if (!scrapeMeta) return;
    const srcs = Array.from(form.querySelectorAll('input[name="sources"]:checked'))
      .map((c) => c.closest('label').querySelector('strong').textContent);
    scrapeMeta.textContent = (srcs.length ? srcs.join(' + ') : 'No source') + ' · ' +
      (mode() === 'multiple' ? 'Multiple search (' + (locked + extraTerms().length) + ' searches)' : 'Single search');
  }
  if (extra) extra.addEventListener('input', () => { updateCount(); updateMeta(); });
  form.querySelectorAll('input[name="sources"]').forEach((c) => c.addEventListener('change', updateMeta));
  updateCount();
  updateMeta();

  // ---- Automation: grey out what doesn't apply ----
  const enabled = document.getElementById('auto-enabled');
  const days = form.querySelector('input[name="auto_every_days"]');
  const weekdays = form.querySelector('.dx-weekdays');
  function updateAuto() {
    const freq = (form.querySelector('input[name="auto_frequency"]:checked') || {}).value;
    if (days) days.disabled = freq === 'weekdays';
    if (weekdays) weekdays.classList.toggle('is-off', freq !== 'weekdays');
    form.querySelectorAll('.dx-auto-fields').forEach((el) => el.classList.toggle('is-off', enabled && !enabled.checked));
  }
  form.querySelectorAll('input[name="auto_frequency"]').forEach((r) => r.addEventListener('change', updateAuto));
  if (weekdays) weekdays.addEventListener('change', () => {
    const r = form.querySelector('input[name="auto_frequency"][value="weekdays"]');
    if (r && !r.checked) { r.checked = true; updateAuto(); }
  });
  if (enabled) enabled.addEventListener('change', updateAuto);
  updateAuto();

  // ---- Unsaved changes: say so, and ask before leaving the page ----
  const bar = document.getElementById('dx-unsaved');
  let dirty = false, submitting = false;
  function markDirty(e) {
    if (e.target.form !== form) return;            // the api_keys.txt textarea belongs to its own form
    dirty = true;
    if (bar) bar.hidden = false;
  }
  form.addEventListener('input', markDirty);
  form.addEventListener('change', markDirty);
  form.addEventListener('submit', () => { submitting = true; });
  window.addEventListener('beforeunload', (e) => {
    if (dirty && !submitting) { e.preventDefault(); e.returnValue = ''; }
  });

  // ---- Collapsible sections: remember open / closed, open one that has a problem ----
  const KEY = 'ue_dx_open';
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem(KEY) || 'null'); } catch (e) { saved = null; }
  const sections = form.querySelectorAll('details.dx-section');
  const hashTarget = location.hash ? document.getElementById(location.hash.slice(1)) : null;
  sections.forEach((d) => {
    if (saved && typeof saved[d.dataset.key] === 'boolean' && !d.hasAttribute('data-keep')) d.open = saved[d.dataset.key];
    if (d === hashTarget) d.open = true;
    d.addEventListener('toggle', () => {
      const state = {};
      sections.forEach((x) => { state[x.dataset.key] = x.open; });
      try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) { /* private mode: not remembered */ }
    });
  });
  if (hashTarget && hashTarget.scrollIntoView) hashTarget.scrollIntoView();
  // A field the browser rejects can't be shown inside a closed section, so open it first.
  form.addEventListener('invalid', (e) => {
    const d = e.target.closest('details');
    if (d && !d.open) d.open = true;
  }, true);
})();

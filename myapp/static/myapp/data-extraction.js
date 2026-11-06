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
    if (days) days.closest('label').classList.toggle('is-off', freq === 'weekdays');   // never disabled: a disabled box isn't sent
    if (weekdays) weekdays.classList.toggle('is-off', freq !== 'weekdays');
    form.querySelectorAll('.dx-auto-fields').forEach((el) => el.classList.toggle('is-off', enabled && !enabled.checked));
  }
  form.querySelectorAll('input[name="auto_frequency"]').forEach((r) => r.addEventListener('change', updateAuto));
  if (days) days.addEventListener('focus', () => {            // typing a number of days means "every N days"
    const r = form.querySelector('input[name="auto_frequency"][value="days"]');
    if (r && !r.checked) { r.checked = true; updateAuto(); schedule(150); }
  });
  if (weekdays) weekdays.addEventListener('change', () => {
    const r = form.querySelector('input[name="auto_frequency"][value="weekdays"]');
    if (r && !r.checked) { r.checked = true; updateAuto(); }
  });
  if (enabled) enabled.addEventListener('change', updateAuto);
  updateAuto();

  // ---- Automatic saving ----
  // Every change is sent to the server (the whole form, action=autosave) a moment after you stop
  // typing, or right away for ticks and switches. Each part (pipeline settings, ghost jobs,
  // automation) is saved on its own, so a mistake in one is reported without losing the others.
  const status = document.getElementById('dx-save-status');
  const csrf = (form.querySelector('input[name=csrfmiddlewaretoken]') || {}).value || '';
  let timer = null, inFlight = false, again = false, pending = false;

  function setStatus(state, text) {
    if (!status) return;
    status.hidden = false;
    status.dataset.state = state;
    status.textContent = text;
  }
  function setText(id, text) { const el = document.getElementById(id); if (el) el.textContent = text; }
  function setHtml(id, html) { const el = document.getElementById(id); if (el && typeof html === 'string') el.innerHTML = html; }

  async function save() {
    if (inFlight) { again = true; return; }
    inFlight = true; pending = false;
    setStatus('saving', 'Saving…');
    const body = new FormData(form);
    body.set('action', 'autosave');
    try {
      const r = await fetch(form.getAttribute('action'), { method: 'POST', body: body, credentials: 'same-origin',
        headers: { 'X-Requested-With': 'fetch', 'X-CSRFToken': csrf } });
      if (r.status === 403) throw new Error('your session ended; reload the page and log in again');
      if (!r.ok) throw new Error('the server answered ' + r.status);
      const d = await r.json();
      if (d.meta) {
        setText('skills-meta', d.meta.skills);
        setText('ghost-meta', d.meta.ghost);
        const am = document.getElementById('auto-meta');
        if (am) {
          while (am.firstChild) am.removeChild(am.firstChild);
          if (d.meta.auto_on) {
            const on = document.createElement('span'); on.className = 'dx-on'; on.textContent = 'On';
            am.appendChild(on); am.appendChild(document.createTextNode(' · ' + d.meta.auto));
          } else am.textContent = 'Off';
        }
      }
      setHtml('ghost-marked', d.ghost_html);
      setHtml('auto-status', d.auto_html);
      const errs = Object.values(d.errors || {});
      if (errs.length) setStatus('error', 'Not saved: ' + errs.join(' '));
      else setStatus('saved', 'All changes saved');
    } catch (e) {
      setStatus('error', 'Couldn’t save: ' + (e.message || 'no connection') + '. Your changes are still on this page.');
      pending = true;
    } finally {
      inFlight = false;
      if (again) { again = false; save(); }
    }
  }
  function schedule(delay) {
    pending = true;
    clearTimeout(timer);
    timer = setTimeout(save, delay);
  }
  form.addEventListener('input', (e) => {
    if (e.target.form !== form) return;                         // api_keys.txt has its own saving
    if (e.target.matches('input[type=text], input[type=number], input[type=time], textarea')) schedule(800);
  });
  form.addEventListener('change', (e) => {
    if (e.target.form !== form) return;
    schedule(e.target.matches('input[type=checkbox], input[type=radio], select') ? 150 : 300);
  });
  // Enter in a field: save now instead of reloading the page. Run now still submits normally.
  form.addEventListener('submit', (e) => {
    const action = e.submitter ? e.submitter.value : 'save';
    if (action !== 'run') { e.preventDefault(); clearTimeout(timer); save(); }
  });
  window.addEventListener('beforeunload', (e) => {
    if (pending || inFlight) { e.preventDefault(); e.returnValue = ''; }
  });

  // api_keys.txt (its own file and form)
  const keys = document.getElementById('keys-text');
  const keysForm = document.getElementById('api-keys-form');
  let keysTimer = null;
  async function saveKeys() {
    setStatus('saving', 'Saving api_keys.txt…');
    const body = new FormData();
    body.set('keys', keys.value);
    try {
      const r = await fetch(keysForm.getAttribute('action'), { method: 'POST', body: body, credentials: 'same-origin',
        headers: { 'X-Requested-With': 'fetch', 'X-CSRFToken': csrf } });
      const d = await r.json();
      if (!d.ok) throw new Error(d.error || 'not saved');
      setText('key-count', d.count + ' key' + (d.count === 1 ? '' : 's'));
      setStatus('saved', 'api_keys.txt saved (' + d.count + ' key' + (d.count === 1 ? '' : 's') + ')');
      save();                                                    // refreshes the key count in the header
    } catch (e) {
      setStatus('error', 'Couldn’t save api_keys.txt: ' + (e.message || 'no connection'));
    }
  }
  if (keys && keysForm) {
    keys.addEventListener('input', () => { clearTimeout(keysTimer); keysTimer = setTimeout(saveKeys, 1200); });
    keys.addEventListener('change', () => { clearTimeout(keysTimer); saveKeys(); });
  }

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

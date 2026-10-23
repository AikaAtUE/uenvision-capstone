/* Scrape Data / Extract Skills: live status + log for the background run. All dynamic text goes in via textContent. */
(function () {
  'use strict';
  const panel = document.getElementById('run-panel');
  if (!panel) return;
  const isConsole = panel.dataset.kind === 'any';   // the Console page shows every run and never hides

  const badge = document.getElementById('run-badge');
  const meta = document.getElementById('run-meta');
  const stepsEl = document.getElementById('run-steps');
  const logEl = document.getElementById('run-log');
  const stopForm = document.getElementById('stop-form');
  const runBtn = document.getElementById('run-btn');
  const runHint = document.getElementById('run-hint');
  const statusUrl = panel.dataset.statusUrl;
  const LABEL = { running: 'Running', done: 'Finished', failed: 'Failed', stopped: 'Stopped', interrupted: 'Interrupted', idle: 'Idle' };

  let prev = panel.dataset.status;
  let delay = 2000;

  function fmt(iso) {
    const d = new Date(iso);
    return isNaN(d) ? '' : d.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
  }

  // Lines that look like errors are shown in red, along with the indented lines that follow
  // them (tracebacks). Text only goes in through textContent.
  const ERR = /\b(ERROR|CRITICAL|FATAL|FAILED|STOP)\b|Traceback|Error:|Exception|\[WARN\]/;
  function renderLog(text) {
    while (logEl.firstChild) logEl.removeChild(logEl.firstChild);
    let inErr = false;
    text.split('\n').forEach((line, i, all) => {
      if (ERR.test(line)) inErr = true;
      else if (!/^\s/.test(line)) inErr = false;
      const span = document.createElement('span');
      if (inErr) span.className = 'log-err';
      span.textContent = line + (i < all.length - 1 ? '\n' : '');
      logEl.appendChild(span);
    });
  }

  function render(d) {
    const mine = isConsole || !d.kind || d.kind === panel.dataset.kind;
    panel.hidden = (d.status === 'idle' && !isConsole) || !mine;
    panel.dataset.status = d.status;
    badge.textContent = LABEL[d.status] || d.status;
    badge.dataset.s = d.status;

    const parts = [];
    if (d.source) parts.push(d.source.charAt(0).toUpperCase() + d.source.slice(1));
    if (d.started_at) parts.push('started ' + fmt(d.started_at));
    if (d.finished_at && d.status !== 'running') parts.push('ended ' + fmt(d.finished_at));
    meta.textContent = parts.join(' · ');

    while (stepsEl.firstChild) stepsEl.removeChild(stepsEl.firstChild);
    (d.steps || []).forEach((s, i) => {
      const li = document.createElement('li');
      li.dataset.s = s.status;
      li.textContent = (i + 1) + '. ' + s.label + (s.status === 'done' ? ' ✓' : s.status === 'failed' ? ' ✗' : '');
      stepsEl.appendChild(li);
    });

    // Everything (output, progress, warnings, errors) goes inside the dark box.
    let text = d.log || '';
    if (d.error && text.indexOf(d.error) === -1) text += (text ? '\n' : '') + 'ERROR: ' + d.error;
    if (!text) text = 'Waiting for output…';
    const atBottom = logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight < 40;
    if (logEl.dataset.raw !== text) {
      logEl.dataset.raw = text;
      renderLog(text);
      if (atBottom) logEl.scrollTop = logEl.scrollHeight;
    }

    const running = d.status === 'running';
    stopForm.hidden = !(running && mine);
    if (runBtn) runBtn.disabled = running;
    if (runHint) runHint.textContent = running ? 'A run is in progress.' : 'Runs in the background — you can leave this page.';
  }

  function poll() {
    fetch(statusUrl, { headers: { 'Accept': 'application/json' }, credentials: 'same-origin' })
      .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(d => {
        delay = 2000;
        render(d);
        if (!isConsole && prev === 'running' && d.status !== 'running') {
          // finished while this page was open: refresh the "what's in data/" table
          setTimeout(() => window.location.reload(), 800);
          return;
        }
        prev = d.status;
        if (d.status === 'running' || isConsole) setTimeout(poll, d.status === 'running' ? delay : 5000);
      })
      .catch(() => { delay = Math.min(delay * 2, 15000); if (prev === 'running' || isConsole) setTimeout(poll, delay); });
  }

  if (prev !== 'idle' || isConsole) poll();

  document.querySelectorAll('time.js-time').forEach(t => {
    const d = new Date(t.getAttribute('datetime'));
    if (!isNaN(d)) t.textContent = d.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
  });

  // A tiny guard so a double-click on Run can't submit twice.
  const form = document.getElementById('scrape-form');
  if (form) form.addEventListener('submit', () => { if (runBtn) setTimeout(() => { runBtn.disabled = true; }, 0); });
})();

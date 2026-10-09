/* Scrape Data: live status + log for the background run. All dynamic text goes in via textContent. */
(function () {
  'use strict';
  const panel = document.getElementById('run-panel');
  if (!panel) return;

  const badge = document.getElementById('run-badge');
  const meta = document.getElementById('run-meta');
  const stepsEl = document.getElementById('run-steps');
  const errEl = document.getElementById('run-error');
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

  function render(d) {
    panel.hidden = d.status === 'idle';
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

    errEl.textContent = d.error || '';

    const atBottom = logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight < 40;
    if (logEl.textContent !== d.log) {
      logEl.textContent = d.log;
      if (atBottom) logEl.scrollTop = logEl.scrollHeight;
    }

    const running = d.status === 'running';
    stopForm.hidden = !running;
    if (runBtn) runBtn.disabled = running;
    if (runHint) runHint.textContent = running ? 'A run is in progress.' : 'Runs in the background — you can leave this page.';
  }

  function poll() {
    fetch(statusUrl, { headers: { 'Accept': 'application/json' }, credentials: 'same-origin' })
      .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(d => {
        delay = 2000;
        render(d);
        if (prev === 'running' && d.status !== 'running') {
          // finished while this page was open: refresh the "what's in data/" table
          setTimeout(() => window.location.reload(), 800);
          return;
        }
        prev = d.status;
        if (d.status === 'running') setTimeout(poll, delay);
      })
      .catch(() => { delay = Math.min(delay * 2, 15000); if (prev === 'running') setTimeout(poll, delay); });
  }

  if (prev !== 'idle') poll();

  document.querySelectorAll('time.js-time').forEach(t => {
    const d = new Date(t.getAttribute('datetime'));
    if (!isNaN(d)) t.textContent = d.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
  });

  // A tiny guard so a double-click on Run can't submit twice.
  const form = document.getElementById('scrape-form');
  if (form) form.addEventListener('submit', () => { if (runBtn) setTimeout(() => { runBtn.disabled = true; }, 0); });
})();

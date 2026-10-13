/* Dashboard: top-skills bar chart + top-skills-per-month line chart, drawn from /dashboard/skills/.
   All dynamic text goes in through textContent. */
(function () {
  'use strict';
  const panel = document.getElementById('skills-panel');
  if (!panel) return;

  const $ = id => document.getElementById(id);
  const ctl = { kind: $('ctl-kind'), top: $('ctl-top'), source: $('ctl-source'), level: $('ctl-level'), months: $('ctl-months') };
  const errEl = $('skills-error');
  const SVGNS = 'http://www.w3.org/2000/svg';
  const COLORS = ['#c8202f', '#16233f', '#2a9d8f', '#e9a23b', '#6a4c93', '#3d85c6', '#b5651d', '#7a8b2e', '#d6609a', '#5b6b7d'];
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

  let data = null;
  const hidden = new Set();       // skills toggled off in the line chart legend
  let timer = null, reqId = 0, filtersBuilt = false;

  const monthLabel = m => MONTHS[+m.slice(5) - 1] + ' ' + m.slice(0, 4);
  const colorOf = i => COLORS[i % COLORS.length];
  const dashOf = i => (Math.floor(i / COLORS.length) % 2 ? '6 4' : null);

  function el(tag, attrs, text) {
    const e = document.createElementNS(SVGNS, tag);
    for (const k in attrs || {}) e.setAttribute(k, attrs[k]);
    if (text != null) e.textContent = text;
    return e;
  }
  function clear(n) { while (n.firstChild) n.removeChild(n.firstChild); }

  /* ---------------- stat cards ---------------- */
  function setStats(d) {
    const st = d.stats;
    const kindWord = d.kind === 'soft' ? 'soft' : 'hard';
    $('stat-total').textContent = st.postings.toLocaleString();
    $('stat-total-note').textContent = 'Postings after filtering';
    $('stat-unique').textContent = st.unique_skills.toLocaleString();
    $('stat-unique-note').textContent = 'Distinct ' + kindWord + ' skills';
    $('stat-topskill').textContent = st.top_skill || '—';
    $('stat-topskill-note').textContent = st.top_skill ? 'Appears in ' + st.top_skill_pct + '% of postings' : 'No skills found';
    $('stat-alignment').textContent = '—';
    $('stat-alignment-note').textContent = 'Available once survey data is collected';
    $('stat-gaps').textContent = '—';
    $('stat-gaps-note').textContent = 'Available once survey data is collected';
    const up = $('last-analyzed');
    if (up) {
      const t = d.updated ? new Date(d.updated) : null;
      up.textContent = t && !isNaN(t) ? t.toLocaleDateString([], { dateStyle: 'medium' }) : '—';
    }
  }

  /* ---------------- bar chart ---------------- */
  function drawBars(d) {
    const box = $('bar-chart');
    clear(box);
    $('bar-legend').textContent = 'Number of job postings that mention the skill (' + (d.kind === 'soft' ? 'soft' : 'hard') + ' skills)';
    if (!d.bars.length) {
      const p = document.createElement('p'); p.className = 'empty-note'; p.textContent = 'No skills match these filters.'; box.appendChild(p);
      return;
    }
    const max = d.bars[0].count || 1;
    d.bars.forEach(b => {
      const row = document.createElement('div'); row.className = 'bar-row';
      const label = document.createElement('span'); label.className = 'bar-label'; label.textContent = b.skill; label.title = b.skill;
      const track = document.createElement('span'); track.className = 'bar-track';
      const fill = document.createElement('span'); fill.className = 'bar-fill'; fill.style.width = (b.count / max * 100).toFixed(1) + '%';
      track.appendChild(fill);
      const val = document.createElement('span'); val.className = 'bar-value';
      val.textContent = b.count + ' ';
      const sm = document.createElement('small'); sm.textContent = '(' + b.pct + '%)'; val.appendChild(sm);
      row.append(label, track, val);
      box.appendChild(row);
    });
  }

  /* ---------------- line chart ---------------- */
  // Four whole-number gridline steps (1, 2, 5, 10, 20, 50 ...) that cover the largest value.
  function niceMax(v) {
    const raw = Math.max(1, v) / 4;
    const pow = Math.pow(10, Math.floor(Math.log10(raw)));
    for (const m of [1, 2, 5, 10]) if (m * pow >= raw) return m * pow * 4;
    return 40 * pow;
  }

  function drawTrend(d) {
    const svg = $('trend-svg'), key = $('trend-key'), note = $('trend-note'), tip = $('trend-tip');
    clear(svg); clear(key); tip.hidden = true;
    const months = d.months, series = d.series;
    if (!months.length || !series.length) {
      svg.setAttribute('viewBox', '0 0 800 80');
      svg.appendChild(el('text', { x: 4, y: 40 }, 'No dated postings match these filters, so there is no trend to show.'));
      note.textContent = '';
      return;
    }
    const W = 800, H = 340, L = 44, R = 14, T = 14, B = 34;
    svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
    const pw = W - L - R, ph = H - T - B;
    const visible = series.map((s, i) => ({ s, i })).filter(o => !hidden.has(o.s.skill));
    const maxVal = niceMax(Math.max(1, ...visible.map(o => Math.max(...o.s.counts))));
    const X = i => L + (months.length === 1 ? pw / 2 : i * pw / (months.length - 1));
    const Y = v => T + ph - v / maxVal * ph;

    for (let g = 0; g <= 4; g++) {
      const v = maxVal / 4 * g, y = Y(v);
      svg.appendChild(el('line', { class: 'grid', x1: L, x2: W - R, y1: y, y2: y }));
      svg.appendChild(el('text', { x: L - 8, y: y + 4, 'text-anchor': 'end' }, Number.isInteger(v) ? v : v.toFixed(1)));
    }
    const ticks = Math.min(months.length, 8);
    for (let t = 0; t < ticks; t++) {
      const i = ticks === 1 ? 0 : Math.round(t * (months.length - 1) / (ticks - 1));
      svg.appendChild(el('text', { x: X(i), y: H - 10, 'text-anchor': t === 0 ? 'start' : t === ticks - 1 ? 'end' : 'middle' }, monthLabel(months[i])));
    }
    const lines = [];
    visible.forEach(o => {
      const pts = o.s.counts.map((c, i) => X(i).toFixed(1) + ',' + Y(c).toFixed(1)).join(' ');
      const a = { class: 'line', points: pts, stroke: colorOf(o.i) };
      const dash = dashOf(o.i); if (dash) a['stroke-dasharray'] = dash;
      const pl = el('polyline', a); svg.appendChild(pl); lines.push({ pl, name: o.s.skill });
      if (months.length <= 36) o.s.counts.forEach((c, i) => svg.appendChild(el('circle', { cx: X(i), cy: Y(c), r: 2.6, fill: colorOf(o.i) })));
    });
    const guide = el('line', { class: 'guide', y1: T, y2: T + ph, x1: 0, x2: 0, visibility: 'hidden' });
    svg.appendChild(guide);
    const hit = el('rect', { x: L, y: T, width: pw, height: ph, fill: 'transparent' });
    svg.appendChild(hit);

    function showTip(ev) {
      const r = svg.getBoundingClientRect();
      const cx = (ev.clientX - r.left) / r.width * W;
      const i = Math.max(0, Math.min(months.length - 1, Math.round((cx - L) / pw * (months.length - 1))));
      guide.setAttribute('x1', X(i)); guide.setAttribute('x2', X(i)); guide.setAttribute('visibility', 'visible');
      clear(tip);
      const h = document.createElement('strong'); h.textContent = monthLabel(months[i]) + ' · ' + d.postings_per_month[i] + ' postings'; tip.appendChild(h);
      visible.slice().sort((a, b) => b.s.counts[i] - a.s.counts[i]).forEach(o => {
        const row = document.createElement('div');
        const k = document.createElement('span'); k.className = 'k';
        const dot = document.createElement('i'); dot.style.background = colorOf(o.i);
        const nm = document.createElement('span'); nm.textContent = o.s.skill;
        k.append(dot, nm);
        const v = document.createElement('b'); v.textContent = o.s.counts[i];
        row.append(k, v); tip.appendChild(row);
      });
      tip.hidden = false;
      const wrap = $('trend-wrap').getBoundingClientRect();
      let left = ev.clientX - wrap.left + 14;
      if (left + tip.offsetWidth > wrap.width) left = ev.clientX - wrap.left - tip.offsetWidth - 14;
      tip.style.left = Math.max(0, left) + 'px';
      tip.style.top = Math.max(0, Math.min(ev.clientY - wrap.top - 20, wrap.height - tip.offsetHeight)) + 'px';
    }
    hit.addEventListener('pointermove', showTip);
    hit.addEventListener('pointerleave', () => { tip.hidden = true; guide.setAttribute('visibility', 'hidden'); });

    series.forEach((s, i) => {
      const b = document.createElement('button'); b.type = 'button';
      b.className = hidden.has(s.skill) ? 'is-off' : '';
      const sw = document.createElement('i'); sw.style.background = colorOf(i);
      b.append(sw, document.createTextNode(s.skill));
      b.title = 'Click to show or hide';
      b.addEventListener('click', () => { hidden.has(s.skill) ? hidden.delete(s.skill) : hidden.add(s.skill); drawTrend(d); });
      b.addEventListener('mouseenter', () => lines.forEach(l => l.pl.classList.toggle('is-dim', l.name !== s.skill)));
      b.addEventListener('mouseleave', () => lines.forEach(l => l.pl.classList.remove('is-dim')));
      key.appendChild(b);
    });
    const undated = d.stats.undated;
    note.textContent = 'A skill is counted once per posting, by the month the posting was created (the date column).'
      + (undated ? ' ' + undated + ' posting' + (undated === 1 ? ' has' : 's have') + ' no date and ' + (undated === 1 ? 'is' : 'are') + ' left out of this chart.' : '');
  }

  /* ---------------- loading ---------------- */
  function buildFilters(d) {
    const fill = (sel, items, first) => {
      const keep = sel.value; clear(sel);
      const o0 = document.createElement('option'); o0.value = ''; o0.textContent = first; sel.appendChild(o0);
      items.forEach(v => { const o = document.createElement('option'); o.value = v; o.textContent = v; sel.appendChild(o); });
      sel.value = items.includes(keep) ? keep : '';
    };
    fill(ctl.source, d.sources.map(s => s), 'All sources');
    Array.from(ctl.source.options).forEach(o => { if (o.value) o.textContent = o.value.charAt(0).toUpperCase() + o.value.slice(1); });
    fill(ctl.level, d.levels, 'All levels');
    filtersBuilt = true;
  }

  function showEmpty(msg) {
    ['stat-total', 'stat-unique', 'stat-topskill', 'stat-alignment', 'stat-gaps'].forEach(i => { $(i).textContent = '—'; });
    const box = $('bar-chart'); clear(box);
    const p = document.createElement('p'); p.className = 'empty-note'; p.textContent = msg; box.appendChild(p);
    const svg = $('trend-svg'); clear(svg); svg.setAttribute('viewBox', '0 0 800 60'); svg.appendChild(el('text', { x: 4, y: 30 }, msg));
    clear($('trend-key'));
  }

  function load() {
    let top = parseInt(ctl.top.value, 10);
    if (!(top >= 1)) return;               // user is mid-typing
    top = Math.min(top, 30);
    const q = new URLSearchParams({ kind: ctl.kind.value, top: top, source: ctl.source.value, level: ctl.level.value, months: ctl.months.value });
    const my = ++reqId;
    fetch(panel.dataset.url + '?' + q, { headers: { Accept: 'application/json' }, credentials: 'same-origin' })
      .then(r => r.json().then(j => ({ ok: r.ok, j })))
      .then(({ ok, j }) => {
        if (my !== reqId) return;
        errEl.textContent = '';
        if (!ok || !j.ok) { errEl.textContent = j.error || 'Could not load the dashboard data.'; return; }
        if (!j.exists) { showEmpty('No extracted skills yet. An administrator can create them on Data → Extract Skills.'); return; }
        data = j;
        if (!filtersBuilt) buildFilters(j);
        setStats(j); drawBars(j); drawTrend(j);
      })
      .catch(() => { if (my === reqId) errEl.textContent = 'Could not reach the server. Try again.'; });
  }

  const later = () => { clearTimeout(timer); timer = setTimeout(load, 250); };
  ctl.top.addEventListener('input', later);
  ctl.top.addEventListener('change', () => {
    let v = parseInt(ctl.top.value, 10);
    if (!(v >= 1)) v = 10;
    ctl.top.value = Math.min(v, 30); load();
  });
  [ctl.kind, ctl.source, ctl.level, ctl.months].forEach(c => c.addEventListener('change', () => { hidden.clear(); load(); }));

  // The period picker only matters for the trend chart.
  const monthsWrap = $('ctl-months-wrap');
  document.querySelectorAll('.tab').forEach(t => t.addEventListener('click', () => { monthsWrap.hidden = t.dataset.tab !== 'skill-trends'; }));

  load();
})();

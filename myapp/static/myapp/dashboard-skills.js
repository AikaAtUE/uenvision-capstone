/* Dashboard: top-skills bar chart + top-skills-per-month line chart + skill gap
   analysis, all drawn from one /dashboard/skills/ response. All dynamic text goes
   in through textContent. */
(function () {
  'use strict';
  const panel = document.getElementById('skills-panel');
  if (!panel) return;

  const $ = id => document.getElementById(id);
  const ctl = { kind: $('ctl-kind'), top: $('ctl-top'), source: $('ctl-source'), level: $('ctl-level'), months: $('ctl-months'), program: $('ctl-program') };
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

  /* ---------------- "According to" source lines ---------------- */
  const cap = s => s.charAt(0).toUpperCase() + s.slice(1);
  function sourceName(d) {
    const picked = ctl.source.value ? [ctl.source.value] : (d.sources || []);
    return picked.length ? picked.map(cap).join(', ') : 'online job boards';
  }
  const PROGRAM_NAMES = { BSCS: 'Computer Science', BSIT: 'Information Technology' };
  function postingsText(n, d) {
    const prog = PROGRAM_NAMES[ctl.program.value];
    return n.toLocaleString() + (prog ? ' ' + prog : '') + ' job posting' + (n === 1 ? '' : 's') + ' from ' + sourceName(d) +
      (ctl.level.value ? ' (' + ctl.level.value + ' level)' : '');
  }
  function setSource(id, text) { const e = $(id); if (e) e.textContent = text; }
  function setSources(d) {
    const extracted = d.kind === 'soft' ? 'soft skills' : 'hard skills';
    const months = d.months || [];
    const period = months.length ? ', ' + monthLabel(months[0]) + ' to ' + monthLabel(months[months.length - 1]) : '';
    setSource('src-top', 'According to ' + postingsText(d.stats.postings, d) + ', with ' + extracted +
      ' extracted from each posting.');
    setSource('src-trend', months.length
      ? 'According to ' + postingsText(d.postings_per_month.reduce((a, b) => a + b, 0), d) + period + '.'
      : '');
    const gap = d.gap;
    if (gap && gap.exists && gap.has_survey_data) {
      const byType = gap.survey_responses_by_type || {};
      setSource('src-gap', 'According to ' + postingsText(gap.postings_considered, d) + ' and ' +
        gap.survey_responses + ' curriculum survey answer' + (gap.survey_responses === 1 ? '' : 's') + ' (' +
        ['student', 'alumni', 'professor'].map(t => (byType[t] || 0) + ' ' + t).join(', ') + ')' +
        (ctl.program.value ? ' from ' + ctl.program.value : '') + '.');
    } else {
      setSource('src-gap', '');
    }
  }

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

    const gap = d.gap;
    if (gap && gap.exists && gap.has_survey_data) {
      $('stat-alignment').textContent = gap.alignment_score + '%';
      $('stat-alignment-note').textContent = 'Cosine similarity: ' + gap.alignment_cosine.toFixed(2) + ' (hard skills)';
      $('stat-gaps').textContent = String(gap.under_taught.length);
      $('stat-gaps-note').textContent = gap.top_gap ? 'Top gap: ' + gap.top_gap : 'No high-priority gaps found';
    } else {
      $('stat-alignment').textContent = '—';
      $('stat-alignment-note').textContent = 'Available once survey data is collected';
      $('stat-gaps').textContent = '—';
      $('stat-gaps-note').textContent = 'Available once survey data is collected';
    }
    const up = $('last-analyzed');
    if (up) {
      const t = d.updated ? new Date(d.updated) : null;
      up.textContent = t && !isNaN(t) ? t.toLocaleDateString([], { dateStyle: 'medium' }) : '—';
    }
  }

  /* ---------------- bar chart ---------------- */
  // Each bar is split by job board; Trabajo and Kalibrr keep the same colour on every filter.
  const SOURCE_COLORS = { trabajo: '#c8202f', kalibrr: '#16233f' };
  const sourceLabel = s => (s ? cap(s) : 'Other');
  function sourceColor(s, i) { return SOURCE_COLORS[s] || COLORS[(i + 2) % COLORS.length]; }

  function drawSourceKey(sources) {
    const key = $('bar-source-key');
    if (!key) return;
    clear(key);
    key.hidden = !sources.length;
    const dot = $('bar-legend').previousElementSibling;   // the single-colour dot doesn't apply to split bars
    if (dot && dot.classList.contains('dot')) dot.style.display = sources.length ? 'none' : '';
    sources.forEach((s, i) => {
      const item = document.createElement('span'); item.className = 'source-key-item';
      const sw = document.createElement('i'); sw.style.background = sourceColor(s, i);
      item.append(sw, document.createTextNode(sourceLabel(s)));
      key.appendChild(item);
    });
  }

  function drawBars(d) {
    const box = $('bar-chart');
    clear(box);
    $('bar-legend').textContent = 'Number of job postings that mention the skill (' + (d.kind === 'soft' ? 'soft' : 'hard') + ' skills)';
    const sources = d.bar_sources || [];
    drawSourceKey(d.bars.length ? sources : []);
    if (!d.bars.length) {
      const p = document.createElement('p'); p.className = 'empty-note'; p.textContent = 'No skills match these filters.'; box.appendChild(p);
      return;
    }
    const max = d.bars[0].count || 1;
    d.bars.forEach(b => {
      const split = b.by_source || [];
      const row = document.createElement('div'); row.className = 'bar-row bar-row--split';
      const label = document.createElement('span'); label.className = 'bar-label'; label.textContent = b.skill; label.title = b.skill;
      const track = document.createElement('span'); track.className = 'bar-track';
      const fill = document.createElement('span'); fill.className = 'bar-fill bar-fill--split'; fill.style.width = (b.count / max * 100).toFixed(1) + '%';
      split.forEach(part => {
        const seg = document.createElement('span'); seg.className = 'bar-seg';
        seg.style.width = (part.count / (b.count || 1) * 100).toFixed(2) + '%';
        seg.style.background = sourceColor(part.source, sources.indexOf(part.source));
        seg.title = sourceLabel(part.source) + ': ' + part.count;
        fill.appendChild(seg);
      });
      track.appendChild(fill);
      const val = document.createElement('span'); val.className = 'bar-value';
      val.textContent = b.count + ' ';
      const sm = document.createElement('small'); sm.textContent = '(' + b.pct + '%)'; val.appendChild(sm);
      const by = document.createElement('span'); by.className = 'bar-split';
      sources.forEach((s, i) => {
        const part = split.find(x => x.source === s);
        const item = document.createElement('span');
        const sw = document.createElement('i'); sw.style.background = sourceColor(s, i);
        item.append(sw, document.createTextNode(sourceLabel(s) + ' ' + (part ? part.count : 0)));
        by.appendChild(item);
      });
      row.title = b.skill + ': ' + b.count + ' posting' + (b.count === 1 ? '' : 's') +
        (split.length ? ' (' + split.map(x => sourceLabel(x.source) + ' ' + x.count).join(', ') + ')' : '');
      row.append(label, track, val);
      if (sources.length > 1) row.appendChild(by);
      box.appendChild(row);
    });
  }

  /* ---------------- skill gap analysis ---------------- */
  function gapRow(box, r) {
    const row = document.createElement('div'); row.className = 'bar-row';
    const label = document.createElement('span'); label.className = 'bar-label'; label.textContent = r.skill; label.title = r.skill;
    const track = document.createElement('span'); track.className = 'bar-track';
    const fill = document.createElement('span'); fill.className = 'bar-fill'; fill.style.width = Math.min(100, r.industry_pct) + '%';
    track.appendChild(fill);
    const val = document.createElement('span'); val.className = 'bar-value';
    val.textContent = r.industry_pct + '% demand';
    const sm = document.createElement('small'); sm.textContent = ' · ' + r.academic_pct + '% covered'; val.appendChild(sm);
    const parts = [r.industry_pct + '% of postings', r.academic_pct + '% depth-weighted coverage'];
    if (r.taught_depth_pct != null) parts.push('taught depth ' + r.taught_depth_pct + '%');
    if (r.learned_proficiency_pct != null) parts.push('learned proficiency ' + r.learned_proficiency_pct + '%');
    row.title = r.skill + ': ' + parts.join(', ');
    row.append(label, track, val);
    box.appendChild(row);
  }

  function skillList(items, fmt) {
    const ul = document.createElement('ul'); ul.className = 'gap-subj-list';
    if (!items.length) { const li = document.createElement('li'); li.className = 'muted'; li.textContent = '—'; ul.appendChild(li); }
    items.forEach(i => { const li = document.createElement('li'); li.textContent = fmt(i); ul.appendChild(li); });
    return ul;
  }

  function drawSubjects(gap) {
    const box = $('gap-by-subject'); clear(box);
    const rows = gap.by_subject || [];
    if (!rows.length) {
      const p = document.createElement('p'); p.className = 'empty-note';
      p.textContent = 'No subject has survey answers that match in-demand skills yet.'; box.appendChild(p);
      return;
    }
    const table = document.createElement('table'); table.className = 'gap-subj-table';
    const head = document.createElement('tr');
    ['Subject', 'Respondents', 'Alignment', 'In-demand skills covered (depth)', 'Under-taught skills that fit (share of postings)'].forEach(h => {
      const th = document.createElement('th'); th.textContent = h; head.appendChild(th);
    });
    const thead = document.createElement('thead'); thead.appendChild(head); table.appendChild(thead);
    const tbody = document.createElement('tbody');
    rows.forEach(r => {
      const tr = document.createElement('tr');
      const c1 = document.createElement('td');
      const strong = document.createElement('strong'); strong.textContent = r.code;
      const sm = document.createElement('small'); sm.textContent = r.name;
      c1.append(strong, document.createElement('br'), sm);
      const c2 = document.createElement('td'); c2.textContent = String(r.respondents);
      const c3 = document.createElement('td'); c3.textContent = r.alignment_pct == null ? '—' : r.alignment_pct + '%';
      const c4 = document.createElement('td');
      c4.appendChild(skillList(r.covered, i => i.skill + ' (' + i.depth_pct + '%)'));
      const c5 = document.createElement('td');
      c5.appendChild(skillList(r.could_add, i => i.skill + ' (' + i.industry_pct + '%)'));
      tr.append(c1, c2, c3, c4, c5); tbody.appendChild(tr);
    });
    table.appendChild(tbody); box.appendChild(table);
  }

  function drawGaps(d) {
    const gap = d.gap, note = $('gap-empty-note'), content = $('gap-content');
    if (!gap || !gap.exists) {
      note.hidden = false; note.textContent = 'Gap analysis isn’t available yet.'; content.hidden = true;
      return;
    }
    if (!gap.has_survey_data) {
      note.hidden = false;
      note.textContent = 'No curriculum survey submissions yet — once students, alumni, or professors fill out ' +
        'the Student / Alumni / Professor survey, this tab will compare what they report being taught against ' +
        'what the job market demands.';
      content.hidden = true;
      return;
    }
    note.hidden = true; content.hidden = false;
    const ut = $('gap-under-taught'), wc = $('gap-well-covered');
    clear(ut); clear(wc);
    if (!gap.under_taught.length) {
      const p = document.createElement('p'); p.className = 'empty-note';
      p.textContent = 'No high-priority gaps among the top skills shown — good alignment.'; ut.appendChild(p);
    } else {
      gap.under_taught.forEach(r => gapRow(ut, r));
    }
    if (!gap.well_covered.length) {
      const p = document.createElement('p'); p.className = 'empty-note';
      p.textContent = 'None of the top in-demand skills are reported as taught yet.'; wc.appendChild(p);
    } else {
      gap.well_covered.forEach(r => gapRow(wc, r));
    }
    const byType = gap.survey_responses_by_type || {};
    drawSubjects(gap);
    $('gap-note').textContent = gap.survey_responses + ' survey response(s) with tagged skills (' +
      ['student', 'alumni', 'professor'].map(t => (byType[t] || 0) + ' ' + t).join(', ') + ').';
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
    ['src-top', 'src-trend', 'src-gap'].forEach(i => setSource(i, ''));
    $('gap-empty-note').hidden = false; $('gap-empty-note').textContent = msg; $('gap-content').hidden = true;
  }

  function load() {
    let top = parseInt(ctl.top.value, 10);
    if (!(top >= 1)) return;               // user is mid-typing
    top = Math.min(top, 30);
    const q = new URLSearchParams({ kind: ctl.kind.value, top: top, source: ctl.source.value, level: ctl.level.value, months: ctl.months.value, program: ctl.program.value });
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
        setStats(j); drawBars(j); drawTrend(j); drawGaps(j); setSources(j);
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
  [ctl.kind, ctl.source, ctl.level, ctl.months, ctl.program].forEach(c => c.addEventListener('change', () => { hidden.clear(); load(); }));

  // The period picker only matters for the trend chart. The program picker narrows every
  // tab (job postings by the COMPUTER SCIENCE / INFORMATION TECHNOLOGY columns, and the
  // gap analysis's survey answers too).
  const monthsWrap = $('ctl-months-wrap');
  document.querySelectorAll('.tab').forEach(t => t.addEventListener('click', () => {
    monthsWrap.hidden = t.dataset.tab !== 'skill-trends';
  }));

  load();
})();

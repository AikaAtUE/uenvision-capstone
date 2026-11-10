/* Job Market page: fetches the numbers from job_market_data_view and draws the charts.
   Live: it fetches again every 5 minutes while the page is open (and when you come back
   to the tab), so postings added by a scrape + Extract Skills run show up on their own. */
(function () {
  var root = document.getElementById('jm');
  if (!root) return;
  var REFRESH_MS = 5 * 60 * 1000;
  var url = root.dataset.url;
  // Source tick boxes: the job boards are ticked by default, imported datasets (Djinni) are opt-in.
  var sourceBoxes = Array.prototype.slice.call(document.querySelectorAll('#jm-sources input[type=checkbox]'));
  function sourceQuery() {
    return sourceBoxes.filter(function (b) { return b.checked; })
      .map(function (b) { return 'source=' + encodeURIComponent(b.value); }).join('&');
  }
  var sinceSel = document.getElementById('jm-since');
  var lastFetch = 0;
  var busy = false;

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c];
    });
  }
  function num(n) { return Number(n).toLocaleString('en-US'); }
  function peso(n) { return 'PHP ' + num(Math.round(n)); }
  function monthLabel(ym) {
    var d = new Date(Number(ym.slice(0, 4)), Number(ym.slice(5, 7)) - 1, 1);
    return d.toLocaleDateString('en-US', {month: 'short', year: 'numeric'});
  }

  // ---- Charts -----------------------------------------------------------
  function quartersChart(rows) {
    var W = 760, H = 300, left = 44, right = 10, y0 = 24, base = 250;
    var max = Math.max.apply(null, rows.map(function (r) { return r.tech + r.nontech; }).concat([1]));
    var step = Math.pow(10, Math.floor(Math.log10(max)));
    var top = Math.ceil(max / step) * step;
    if (top / step <= 2) step = step / 2;
    var band = (W - left - right) / rows.length, bw = Math.max(6, Math.min(48, band * 0.62));
    var y = function (v) { return base - v / top * (base - y0); };
    var out = ['<svg viewBox="0 0 ' + W + ' ' + H + '" aria-hidden="true">'];
    for (var t = 0; t <= top + 1e-9; t += step) {
      out.push('<line class="jm-grid-line" x1="' + left + '" x2="' + (W - right) + '" y1="' + y(t) + '" y2="' + y(t) + '"/>');
      out.push('<text x="' + (left - 6) + '" y="' + (y(t) + 4) + '" text-anchor="end">' + num(t) + '</text>');
    }
    var every = rows.length > 16 ? Math.ceil(rows.length / 12) : 1;
    rows.forEach(function (r, i) {
      var x = left + i * band + (band - bw) / 2, total = r.tech + r.nontech;
      var label = r.label + (r.partial ? ' (so far)' : '');
      out.push('<rect class="jm-tech" x="' + x + '" y="' + y(r.tech) + '" width="' + bw + '" height="' + (base - y(r.tech)) + '"><title>' +
        esc(label + ': ' + num(r.tech) + ' tech postings') + '</title></rect>');
      out.push('<rect class="jm-other" x="' + x + '" y="' + y(total) + '" width="' + bw + '" height="' + (y(r.tech) - y(total)) + '"><title>' +
        esc(label + ': ' + num(r.nontech) + ' non-tech postings') + '</title></rect>');
      if (rows.length <= 16) out.push('<text class="jm-val" x="' + (x + bw / 2) + '" y="' + (y(total) - 5) + '" text-anchor="middle">' + num(total) + '</text>');
      if (i % every === 0) {
        out.push('<text x="' + (x + bw / 2) + '" y="' + (base + 18) + '" text-anchor="middle">' + esc(r.label.replace(' 20', " '")) + (r.partial ? '*' : '') + '</text>');
      }
    });
    out.push('<line class="jm-axis" x1="' + left + '" x2="' + (W - right) + '" y1="' + base + '" y2="' + base + '"/></svg>');
    return out.join('');
  }

  function shiftChart(shift) {
    // Diverging bars drawn in HTML (not SVG) so the rows reflow on a phone.
    var rows = shift.rising.concat(shift.falling);
    var maxAbs = Math.max.apply(null, rows.map(function (r) { return Math.abs(r.change); }).concat([0.1]));
    return rows.map(function (r) {
      var up = r.change > 0, w = (Math.abs(r.change) / maxAbs * 100).toFixed(1);
      var tip = r.skill + ': ' + r.from + '% of tech postings in ' + shift.from_year + ', ' + r.to + '% in ' + shift.to_year;
      var bar = '<span class="jm-shift-fill ' + (up ? 'jm-shift-fill--up' : 'jm-shift-fill--down') + '" style="width:' + w + '%"></span>';
      return '<div class="jm-shift-row" title="' + esc(tip) + '"><span class="jm-shift-name">' + esc(r.skill) + '</span>' +
        '<span class="jm-shift-half jm-shift-half--neg">' + (up ? '' : bar) + '</span>' +
        '<span class="jm-shift-half jm-shift-half--pos">' + (up ? bar : '') + '</span>' +
        '<span class="jm-shift-val">' + esc((up ? '+' : '') + r.change + ' pts (' + r.from + '% \u2192 ' + r.to + '%)') + '</span></div>';
    }).join('');
  }

  function hbars(el, items, valueText) {
    var max = Math.max.apply(null, items.map(function (i) { return i.value; }).concat([1]));
    el.innerHTML = items.length ? items.map(function (i) {
      return '<div class="jm-hbar" title="' + esc(i.title || '') + '"><span class="jm-hbar-name">' + esc(i.name) + '</span>' +
        '<span class="jm-hbar-track"><span class="jm-hbar-fill" style="width:' + (i.value / max * 100).toFixed(1) + '%"></span></span>' +
        '<span class="jm-hbar-val">' + esc(valueText(i)) + '</span></div>';
    }).join('') : '<p class="muted">No postings yet.</p>';
  }

  function table(el, head, rows, strongCol) {
    el.innerHTML = '<thead><tr>' + head.map(function (h) { return '<th>' + esc(h) + '</th>'; }).join('') + '</tr></thead><tbody>' +
      rows.map(function (r) { return '<tr>' + r.map(function (c, i) {
        return '<td' + (i === strongCol ? ' class="jm-num-strong"' : '') + '>' + esc(c) + '</td>'; }).join('') + '</tr>'; }).join('') +
      '</tbody>';
  }

  // ---- Page -------------------------------------------------------------
  function render(d) {
    $('jm-error').textContent = '';
    if (d.updated) {
      $('jm-updated').textContent = 'Data last updated ' + new Date(d.updated).toLocaleString('en-US',
        {month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit'}) + '.';
    }
    if (!d.exists || d.empty) {
      $('jm-content').hidden = true;
      $('jm-empty').hidden = false;
      $('jm-empty').textContent = !d.exists ? 'No job postings yet. Extract skills on the Data Extraction page first.'
        : 'No ' + d.source_label + ' postings from ' + d.since + ' on yet.';
      return;
    }
    $('jm-empty').hidden = true;
    $('jm-content').hidden = false;
    var range = monthLabel(d.first_month) + ' to ' + monthLabel(d.last_month);

    $('jm-total').textContent = num(d.total);
    $('jm-total-note').textContent = d.source_label + ', ' + range;
    $('jm-tech').textContent = num(d.tech_total);
    $('jm-tech-note').textContent = Math.round(d.tech_total / d.total * 100) + '% of postings are tech jobs';
    $('jm-companies').textContent = num(d.companies);
    $('jm-companies-note').textContent = 'Top 10 posted ' + d.employers_share + '% of jobs';
    var top = d.top_skills[0];
    $('jm-topskill').textContent = top ? top.skill : '—';
    $('jm-topskill-note').textContent = top ? 'In ' + num(top.count) + ' tech postings (' + top.pct + '%)' : '';
    var ghostNote = $('jm-ghost-note');
    if (ghostNote) {
      ghostNote.hidden = !d.ghosts_excluded;
      ghostNote.textContent = d.ghosts_excluded
        ? num(d.ghosts_hidden) + ' possible ghost job' + (d.ghosts_hidden === 1 ? '' : 's') +
          ' excluded, as set in the Dashboard\'s Filter.'
        : '';
    }

    $('jm-quarters').innerHTML = quartersChart(d.quarters);
    var last = d.quarters[d.quarters.length - 1];
    $('jm-quarters-note').textContent = (last && last.partial ? '*' + last.label + ' runs to ' + monthLabel(d.last_month) + ' only. ' : '') +
      'Tech postings are the ones the skill extraction marked as tech jobs (isTechJob).';

    if (d.shift && (d.shift.rising.length || d.shift.falling.length)) {
      $('jm-shift-panel').hidden = false;
      $('jm-shift-note').textContent = 'Change in the share of tech postings that list each skill, ' + d.shift.from_year +
        ' (' + num(d.shift.from_posts) + ' postings) to ' + d.shift.to_year + ' (' + num(d.shift.to_posts) +
        ' postings), in percentage points. Only skills in at least ' + d.shift.min_posts + ' tech postings.';
      $('jm-shift').innerHTML = shiftChart(d.shift);
    } else {
      $('jm-shift-panel').hidden = true;
    }

    table($('jm-skills'), ['Skill', 'Postings', '%'].concat(d.years.map(String)),
      d.top_skills.map(function (s) { return [s.skill, num(s.count), s.pct + '%'].concat(s.by_year.map(num)); }), 1);
    table($('jm-roles'), ['Role'].concat(d.roles.years.map(String)).concat(['Postings']),
      d.roles.rows.map(function (r) { return [r.role].concat(r.by_year.map(function (p) { return p + '%'; })).concat([num(r.count)]); }), d.roles.years.length + 1);

    $('jm-employers-note').textContent = 'The top 10 of ' + num(d.companies) + ' companies posted ' + d.employers_share + '% of these jobs.';
    hbars($('jm-employers'), d.employers.map(function (e) { return {name: e.name, value: e.count, pct: e.pct, title: e.name}; }),
      function (i) { return num(i.value); });
    hbars($('jm-cities'), d.cities.map(function (c) { return {name: c.name, value: c.count, pct: c.pct}; }),
      function (i) { return num(i.value) + ' (' + i.pct + '%)'; });

    $('jm-pay-note').textContent = 'Median monthly pay (midpoint of the posted range), from the ' + num(d.priced) +
      ' postings with a PHP monthly salary.';
    hbars($('jm-pay'), d.pay.map(function (p) {
      return {name: p.level, value: p.median, title: p.priced + ' of ' + p.postings + ' ' + p.level + ' postings show a salary'};
    }), function (i) { return peso(i.value); });

    table($('jm-modes'), ['Work setup'].concat(d.work_modes.years.map(String)),
      d.work_modes.rows.map(function (r) { return [r.mode].concat(r.by_year.map(function (p) { return p + '%'; })); }));
    $('jm-fresh').textContent = 'Open to fresh graduates: ' + d.fresh_grads.map(function (f) { return f.pct + '% in ' + f.year; }).join(', ') + '.';

    $('jm-entry-title').innerHTML = 'Entry-level <small>' + num(d.entry.postings) + ' postings</small>';
    $('jm-senior-title').innerHTML = 'Senior <small>' + num(d.senior.postings) + ' postings</small>';
    hbars($('jm-entry'), d.entry.skills.map(function (s) { return {name: s.skill, value: s.count}; }), function (i) { return num(i.value); });
    hbars($('jm-senior'), d.senior.skills.map(function (s) { return {name: s.skill, value: s.count}; }), function (i) { return num(i.value); });
  }

  function load() {
    if (busy) return;
    busy = true;
    lastFetch = Date.now();
    var sq = sourceQuery();
    var q = '?' + (sq ? sq + '&' : '') + 'since=' + encodeURIComponent(sinceSel.value);
    fetch(url + q, {headers: {'Accept': 'application/json'}, credentials: 'same-origin'})
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.ok) throw new Error(d.error || 'Something went wrong.');
        render(d);
      })
      .catch(function (e) { $('jm-error').textContent = 'Couldn’t load the job market data: ' + e.message; })
      .then(function () { busy = false; });
  }

  function onFilter() {
    var sq = sourceQuery();
    var q = '?' + (sq ? sq + '&' : '') + 'since=' + encodeURIComponent(sinceSel.value);
    if (window.history && history.replaceState) history.replaceState(null, '', location.pathname + q);
    load();
  }
  sourceBoxes.forEach(function (box) {
    box.addEventListener('change', function () {
      // At least one source stays ticked.
      if (!sourceBoxes.some(function (b) { return b.checked; })) { box.checked = true; return; }
      onFilter();
    });
  });
  sinceSel.addEventListener('change', onFilter);
  $('jm-filters').addEventListener('submit', function (e) { e.preventDefault(); onFilter(); });

  setInterval(function () { if (!document.hidden) load(); }, REFRESH_MS);
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden && Date.now() - lastFetch > REFRESH_MS) load();
  });
  load();
})();

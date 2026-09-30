/* ==========================================================================
   UEnvision — front-end interactivity
   --------------------------------------------------------------------------
   This file wires up navigation, forms, charts, tables, and the filter/
   delete/settings UI for both index.html and sample.html (they share the
   same ids and classes, so one script drives both).

   IMPORTANT FOR THE CAPSTONE / SQL INTEGRATION:
   There is no real backend yet, so every "data" object below (DASHBOARD,
   TABLE_DATA) is mock data standing in for what will eventually come from
   your SQL database. Search this file for "TODO(SQL)" to see the exact
   spots where a real fetch()/query call should replace the mock data once
   your database (e.g. a Supabase Postgres table) is wired up. Everything
   else — rendering, navigation, validation — stays the same.
   ========================================================================== */

(function () {
  'use strict';

  /* ---------------------------- small helpers ---------------------------- */
  const qs = (sel, root) => (root || document).querySelector(sel);
  const qsa = (sel, root) => Array.from((root || document).querySelectorAll(sel));
  const on = (el, evt, handler) => { if (el) el.addEventListener(evt, handler); };

  function formatNumber(n) {
    return Number(n).toLocaleString('en-US');
  }

  function escapeHtml(str) {
    return String(str).replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
  }

  function prettifyKey(key) {
    return key
      .replace(/([a-z])([A-Z])/g, '$1 $2')
      .replace(/^./, (c) => c.toUpperCase());
  }

  /* ------------------------------- toast ---------------------------------- */
  let toastTimer = null;
  function showToast(message, isError) {
    const toast = qs('#toast');
    if (!toast) return;
    toast.textContent = message;
    toast.classList.toggle('is-error', !!isError);
    toast.classList.add('is-active');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove('is-active'), 2600);
  }

  /* ============================================================
     MOCK DATA
     TODO(SQL): replace DASHBOARD and TABLE_DATA with data fetched
     from your database once the backend is connected, e.g.:
       const { data } = await supabase.from('job_postings').select('*');
     ============================================================ */

  const DASHBOARD = {
    lastAnalyzation: '09/07/2026',
    stats: {
      totalPostings: { value: '2,470', note: 'Your postings after filtering' },
      uniqueSkills: { value: '183', note: 'Top category: Programming (47%)' },
      topSkill: { value: 'Python', note: 'Appears in 78% of postings' },
      alignment: { value: '68%', note: 'Cosine similarity: 0.68' },
      skillGaps: { value: '27', note: 'Top gap: Cloud Computing' }
    },
    topSkills: [
      { label: 'Python', value: 1927 },
      { label: 'SQL', value: 1606 },
      { label: 'JavaScript', value: 1433 },
      { label: 'AWS', value: 1161 },
      { label: 'Excel', value: 1087 },
      { label: 'Java', value: 963 },
      { label: 'Tableau', value: 766 },
      { label: 'R', value: 593 }
    ],
    skillTrends: {
      labels: ['2023', '2024 Q1', '2024 Q3', '2025 Q1', '2025 Q3', '2026 Q1', '2026 Q3'],
      series: [
        { name: 'Python', color: '#c8202f', data: [24, 33, 46, 60, 74, 84, 92] },
        { name: 'SQL', color: '#1b2a4a', data: [16, 20, 26, 33, 40, 47, 53] },
        { name: 'AWS', color: '#a7abb8', data: [5, 6, 7, 9, 10, 11, 13] }
      ]
    }
  };

  const TABLE_COLUMNS = {
    raw: ['title', 'company', 'location', 'datePosted', 'source', 'program'],
    extracted: ['jobId', 'skill', 'category', 'frequency', 'confidence'],
    survey: ['respondentId', 'role', 'program', 'satisfaction', 'comments'],
    category: ['category', 'skillCount', 'percentOfPostings', 'trend']
  };

  const TABLE_DATA = {
    raw: [
      { title: 'Junior Data Analyst', company: 'Globe Telecom', location: 'Taguig City', datePosted: '2026-08-02', source: 'JobStreet', program: 'BSIT' },
      { title: 'Software Engineer I', company: 'Accenture PH', location: 'Quezon City', datePosted: '2026-08-05', source: 'LinkedIn', program: 'BSCS' },
      { title: 'Cloud Support Associate', company: 'IBM Philippines', location: 'Cebu City', datePosted: '2026-07-29', source: 'Indeed', program: 'BSIT' },
      { title: 'BI Developer', company: 'Concentrix', location: 'Pasig City', datePosted: '2026-08-11', source: 'JobStreet', program: 'BSIT' },
      { title: 'Backend Developer (Node.js)', company: 'PLDT Enterprise', location: 'Makati City', datePosted: '2026-08-14', source: 'LinkedIn', program: 'BSCS' },
      { title: 'QA / Test Automation Engineer', company: 'Sun Life Asia Service Centre', location: 'Taguig City', datePosted: '2026-07-21', source: 'Kalibrr', program: 'BSCS' }
    ],
    extracted: [
      { jobId: 'JP-10432', skill: 'Python', category: 'Programming', frequency: 1927, confidence: 'High' },
      { jobId: 'JP-10432', skill: 'SQL', category: 'Data', frequency: 1606, confidence: 'High' },
      { jobId: 'JP-10488', skill: 'AWS', category: 'Cloud', frequency: 1161, confidence: 'Medium' },
      { jobId: 'JP-10511', skill: 'Tableau', category: 'Data', frequency: 766, confidence: 'Medium' },
      { jobId: 'JP-10577', skill: 'JavaScript', category: 'Programming', frequency: 1433, confidence: 'High' },
      { jobId: 'JP-10602', skill: 'Excel', category: 'Productivity', frequency: 1087, confidence: 'High' }
    ],
    survey: [
      { respondentId: 'R-014', role: 'IT Manager', program: 'BSIT partner industry', satisfaction: 4, comments: 'Strong fundamentals, weak on cloud tooling' },
      { respondentId: 'R-021', role: 'Recruiter', program: 'BSCS partner industry', satisfaction: 3, comments: 'Needs more exposure to real datasets' },
      { respondentId: 'R-033', role: 'Alumnus (2024)', program: 'BSIT', satisfaction: 5, comments: 'Curriculum matched my first job well' },
      { respondentId: 'R-047', role: 'Faculty', program: 'BSCS', satisfaction: 4, comments: 'Would like an updated cloud computing elective' }
    ],
    category: [
      { category: 'Programming Languages', skillCount: 34, percentOfPostings: '47%', trend: 'Rising' },
      { category: 'Cloud Platforms', skillCount: 18, percentOfPostings: '29%', trend: 'Rising' },
      { category: 'Data & Analytics', skillCount: 26, percentOfPostings: '38%', trend: 'Stable' },
      { category: 'DevOps & Tools', skillCount: 15, percentOfPostings: '19%', trend: 'Rising' },
      { category: 'Productivity Software', skillCount: 9, percentOfPostings: '22%', trend: 'Stable' }
    ]
  };

  /* ============================================================
     AUTH SCREENS (login / signup / forgot / reset / app)
     ============================================================ */

  function showAuthScreen(id) {
    qsa('.auth-screen').forEach((el) => el.classList.remove('is-active'));
    qs('#app').classList.remove('is-active');
    const target = document.getElementById(id);
    if (target) target.classList.add('is-active');
  }

  function showApp() {
    qsa('.auth-screen').forEach((el) => el.classList.remove('is-active'));
    qs('#app').classList.add('is-active');
  }

  function setFormError(id, message) {
    const el = document.getElementById(id);
    if (!el) return;
    if (!message) {
      el.hidden = true;
      el.textContent = '';
    } else {
      el.hidden = false;
      el.textContent = message;
    }
  }

  function deriveProfileFromEmail(email) {
    const local = String(email || '').split('@')[0];
    if (!local) return { name: 'Jose Rizal', role: 'Faculty' };
    const parts = local.split(/[._-]+/).filter(Boolean);
    const name = parts
      .map((p) => p.charAt(0).toUpperCase() + p.slice(1))
      .join(' ');
    return { name: name || 'Jose Rizal', role: 'Faculty' };
  }

  function setProfile(name, role, email) {
    const nameEl = qs('#profile-name');
    const roleEl = qs('#profile-role');
    if (nameEl) nameEl.textContent = name;
    if (roleEl) roleEl.textContent = role;
    const usernameEl = qs('#settings-username');
    const emailEl = qs('#settings-email');
    if (usernameEl) usernameEl.textContent = name;
    if (emailEl && email) emailEl.textContent = email;
  }

  function initAuth() {
    // Any element with data-goto switches auth screens (login/signup/forgot/reset)
    qsa('[data-goto]').forEach((btn) => {
      on(btn, 'click', () => showAuthScreen(btn.getAttribute('data-goto')));
    });

    // --- Log in ---
    on(qs('#login-form'), 'submit', (e) => {
      e.preventDefault();
      const email = qs('#login-email').value.trim();
      const password = qs('#login-password').value;
      setFormError('login-error', '');

      if (!email || !password) {
        setFormError('login-error', 'Please enter both your email and password.');
        return;
      }

      // TODO(SQL): replace with a real authentication call, e.g.
      //   const { data, error } = await supabase.auth.signInWithPassword({ email, password });
      const profile = deriveProfileFromEmail(email);
      setProfile(profile.name, profile.role, email);
      sessionStorage.setItem('ue_loggedIn', '1');
      sessionStorage.setItem('ue_email', email);
      showApp();
      showToast(`Welcome back, ${profile.name}!`);
    });

    // --- Sign up ---
    on(qs('#signup-form'), 'submit', (e) => {
      e.preventDefault();
      setFormError('signup-error', '');

      const lastName = qs('#signup-lastname').value.trim();
      const firstName = qs('#signup-firstname').value.trim();
      const email = qs('#signup-email').value.trim();
      const password = qs('#signup-password').value;
      const password2 = qs('#signup-password2').value;

      if (!lastName || !firstName || !email || !password || !password2) {
        setFormError('signup-error', 'Please fill in all required fields.');
        return;
      }
      if (password !== password2) {
        setFormError('signup-error', 'Passwords do not match.');
        return;
      }
      if (password.length < 8) {
        setFormError('signup-error', 'Password must be at least 8 characters.');
        return;
      }

      // TODO(SQL): replace with a real "create account" call, e.g.
      //   const { error } = await supabase.auth.signUp({ email, password });
      //   then INSERT a row into a `profiles` table with first/last/middle name.
      showToast('Account created! You can now log in.');
      qs('#signup-form').reset();
      showAuthScreen('screen-login');
    });

    // --- Forgot password: send code ---
    on(qs('#forgot-form'), 'submit', (e) => {
      e.preventDefault();
      setFormError('forgot-error', '');
      const email = qs('#forgot-email').value.trim();
      if (!email) {
        setFormError('forgot-error', 'Please enter your email address.');
        return;
      }
      // TODO(SQL): replace with a real "send reset code" call to your backend.
      showToast('A verification code has been sent to ' + email);
    });

    // --- Forgot password: submit code ---
    on(qs('#forgot-submit'), 'click', () => {
      const code = qs('#forgot-code').value.trim();
      setFormError('forgot-error', '');
      if (!code) {
        setFormError('forgot-error', 'Please enter the 6-digit code sent to your email.');
        return;
      }
      // data-goto="screen-reset" on this button already advances the screen
      // via the generic [data-goto] handler above.
    });

    // --- Reset password ---
    on(qs('#reset-form'), 'submit', (e) => {
      e.preventDefault();
      setFormError('reset-error', '');
      const p1 = qs('#reset-password').value;
      const p2 = qs('#reset-password2').value;
      if (!p1 || !p2) {
        setFormError('reset-error', 'Please fill in both password fields.');
        return;
      }
      if (p1 !== p2) {
        setFormError('reset-error', 'Passwords do not match.');
        return;
      }
      if (p1.length < 8) {
        setFormError('reset-error', 'Password must be at least 8 characters.');
        return;
      }
      // TODO(SQL): replace with a real "update password" call.
      showToast('Password updated. Please log in.');
      qs('#reset-form').reset();
      showAuthScreen('screen-login');
    });

    // Restore a previous session (so a page refresh doesn't force re-login)
    if (sessionStorage.getItem('ue_loggedIn') === '1') {
      const email = sessionStorage.getItem('ue_email') || '';
      const profile = deriveProfileFromEmail(email);
      if (email) setProfile(profile.name, profile.role, email);
      showApp();
    }
  }

  /* ============================================================
     APP SHELL: sidebar navigation, collapse, tabs
     ============================================================ */

  function switchPage(pageName) {
    qsa('.nav-item[data-page]').forEach((btn) => {
      const active = btn.getAttribute('data-page') === pageName;
      btn.classList.toggle('is-active', active);
      if (active) btn.setAttribute('aria-current', 'page');
      else btn.removeAttribute('aria-current');
    });
    qsa('.page').forEach((section) => {
      section.classList.toggle('is-active', section.id === 'page-' + pageName);
    });
  }

  function initNav() {
    qsa('.nav-item[data-page]').forEach((btn) => {
      on(btn, 'click', () => switchPage(btn.getAttribute('data-page')));
    });
  }

  function initSidebarCollapse() {
    const sidebar = qs('#sidebar');
    const collapseBtn = qs('#collapse-btn');
    if (!sidebar || !collapseBtn) return;

    if (localStorage.getItem('ue_sidebarCollapsed') === '1') {
      sidebar.classList.add('is-collapsed');
    }

    on(collapseBtn, 'click', () => {
      const collapsed = sidebar.classList.toggle('is-collapsed');
      localStorage.setItem('ue_sidebarCollapsed', collapsed ? '1' : '0');
    });
  }

  function initTabs() {
    qsa('.tab[data-tab]').forEach((tab) => {
      on(tab, 'click', () => {
        const target = tab.getAttribute('data-tab');
        qsa('.tab[data-tab]').forEach((t) => t.classList.toggle('is-active', t === tab));
        qsa('.tab-panel').forEach((panel) => {
          panel.classList.toggle('is-active', panel.id === 'tab-' + target);
        });
      });
    });
  }

  /* ============================================================
     DASHBOARD RENDERING
     ============================================================ */

  function renderStats() {
    const map = {
      totalPostings: ['stat-total-postings', 'stat-total-postings-note'],
      uniqueSkills: ['stat-unique-skills', 'stat-unique-skills-note'],
      topSkill: ['stat-top-skill', 'stat-top-skill-note'],
      alignment: ['stat-alignment', 'stat-alignment-note'],
      skillGaps: ['stat-skill-gaps', 'stat-skill-gaps-note']
    };
    Object.keys(map).forEach((key) => {
      const [valueId, noteId] = map[key];
      const valueEl = document.getElementById(valueId);
      const noteEl = document.getElementById(noteId);
      const stat = DASHBOARD.stats[key];
      if (valueEl && stat) valueEl.textContent = stat.value;
      if (noteEl && stat) noteEl.textContent = stat.note;
    });

    const lastAnalyzationEl = qs('#last-analyzation');
    if (lastAnalyzationEl) lastAnalyzationEl.textContent = DASHBOARD.lastAnalyzation;
  }

  function renderBarChart(items) {
    const container = qs('#bar-chart');
    if (!container) return;
    container.innerHTML = '';

    if (!items || !items.length) {
      container.innerHTML = '<p class="bars-empty">No skills match the current filters.</p>';
      return;
    }

    const max = Math.max(...items.map((i) => i.value));
    items.forEach((item) => {
      const row = document.createElement('div');
      row.className = 'bar-row';
      const pct = max ? Math.round((item.value / max) * 100) : 0;
      row.innerHTML =
        '<span class="bar-label">' + escapeHtml(item.label) + '</span>' +
        '<span class="bar-track"><span class="bar-fill" style="width:' + pct + '%"></span></span>' +
        '<span class="bar-value">' + formatNumber(item.value) + '</span>';
      container.appendChild(row);
    });
  }

  function renderLineChart() {
    const svg = qs('#line-chart');
    const legend = qs('#skill-trends-legend');
    const labelsWrap = qs('#line-labels');
    if (!svg) return; // sample.html's static line chart has no id — leave it alone

    const { labels, series } = DASHBOARD.skillTrends;
    const viewW = 640;
    const top = 40;
    const bottom = 220;

    const allValues = series.flatMap((s) => s.data);
    const minVal = Math.min(...allValues, 0);
    const maxVal = Math.max(...allValues, 1);

    function toPoints(data) {
      return data.map((value, i) => {
        const x = (i / (data.length - 1)) * viewW;
        const ratio = (value - minVal) / (maxVal - minVal || 1);
        const y = bottom - ratio * (bottom - top);
        return x.toFixed(1) + ',' + y.toFixed(1);
      }).join(' ');
    }

    // Remove any previously drawn polylines, keep the gridlines.
    qsa('polyline', svg).forEach((el) => el.remove());

    series.forEach((s) => {
      const poly = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
      poly.setAttribute('points', toPoints(s.data));
      poly.setAttribute('fill', 'none');
      poly.setAttribute('stroke', s.color);
      poly.setAttribute('stroke-width', '3');
      svg.appendChild(poly);
    });

    if (legend) {
      legend.innerHTML = series.map((s) =>
        '<span class="dot" style="background:' + s.color + '"></span>' + escapeHtml(s.name)
      ).join(' &nbsp; ');
    }
    if (labelsWrap) {
      labelsWrap.innerHTML = labels.map((l) => '<span>' + escapeHtml(l) + '</span>').join('');
    }
  }

  function getCheckedSkillLabels() {
    const grid = qs('#skill-chip-grid');
    if (!grid) return null; // no filter grid on this page — show everything
    const checked = qsa('input[type="checkbox"]:checked', grid).map((cb) =>
      cb.parentElement.querySelector('span').textContent.trim()
    );
    return checked;
  }

  function renderDashboard() {
    renderStats();
    const checked = getCheckedSkillLabels();
    const items = checked
      ? DASHBOARD.topSkills.filter((s) => checked.includes(s.label))
      : DASHBOARD.topSkills;
    renderBarChart(items);
    renderLineChart();
  }

  /* ============================================================
     FILTER DRAWER
     ============================================================ */

  function initFilterDrawer() {
    const drawer = qs('#filter-drawer');
    const backdrop = qs('#filter-backdrop');
    if (!drawer || !backdrop) return;

    function openDrawer() {
      drawer.classList.add('is-active');
      backdrop.classList.add('is-active');
      drawer.setAttribute('aria-hidden', 'false');
    }
    function closeDrawer() {
      drawer.classList.remove('is-active');
      backdrop.classList.remove('is-active');
      drawer.setAttribute('aria-hidden', 'true');
    }

    on(qs('#filter-btn'), 'click', openDrawer);
    on(qs('#filter-close'), 'click', closeDrawer);
    on(backdrop, 'click', closeDrawer);
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && drawer.classList.contains('is-active')) closeDrawer();
    });

    on(qs('#filter-clear-all'), 'click', () => {
      qsa('input[type="checkbox"]', drawer).forEach((cb) => { cb.checked = false; });
    });

    qsa('[data-clear-section]', drawer).forEach((btn) => {
      on(btn, 'click', () => {
        const section = btn.closest('.drawer-section');
        if (section) qsa('input[type="checkbox"]', section).forEach((cb) => { cb.checked = false; });
      });
    });

    on(qs('#filter-apply'), 'click', () => {
      renderDashboard();
      closeDrawer();
      showToast('Filters applied.');
    });
  }

  /* ============================================================
     DATA PAGE: table + CSV export
     ============================================================ */

  function currentSource() {
    const select = qs('#data-source');
    return select ? select.value : 'raw';
  }

  function renderTable(source) {
    const table = qs('#data-table');
    if (!table) return;
    const rows = TABLE_DATA[source] || [];
    const columns = TABLE_COLUMNS[source] || (rows[0] ? Object.keys(rows[0]) : []);

    const thead = '<thead><tr>' +
      columns.map((c) => '<th>' + escapeHtml(prettifyKey(c)) + '</th>').join('') +
      '</tr></thead>';

    const tbody = '<tbody>' +
      rows.map((row) =>
        '<tr>' + columns.map((c) => '<td>' + escapeHtml(row[c] ?? '') + '</td>').join('') + '</tr>'
      ).join('') +
      '</tbody>';

    table.innerHTML = thead + tbody;
  }

  function exportCurrentTableAsCsv() {
    const source = currentSource();
    const rows = TABLE_DATA[source] || [];
    const columns = TABLE_COLUMNS[source] || (rows[0] ? Object.keys(rows[0]) : []);

    if (!rows.length) {
      showToast('There is no data to export for this source.', true);
      return;
    }

    const csvEscape = (val) => {
      const s = String(val ?? '');
      return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
    };

    const lines = [
      columns.map((c) => csvEscape(prettifyKey(c))).join(','),
      ...rows.map((row) => columns.map((c) => csvEscape(row[c])).join(','))
    ];

    const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'uenvision-' + source + '.csv';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    showToast('Exported ' + rows.length + ' rows as CSV.');
  }

  function initDataPage() {
    const select = qs('#data-source');
    if (select) {
      renderTable(select.value);
      on(select, 'change', () => renderTable(select.value));
    }
    on(qs('#export-btn'), 'click', exportCurrentTableAsCsv);
  }

  /* ============================================================
     FEEDBACK PAGE: SUS / UAT / Functional test case surveys
     ------------------------------------------------------------
     Submissions are saved to Supabase (see config.js + schema.sql)
     when configured; otherwise they fall back to localStorage so
     the forms are fully testable before your database exists.
     ============================================================ */

  // Standard 10-item System Usability Scale (Brooke, 1986).
  const SUS_QUESTIONS = [
    'I think that I would like to use this system frequently.',
    'I found the system unnecessarily complex.',
    'I thought the system was easy to use.',
    'I think that I would need the support of a technical person to be able to use this system.',
    'I found the various functions in this system were well integrated.',
    'I thought there was too much inconsistency in this system.',
    'I would imagine that most people would learn to use this system very quickly.',
    'I found the system very cumbersome to use.',
    'I felt very confident using the system.',
    'I needed to learn a lot of things before I could get going with this system.'
  ];

  const UAT_CHECKS = [
    { id: 'login', label: 'Logging in (and logging out) worked as expected.' },
    { id: 'dashboard', label: 'The dashboard stats and charts loaded correctly.' },
    { id: 'filter', label: 'Filtering the dashboard updated the results correctly.' },
    { id: 'export', label: 'Exporting data from the Data page worked correctly.' },
    { id: 'settings', label: 'Editing account settings saved correctly.' }
  ];

  const FUNCTIONAL_DEFAULT_ROWS = [
    { feature: 'Log in', steps: 'Enter a valid email and password, click Log in.', expected: 'User is taken to the Dashboard.' },
    { feature: 'Dashboard filter', steps: 'Open Filter, uncheck a skill, click Apply filters.', expected: 'Top in-demand skills chart updates to exclude that skill.' },
    { feature: 'Export data', steps: 'Go to Data, choose a source, click Export.', expected: 'A CSV file downloads with the visible table’s rows.' },
    { feature: 'Edit settings', steps: 'Go to Settings, click Edit, change name/email, click Save.', expected: 'The new values are shown in Settings and the sidebar.' },
    { feature: 'Log out', steps: 'Go to Settings, click Log out.', expected: 'User is returned to the Log in screen.' }
  ];

  let functionalRowCount = 0;

  /* ---- Supabase client (falls back to localStorage if unset) ---- */
  let supabaseClient = null;
  if (window.supabase && window.UE_SUPABASE_URL && window.UE_SUPABASE_ANON_KEY) {
    try {
      supabaseClient = window.supabase.createClient(window.UE_SUPABASE_URL, window.UE_SUPABASE_ANON_KEY);
    } catch (err) {
      console.error('Could not create Supabase client:', err);
    }
  }

  function saveToLocalFallback(table, rows) {
    const key = 'ue_survey_' + table;
    const existing = JSON.parse(localStorage.getItem(key) || '[]');
    rows.forEach((row) => existing.push(Object.assign({}, row, { _savedAt: new Date().toISOString() })));
    localStorage.setItem(key, JSON.stringify(existing));
  }

  // Accepts a single response object or an array of them (for the
  // functional test sheet, which submits several rows at once).
  async function saveSurveyResponse(table, payload) {
    const rows = Array.isArray(payload) ? payload : [payload];

    if (supabaseClient) {
      const { error } = await supabaseClient.from(table).insert(rows);
      if (error) {
        console.error('Supabase insert failed, saving locally instead:', error);
        saveToLocalFallback(table, rows);
        return { ok: true, usedFallback: true };
      }
      return { ok: true, usedFallback: false };
    }

    // TODO(SQL): once config.js has your Supabase URL + anon key, this
    // fallback branch stops being used and rows go straight to your table.
    saveToLocalFallback(table, rows);
    return { ok: true, usedFallback: true };
  }

  /* ---- navigation between the survey list and each form ---- */
  function showSurveyHome() {
    qs('#feedback-home').hidden = false;
    qsa('.survey-wrap').forEach((el) => { el.hidden = true; });
  }

  function showSurveyForm(name) {
    const target = document.getElementById('survey-' + name);
    if (!target) return;
    qs('#feedback-home').hidden = true;
    qsa('.survey-wrap').forEach((el) => { el.hidden = true; });
    target.hidden = false;
  }

  /* ---- SUS ---- */
  function renderSusQuestions() {
    const container = qs('#sus-questions');
    if (!container || container.childElementCount) return; // render once
    container.innerHTML = SUS_QUESTIONS.map((question, i) => {
      const n = i + 1;
      const options = [1, 2, 3, 4, 5].map((v) =>
        '<label class="likert-option">' +
          '<input type="radio" name="sus-q' + n + '" value="' + v + '" required>' +
          '<span>' + v + '</span>' +
        '</label>'
      ).join('');
      return (
        '<div class="likert-group">' +
          '<p class="likert-question">' + (n) + '. ' + escapeHtml(question) + '</p>' +
          '<div class="likert-scale">' +
            '<span class="likert-end">Strongly disagree</span>' +
            options +
            '<span class="likert-end">Strongly agree</span>' +
          '</div>' +
        '</div>'
      );
    }).join('');
  }

  function computeSusScore(answers) {
    // Odd items are scored (answer - 1); even items are scored (5 - answer).
    // The sum of all 10 is multiplied by 2.5 to give a 0-100 score.
    let total = 0;
    answers.forEach((value, idx) => {
      const n = idx + 1;
      total += (n % 2 === 1) ? (value - 1) : (5 - value);
    });
    return Math.round(total * 2.5 * 100) / 100;
  }

  function initSusForm() {
    renderSusQuestions();
    on(qs('#sus-form'), 'submit', async (e) => {
      e.preventDefault();
      setFormError('sus-error', '');

      const answers = [];
      for (let n = 1; n <= 10; n++) {
        const checked = qs('input[name="sus-q' + n + '"]:checked');
        if (!checked) {
          setFormError('sus-error', 'Please answer every statement before submitting.');
          return;
        }
        answers.push(Number(checked.value));
      }

      const payload = {
        respondent_role: qs('#sus-role').value,
        program: qs('#sus-program').value,
        q1: answers[0], q2: answers[1], q3: answers[2], q4: answers[3], q5: answers[4],
        q6: answers[5], q7: answers[6], q8: answers[7], q9: answers[8], q10: answers[9],
        sus_score: computeSusScore(answers),
        comments: qs('#sus-comments').value.trim() || null
      };

      const result = await saveSurveyResponse('sus_responses', payload);
      qs('#sus-form').reset();
      showToast(result.usedFallback
        ? 'Saved locally (connect Supabase in config.js to sync to your database).'
        : 'Thanks! Your SUS evaluation was submitted.');
      showSurveyHome();
    });
  }

  /* ---- UAT ---- */
  function renderUatChecks() {
    const container = qs('#uat-checks');
    if (!container || container.childElementCount) return; // render once
    container.innerHTML = UAT_CHECKS.map((check) =>
      '<div class="uat-check-row">' +
        '<p class="uat-check-label">' + escapeHtml(check.label) + '</p>' +
        '<div class="uat-check-options">' +
          ['Yes', 'Partial', 'No'].map((opt) =>
            '<label class="checkbox uat-radio">' +
              '<input type="radio" name="uat-' + check.id + '" value="' + opt + '" required>' +
              '<span>' + opt + '</span>' +
            '</label>'
          ).join('') +
        '</div>' +
      '</div>'
    ).join('');
  }

  function initUatForm() {
    renderUatChecks();
    on(qs('#uat-form'), 'submit', async (e) => {
      e.preventDefault();
      setFormError('uat-error', '');

      const name = qs('#uat-name').value.trim();
      if (!name) {
        setFormError('uat-error', 'Please enter your name.');
        return;
      }

      const results = {};
      for (const check of UAT_CHECKS) {
        const checked = qs('input[name="uat-' + check.id + '"]:checked');
        if (!checked) {
          setFormError('uat-error', 'Please answer every item before submitting.');
          return;
        }
        results[check.id] = checked.value;
      }

      const payload = {
        tester_name: name,
        tester_role: qs('#uat-role').value,
        program: qs('#uat-program').value,
        test_date: qs('#uat-date').value || null,
        login_worked: results.login,
        dashboard_worked: results.dashboard,
        filter_worked: results.filter,
        export_worked: results.export,
        settings_worked: results.settings,
        satisfaction: Number(qs('#uat-satisfaction').value),
        comments: qs('#uat-comments').value.trim() || null
      };

      const result = await saveSurveyResponse('uat_responses', payload);
      qs('#uat-form').reset();
      showToast(result.usedFallback
        ? 'Saved locally (connect Supabase in config.js to sync to your database).'
        : 'Thanks! Your UAT survey was submitted.');
      showSurveyHome();
    });
  }

  /* ---- Functional test case sheet ---- */
  function functionalRowHtml(row) {
    functionalRowCount += 1;
    const idx = functionalRowCount;
    return (
      '<tr data-row="' + idx + '">' +
        '<td>TC-' + String(idx).padStart(2, '0') + '</td>' +
        '<td><input type="text" class="ft-feature" value="' + escapeHtml(row.feature || '') + '"></td>' +
        '<td><input type="text" class="ft-steps" value="' + escapeHtml(row.steps || '') + '"></td>' +
        '<td><input type="text" class="ft-expected" value="' + escapeHtml(row.expected || '') + '"></td>' +
        '<td><input type="text" class="ft-actual" placeholder="What actually happened"></td>' +
        '<td><select class="ft-status">' +
          '<option value="Pass">Pass</option>' +
          '<option value="Fail">Fail</option>' +
          '<option value="Blocked">Blocked</option>' +
        '</select></td>' +
        '<td><input type="text" class="ft-notes" placeholder="Optional"></td>' +
        '<td><button type="button" class="link-inline link-inline--sm ft-remove" aria-label="Remove row">Remove</button></td>' +
      '</tr>'
    );
  }

  function addFunctionalRow(row) {
    const tbody = qs('#functional-rows');
    if (!tbody) return;
    tbody.insertAdjacentHTML('beforeend', functionalRowHtml(row || {}));
  }

  function renderFunctionalTable() {
    const tbody = qs('#functional-rows');
    if (!tbody || tbody.childElementCount) return; // render once
    functionalRowCount = 0;
    FUNCTIONAL_DEFAULT_ROWS.forEach(addFunctionalRow);
  }

  function collectFunctionalRows(testerName) {
    const submissionId = (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()));
    return qsa('#functional-rows tr').map((tr) => ({
      submission_id: submissionId,
      tester_name: testerName,
      test_case_id: tr.children[0].textContent.trim(),
      feature: tr.querySelector('.ft-feature').value.trim(),
      steps: tr.querySelector('.ft-steps').value.trim(),
      expected_result: tr.querySelector('.ft-expected').value.trim(),
      actual_result: tr.querySelector('.ft-actual').value.trim(),
      status: tr.querySelector('.ft-status').value,
      notes: tr.querySelector('.ft-notes').value.trim() || null
    }));
  }

  function initFunctionalForm() {
    renderFunctionalTable();

    on(qs('#functional-add-row'), 'click', () => addFunctionalRow());

    on(qs('#functional-rows'), 'click', (e) => {
      if (e.target.classList.contains('ft-remove')) {
        const tr = e.target.closest('tr');
        if (tr && qsa('#functional-rows tr').length > 1) tr.remove();
        else showToast('Keep at least one test case, or use Back to cancel.', true);
      }
    });

    on(qs('#functional-form'), 'submit', async (e) => {
      e.preventDefault();
      setFormError('functional-error', '');

      const tester = qs('#functional-tester').value.trim();
      if (!tester) {
        setFormError('functional-error', 'Please enter the tester’s name.');
        return;
      }

      const rows = collectFunctionalRows(tester);
      const incomplete = rows.some((r) => !r.actual_result);
      if (incomplete) {
        setFormError('functional-error', 'Please fill in the actual result for every test case.');
        return;
      }

      const result = await saveSurveyResponse('functional_test_results', rows);
      qs('#functional-form').reset();
      qs('#functional-rows').innerHTML = '';
      functionalRowCount = 0;
      renderFunctionalTable();
      showToast(result.usedFallback
        ? 'Saved locally (connect Supabase in config.js to sync to your database).'
        : 'Thanks! Your test results were submitted.');
      showSurveyHome();
    });
  }

  function initFeedback() {
    qsa('.feedback-item').forEach((link) => {
      on(link, 'click', (e) => {
        e.preventDefault();
        showSurveyForm(link.getAttribute('data-survey'));
      });
    });

    qsa('.survey-back').forEach((btn) => {
      on(btn, 'click', showSurveyHome);
    });

    initSusForm();
    initUatForm();
    initFunctionalForm();
  }

  /* ============================================================
     SETTINGS: edit account fields, delete modal, log out
     ============================================================ */

  function initSettings() {
    const editBtn = qs('#edit-btn');
    const usernameField = qs('#settings-username');
    const emailField = qs('#settings-email');
    let editing = false;

    on(editBtn, 'click', () => {
      if (!usernameField || !emailField) return;

      if (!editing) {
        const nameVal = usernameField.textContent.trim();
        const emailVal = emailField.textContent.trim();
        usernameField.innerHTML = '<input type="text" id="edit-username-input" value="' + escapeHtml(nameVal) + '">';
        emailField.innerHTML = '<input type="email" id="edit-email-input" value="' + escapeHtml(emailVal) + '">';
        editBtn.textContent = 'Save';
        editing = true;
      } else {
        const nameInput = qs('#edit-username-input');
        const emailInput = qs('#edit-email-input');
        const newName = nameInput ? nameInput.value.trim() : '';
        const newEmail = emailInput ? emailInput.value.trim() : '';

        usernameField.textContent = newName || 'Jose Rizal';
        emailField.textContent = newEmail || 'jose.rizal@ue.edu.ph';
        setProfile(usernameField.textContent, qs('#profile-role') ? qs('#profile-role').textContent : 'Faculty');
        editBtn.textContent = 'Edit';
        editing = false;

        // TODO(SQL): persist these changes, e.g.
        //   await supabase.from('profiles').update({ name: newName, email: newEmail }).eq('id', currentUserId);
        showToast('Account details updated.');
      }
    });

    // --- Delete account modal ---
    const deleteBackdrop = qs('#delete-backdrop');
    on(qs('#delete-btn'), 'click', () => { if (deleteBackdrop) deleteBackdrop.classList.add('is-active'); });
    on(qs('#delete-cancel'), 'click', () => { if (deleteBackdrop) deleteBackdrop.classList.remove('is-active'); });
    on(deleteBackdrop, 'click', (e) => { if (e.target === deleteBackdrop) deleteBackdrop.classList.remove('is-active'); });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && deleteBackdrop && deleteBackdrop.classList.contains('is-active')) {
        deleteBackdrop.classList.remove('is-active');
      }
    });
    on(qs('#delete-yes'), 'click', () => {
      // TODO(SQL): call your real "delete account" endpoint here.
      if (deleteBackdrop) deleteBackdrop.classList.remove('is-active');
      logOut('Your account has been deleted.');
    });

    on(qs('#logout-btn'), 'click', () => logOut('You have been logged out.'));
  }

  function logOut(message) {
    sessionStorage.removeItem('ue_loggedIn');
    sessionStorage.removeItem('ue_email');
    showAuthScreen('screen-login');
    qsa('form').forEach((f) => f.reset());
    if (message) showToast(message);
  }

  /* ============================================================
     INIT
     ============================================================ */

  document.addEventListener('DOMContentLoaded', () => {
    initAuth();
    initNav();
    initSidebarCollapse();
    initTabs();
    initFilterDrawer();
    initDataPage();
    initFeedback();
    initSettings();
    renderDashboard();
  });
})();

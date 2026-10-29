document.addEventListener('DOMContentLoaded', () => {

  /* ======================================================================
     URL HELPERS — read the data-*-url attributes base.html put on <body>,
     so this file never hardcodes a Django path.
  ====================================================================== */
  const urls = document.body.dataset;
  const goTo = key => { window.location.href = urls[key]; };

  /* ======================================================================
     TOAST
  ====================================================================== */
  const toastEl = document.getElementById('toast');
  let toastTimer;
  function showToast(msg){
    if (!toastEl) return;
    toastEl.textContent = msg;
    toastEl.classList.add('is-active');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastEl.classList.remove('is-active'), 3200);
  }

  function setMsg(el, text, kind){
    if (!el) return;
    el.textContent = text || '';
    el.classList.remove('is-error', 'is-success');
    if (kind) el.classList.add(kind === 'error' ? 'is-error' : 'is-success');
  }

  /* ======================================================================
     ACCOUNTS — persisted in localStorage so they survive full page loads
     (every Django page here is a real navigation, not a JS view-swap).

     NOTE: Login and signup now go through Django (see login_view /
     signup_view in views.py), which is the real source of truth for
     accounts and passwords. This local "accounts" list is kept only
     for pages not yet wired to the backend (settings, delete account). Those will need the same treatment
     as login/signup eventually.
  ====================================================================== */
  const STORAGE_KEY = 'uenvision_accounts';
  const SESSION_KEY = 'uenvision_session';

  function loadAccounts(){
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) return JSON.parse(raw);
    } catch (e) { /* ignore corrupt storage */ }
    const seed = [{
      id: '24601', firstName: 'Jose', lastName: 'Rizal', name: 'Jose Rizal',
      email: 'jose.rizal@ue.edu.ph', password: 'rizal123', role: 'Faculty'
    }];
    localStorage.setItem(STORAGE_KEY, JSON.stringify(seed));
    return seed;
  }
  function saveAccounts(list){ localStorage.setItem(STORAGE_KEY, JSON.stringify(list)); }

  let accounts = loadAccounts();

  function getSessionUser(){
    try {
      const session = JSON.parse(sessionStorage.getItem(SESSION_KEY) || 'null');
      if (!session) return null;
      return accounts.find(a => a.email === session.email) || null;
    } catch (e) { return null; }
  }
  function setSessionUser(user){
    sessionStorage.setItem(SESSION_KEY, JSON.stringify({ email: user.email }));
  }
  function clearSessionUser(){
    sessionStorage.removeItem(SESSION_KEY);
  }

  let currentUser = getSessionUser();

  /* ======================================================================
     PROFILE HYDRATION (sidebar name + settings page fields, if present)
  ====================================================================== */
  function hydrateProfile(){
    if (!currentUser) return;
    const nameEl = document.querySelector('.profile-name');
    if (nameEl) nameEl.textContent = currentUser.name;
    // The Settings page fields come from Django (settings.html / update_account_view).
  }
  hydrateProfile();

  /* ======================================================================
     LOGIN PAGE
     Django (login_view) checks the credentials. The form is posted with
     fetch() so a failed attempt shows its message without reloading the page:
     the email stays, only the password is cleared. On success the page goes
     where login_view says. Without JavaScript the form still posts normally.
  ====================================================================== */
  const loginForm = document.getElementById('login-form');
  if (loginForm && window.fetch && window.FormData){
    const loginMsg = document.getElementById('login-msg');
    const loginPassword = document.getElementById('login-password');
    const loginBtn = loginForm.querySelector('button[type=submit]');
    loginForm.addEventListener('submit', e => {
      e.preventDefault();
      if (loginBtn.disabled) return;
      loginBtn.disabled = true;
      fetch(loginForm.action, {
        method: 'POST',
        body: new FormData(loginForm),
        credentials: 'same-origin',
        headers: { 'X-Requested-With': 'XMLHttpRequest', Accept: 'application/json' }
      }).then(r => r.json()).then(body => {
        if (body && body.ok && body.redirect){ window.location.href = body.redirect; return; }
        loginBtn.disabled = false;
        const timeout = document.getElementById('login-timeout');
        if (timeout) timeout.remove();
        setMsg(loginMsg, (body && body.error) || 'Could not log in. Please try again.', 'error');
        loginPassword.value = '';
        loginPassword.focus();
      }).catch(() => {
        // network trouble or an unexpected reply: fall back to a normal post
        loginForm.submit();
      });
    });
  }

  /* ======================================================================
     SIGN UP / CREATE ACCOUNT: live password requirements
     Each requirement under a [data-password-rules] password box gets a
     checkmark as soon as the typed password meets it (only a minimum length
     for now), so the account isn't refused for a too-short password.
  ====================================================================== */
  document.querySelectorAll('input[data-password-rules]').forEach(input => {
    const list = document.getElementById(input.getAttribute('aria-describedby'));
    if (!list) return;
    const rules = Array.from(list.querySelectorAll('li[data-min-length]'));
    const check = () => rules.forEach(li => {
      li.classList.toggle('is-met', input.value.length >= Number(li.dataset.minLength));
    });
    input.addEventListener('input', check);
    check();
  });

  /* Forgot / reset password are handled by Django now (forgot_password_view,
     reset_password_view): the reset link is emailed to the user. */

  /* ======================================================================
     SIDEBAR: collapse + logout (present on dashboard/data/feedback/about/settings)
  ====================================================================== */
  const sidebar = document.getElementById('sidebar');
  const collapseBtn = document.getElementById('collapse-btn');
  const isPhone = () => window.matchMedia('(max-width: 720px)').matches;
  const COLLAPSE_KEY = 'ue_sidebar_collapsed';
  if (sidebar){
    // remember the desktop collapse choice between pages (per browser; harmless if storage is blocked)
    try { if (localStorage.getItem(COLLAPSE_KEY) === '1') sidebar.classList.add('is-collapsed'); } catch (e) {}
  }
  if (collapseBtn){
    collapseBtn.addEventListener('click', () => {
      if (isPhone()) { closeNav(); return; }
      const collapsed = sidebar.classList.toggle('is-collapsed');
      try { localStorage.setItem(COLLAPSE_KEY, collapsed ? '1' : '0'); } catch (e) {}
    });
  }

  // Phone width: the red top bar shows the page name (taken from the page's own header, which is then hidden)
  const barTitle = document.querySelector('.mobile-bar-title');
  const pageTitle = document.querySelector('.page-header h1');
  if (barTitle && pageTitle) barTitle.textContent = pageTitle.textContent.trim();

  // Phone-width slide-in menu
  const navOpen = document.getElementById('nav-open');
  const backdrop = document.getElementById('sidebar-backdrop');
  function openNav(){
    sidebar.classList.add('is-open');
    if (backdrop) backdrop.hidden = false;
    if (navOpen) navOpen.setAttribute('aria-expanded', 'true');
    const first = sidebar.querySelector('.nav-item'); if (first) first.focus();
  }
  function closeNav(){
    if (!sidebar || !sidebar.classList.contains('is-open')) return;
    sidebar.classList.remove('is-open');
    if (backdrop) backdrop.hidden = true;
    if (navOpen) { navOpen.setAttribute('aria-expanded', 'false'); navOpen.focus(); }
  }
  if (navOpen && sidebar){
    navOpen.addEventListener('click', openNav);
    if (backdrop) backdrop.addEventListener('click', closeNav);
    document.addEventListener('keydown', e => { if (e.key === 'Escape') closeNav(); });
  }

  const logoutBtn = document.getElementById('logout-btn');
  if (logoutBtn){
    logoutBtn.addEventListener('click', () => {
      clearSessionUser();
      // default <a href> navigation to the login page proceeds normally
    });
  }

  /* ======================================================================
     DASHBOARD TABS
  ====================================================================== */
  const tabs = document.querySelectorAll('.tab');
  if (tabs.length){
    const tabPanels = document.querySelectorAll('.tab-panel');
    tabs.forEach(tab => {
      tab.addEventListener('click', () => {
        tabs.forEach(t => t.classList.remove('is-active'));
        tab.classList.add('is-active');
        tabPanels.forEach(p => p.classList.toggle('is-active', p.id === `tab-${tab.dataset.tab}`));
      });
    });
  }

  /* ======================================================================
     DATASET — used by Dashboard + Data pages only, but cheap to define here
  ====================================================================== */
  const SKILL_POOL = ['Python','SQL','AWS','Azure','Java','C++','R','Tableau','Excel','Spark',
    'Oracle','Networking','MySQL','AWS RDS','PowerBI','NoSQL','PySpark','Snowflake','Hadoop',
    'TensorFlow','Pandas','HTML','Linux','JavaScript','C','Ruby','SAS'];

  function mkJob(id, code, name, start, end, program, skills){
    return { jobID:String(id), jobCode:code, jobName:name, activationDate:start, activationEndDate:end,
      jobDescription:`Provides expert support and delivery for ${name.toLowerCase()} responsibilities...`,
      program, year: start.slice(0,4), skills };
  }

  const rawJobs = [
    mkJob(262778,'data-eng-01','Data Engineer','2026-01-12','2026-12-30','IT',['Python','SQL','Spark','AWS']),
    mkJob(892012,'jr-sw-04','Jr. Software Developer','2026-02-03','2026-11-15','CS',['C++','Java','SQL']),
    mkJob(782192,'db-admin-02','Database Administrator','2026-01-28','2026-12-01','IT',['SQL','AWS','Oracle']),
    mkJob(981472,'db-admin-07','Database Administrator','2026-03-10','2026-12-20','IT',['SQL','Azure','MySQL']),
    mkJob(853921,'sysadmin-03','System Administrator','2026-02-14','2026-11-30','IT',['Python','SQL','Networking']),
    mkJob(110234,'data-an-02','Data Analyst','2025-05-02','2025-12-15','CS',['Python','Tableau','Excel','SQL']),
    mkJob(110987,'cloud-eng-01','Cloud Engineer','2025-06-19','2026-01-30','IT',['AWS','Azure','Python','Linux']),
    mkJob(220456,'ml-eng-01','ML Engineer','2026-01-05','2026-10-31','CS',['Python','TensorFlow','Pandas','SQL']),
    mkJob(220789,'bi-dev-01','BI Developer','2025-08-11','2026-02-28','IT',['SQL','PowerBI','Tableau']),
    mkJob(331120,'fullstack-02','Full-stack Developer','2026-02-20','2026-09-30','CS',['JavaScript','HTML','SQL','Java']),
    mkJob(331555,'net-eng-01','Network Engineer','2025-04-14','2025-11-20','IT',['Networking','Linux','SAS']),
    mkJob(441002,'data-sci-03','Data Scientist','2026-03-01','2026-12-15','CS',['Python','R','Pandas','SQL']),
    mkJob(441777,'devops-01','DevOps Engineer','2025-09-09','2026-03-15','IT',['AWS','Linux','Python','Azure']),
    mkJob(552341,'bi-analyst-02','BI Analyst','2026-01-19','2026-08-30','CS',['SQL','Excel','PowerBI','R']),
    mkJob(552980,'bigdata-01','Big Data Engineer','2025-07-22','2026-01-31','IT',['Spark','Hadoop','Python','SQL']),
    mkJob(663112,'qa-eng-01','QA Engineer','2026-02-08','2026-09-15','CS',['Java','SQL','C++']),
    mkJob(663890,'sec-analyst-01','Security Analyst','2025-05-30','2025-12-31','IT',['Linux','Networking','Python']),
    mkJob(774223,'sw-dev-09','Software Developer','2026-03-15','2026-12-05','CS',['Ruby','SQL','JavaScript']),
    mkJob(774900,'cloud-arch-01','Cloud Architect','2025-10-01','2026-04-30','IT',['AWS','Azure','Snowflake']),
    mkJob(885110,'data-eng-06','Data Engineer','2026-01-25','2026-11-10','IT',['Python','SQL','Spark','Snowflake']),
    mkJob(885670,'app-dev-03','App Developer','2025-06-06','2025-12-20','CS',['Java','SQL','C']),
    mkJob(996201,'analytics-eng-01','Analytics Engineer','2026-02-27','2026-10-15','CS',['SQL','Python','Tableau','Pandas']),
  ];

  const surveys = [
    { surveyID:'0001', faculty:'Sir John', course:'Intro to Programming', courseCode:'CCS1101', program:'CS', year:'2026', skills:['Python'] },
    { surveyID:'0002', faculty:'Dr. Juan', course:'Statistics', courseCode:'CCS2204', program:'CS', year:'2025', skills:['R','SQL'] },
    { surveyID:'0003', faculty:'Ms. Rain', course:'Discrete Structures', courseCode:'CCS2101', program:'CS', year:'2025', skills:['C++'] },
    { surveyID:'0004', faculty:'Mr. Ray', course:'Information Management', courseCode:'CIM 1101', program:'IT', year:'2026', skills:['SQL'] },
    { surveyID:'0005', faculty:'Dr. Juan', course:'Artificial Intelligence', courseCode:'CCS3201', program:'CS', year:'2026', skills:['Python','R','TensorFlow'] },
    { surveyID:'0006', faculty:'Ms. Rain', course:'Information Management', courseCode:'CIM 1101', program:'IT', year:'2025', skills:['SQL'] },
    { surveyID:'0007', faculty:'Dr. Juan', course:'Data Analytics', courseCode:'CDT 1101', program:'IT', year:'2026', skills:['Python','R','Tableau'] },
  ];

  const categoryRows = [
    { categoryID:'000001', category:'Software Development', skill:'C++', frequency:52 },
    { categoryID:'000001', category:'Software Development', skill:'Java', frequency:49 },
    { categoryID:'000001', category:'Software Development', skill:'Python', frequency:42 },
    { categoryID:'000001', category:'Software Development', skill:'SQL', frequency:42 },
    { categoryID:'000001', category:'Software Development', skill:'AWS', frequency:39 },
    { categoryID:'000002', category:'System Administration', skill:'Python', frequency:48 },
    { categoryID:'000002', category:'System Administration', skill:'SQL', frequency:48 },
    { categoryID:'000002', category:'System Administration', skill:'Oracle', frequency:47 },
    { categoryID:'000002', category:'System Administration', skill:'Networking', frequency:42 },
    { categoryID:'000003', category:'Database Management', skill:'SQL', frequency:51 },
    { categoryID:'000003', category:'Database Management', skill:'MySQL', frequency:47 },
    { categoryID:'000003', category:'Database Management', skill:'AWS RDS', frequency:20 },
  ];

  /* ======================================================================
     FILTER STATE + DRAWER (present on Dashboard + Data pages)
  ====================================================================== */
  const filterState = {
    years: new Set(['2025','2026']),
    programs: new Set(['CS','IT']),
    skills: new Set(SKILL_POOL),
  };

  const filterDrawer = document.getElementById('filter-drawer');
  if (filterDrawer){
    const filterBackdrop = document.getElementById('filter-backdrop');
    const openDrawer = () => { filterDrawer.classList.add('is-active'); filterBackdrop.classList.add('is-active'); };
    const closeDrawer = () => { filterDrawer.classList.remove('is-active'); filterBackdrop.classList.remove('is-active'); };

    document.getElementById('filter-btn').addEventListener('click', openDrawer);
    document.getElementById('filter-close').addEventListener('click', closeDrawer);
    filterBackdrop.addEventListener('click', closeDrawer);

    document.getElementById('filter-apply').addEventListener('click', () => {
      readFiltersFromDrawer();
      renderDashboard();
      renderTable(document.getElementById('data-source') ? document.getElementById('data-source').value : 'raw');
      closeDrawer();
      showToast('Filters applied.');
    });

    document.getElementById('filter-clear-all').addEventListener('click', () => {
      filterDrawer.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.checked = false);
    });
    filterDrawer.querySelectorAll('.link-inline--sm').forEach(btn => {
      btn.addEventListener('click', () => {
        btn.closest('.drawer-section').querySelectorAll('input[type="checkbox"]').forEach(cb => cb.checked = false);
      });
    });
  }

  function readFiltersFromDrawer(){
    if (!filterDrawer) return;
    const sections = document.querySelectorAll('#filter-drawer .drawer-section');
    filterState.years = new Set(
      [...sections[0].querySelectorAll('input:checked')].map(cb => cb.nextElementSibling.textContent.trim())
    );
    const programLabels = [...sections[1].querySelectorAll('input:checked')].map(cb => cb.nextElementSibling.textContent.trim());
    filterState.programs = new Set(programLabels.map(p => p.startsWith('Computer') ? 'CS' : 'IT'));
    filterState.skills = new Set(
      [...document.querySelectorAll('#filter-drawer .chip-grid input:checked')].map(cb => cb.nextElementSibling.textContent.trim())
    );
  }

  function filteredJobs(){
    return rawJobs.filter(j =>
      filterState.years.has(j.year) &&
      filterState.programs.has(j.program) &&
      j.skills.some(s => filterState.skills.has(s))
    ).map(j => ({ ...j, skills: j.skills.filter(s => filterState.skills.has(s)) }));
  }
  function filteredSurveys(){
    return surveys.filter(s => filterState.years.has(s.year) && filterState.programs.has(s.program));
  }
  function filteredCategoryRows(){
    return categoryRows.filter(r => filterState.skills.has(r.skill));
  }

  /* ======================================================================
     DASHBOARD RENDERING (only runs if the dashboard's elements exist)
  ====================================================================== */
  function renderDashboard(){
    const totalEl = document.getElementById('stat-total');
    if (!totalEl) return; // not the dashboard page

    // The real figures and charts are drawn by dashboard-skills.js from the extracted data.
  }
  renderDashboard();

  /* ======================================================================
     DATA TABLE RENDERING (only runs if the Data page's table exists)
  ====================================================================== */
  const dataTable = document.getElementById('data-table');
  let currentColumns = [];
  let currentRows = [];

  function buildDataset(sourceKey){
    if (sourceKey === 'raw'){
      const cols = ['jobID','jobCode','jobName','activationDate','activationEndDate','program','jobDescription'];
      const rows = filteredJobs().map(j => [j.jobID, j.jobCode, j.jobName, j.activationDate, j.activationEndDate, j.program, j.jobDescription]);
      return { cols, rows };
    }
    if (sourceKey === 'extracted'){
      const cols = ['jobID','jobTitle','skills'];
      const rows = filteredJobs().map(j => [j.jobID, j.jobName, j.skills.join(', ')]);
      return { cols, rows };
    }
    if (sourceKey === 'survey'){
      const cols = ['surveyID','faculty','course','courseCode','program','skills'];
      const rows = filteredSurveys().map(s => [s.surveyID, s.faculty, s.course, s.courseCode, s.program, s.skills.join(', ')]);
      return { cols, rows };
    }
    const cols = ['categoryID','category','skill','frequency'];
    const rows = filteredCategoryRows().map(r => [r.categoryID, r.category, r.skill, r.frequency]);
    return { cols, rows };
  }

  function renderFilteredRows(){
    const searchInput = document.getElementById('data-search');
    const q = searchInput ? searchInput.value.trim().toLowerCase() : '';
    const rows = q
      ? currentRows.filter(row => row.some(cell => String(cell).toLowerCase().includes(q)))
      : currentRows;

    const thead = `<thead><tr>${currentColumns.map(c => `<th>${c}</th>`).join('')}</tr></thead>`;
    const tbody = rows.length
      ? `<tbody>${rows.map(row => `<tr>${row.map(cell => `<td>${cell}</td>`).join('')}</tr>`).join('')}</tbody>`
      : `<tbody><tr><td colspan="${currentColumns.length}" class="muted">No matching rows.</td></tr></tbody>`;
    dataTable.innerHTML = thead + tbody;
    const tableCount = document.getElementById('table-count');
    if (tableCount) tableCount.textContent = `${rows.length} of ${currentRows.length} rows shown`;
  }

  function renderTable(sourceKey){
    if (!dataTable) return; // not the Data page
    const { cols, rows } = buildDataset(sourceKey);
    currentColumns = cols;
    currentRows = rows;
    renderFilteredRows();
  }

  if (dataTable){
    const dataSourceSelect = document.getElementById('data-source');
    const searchInput = document.getElementById('data-search');

    dataSourceSelect.addEventListener('change', () => {
      searchInput.value = '';
      renderTable(dataSourceSelect.value);
    });
    searchInput.addEventListener('input', renderFilteredRows);

    document.getElementById('export-btn').addEventListener('click', () => {
      const q = searchInput.value.trim().toLowerCase();
      const rows = q ? currentRows.filter(row => row.some(cell => String(cell).toLowerCase().includes(q))) : currentRows;
      const csv = [currentColumns.join(','), ...rows.map(r => r.map(c => `"${String(c).replace(/"/g, '""')}"`).join(','))].join('\n');
      const blob = new Blob([csv], { type: 'text/csv' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${dataSourceSelect.value}-export.csv`;
      a.click();
      URL.revokeObjectURL(url);
      showToast(`Exported ${rows.length} rows to CSV.`);
    });

    renderTable('raw');
  }

  /* ======================================================================
     SETTINGS: inline edit / save / cancel / delete (Settings page only)
  ====================================================================== */
  const editBtn = document.getElementById('edit-btn');
  if (editBtn){
    const cancelBtn = document.getElementById('cancel-edit-btn');
    const settingsMsg = document.getElementById('settings-msg');
    let editing = false;

    function startEdit(){
      editing = true;
      editBtn.textContent = 'Save';
      cancelBtn.hidden = false;
      document.querySelectorAll('[data-editable]').forEach(dd => {
        const type = dd.dataset.type;
        const value = type === 'password' ? (dd.dataset.real || '') : dd.textContent.trim();
        dd.dataset.original = value;
        dd.classList.add('is-editing');
        dd.innerHTML = `<input type="${type === 'password' ? 'text' : type}" value="${value.replace(/"/g, '&quot;')}">`;
      });
    }

    function stopEdit(applyChanges){
      document.querySelectorAll('[data-editable]').forEach(dd => {
        const input = dd.querySelector('input');
        const newVal = input ? input.value.trim() : dd.dataset.original;
        dd.classList.remove('is-editing');
        if (dd.id === 'set-password'){
          dd.dataset.real = applyChanges ? (newVal || dd.dataset.real) : dd.dataset.real;
          dd.textContent = '•'.repeat(Math.max(8, dd.dataset.real.length));
        } else {
          dd.textContent = applyChanges ? (newVal || dd.dataset.original) : dd.dataset.original;
        }
      });
      editing = false;
      editBtn.textContent = 'Edit';
      cancelBtn.hidden = true;
    }

    editBtn.addEventListener('click', () => {
      if (!editing){ startEdit(); return; }

      const newName = document.querySelector('#set-name input').value.trim();
      const newEmail = document.querySelector('#set-email input').value.trim();

      if (!newName || !newEmail){
        setMsg(settingsMsg, 'Name and email cannot be empty.', 'error');
        return;
      }
      if (!currentUser){
        setMsg(settingsMsg, 'You need to be logged in to save changes.', 'error');
        return;
      }
      const emailTaken = accounts.some(a => a.email.toLowerCase() === newEmail.toLowerCase() && a.id !== currentUser.id);
      if (emailTaken){
        setMsg(settingsMsg, 'Another account already uses that email.', 'error');
        return;
      }

      currentUser.name = newName;
      currentUser.email = newEmail;
      const idx = accounts.findIndex(a => a.id === currentUser.id);
      if (idx > -1) accounts[idx] = currentUser;
      saveAccounts(accounts);
      setSessionUser(currentUser);

      stopEdit(true);
      hydrateProfile();
      setMsg(settingsMsg, '');
      showToast('Account changes saved.');
    });

    cancelBtn.addEventListener('click', () => {
      stopEdit(false);
      setMsg(settingsMsg, '');
    });
  }

  const deleteBackdrop = document.getElementById('delete-backdrop');
  if (deleteBackdrop){
    document.getElementById('delete-btn').addEventListener('click', () => deleteBackdrop.classList.add('is-active'));
    document.getElementById('delete-cancel').addEventListener('click', () => deleteBackdrop.classList.remove('is-active'));
    document.getElementById('delete-yes').addEventListener('click', () => {
      if (currentUser){
        accounts = accounts.filter(a => a.id !== currentUser.id);
        saveAccounts(accounts);
      }
      clearSessionUser();
      showToast('Account deleted.');
      goTo('loginUrl');
    });
  }

});
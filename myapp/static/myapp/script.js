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
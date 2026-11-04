/* UEnvision — Light / Dark / System colours.
   The inline script in base.html's <head> already set <html data-theme> before the page drew,
   so there is no flash. This file:
   * keeps "System" in step when the phone / computer switches between light and dark,
   * wires the quick toggle in the top bar ([data-theme-toggle]) and the Settings choices
     ([data-theme-choice] radios),
   * saves the choice in this browser (localStorage) and, when logged in, on the account
     (POST to data-save-url), so it follows the user to other devices.
   Other scripts can listen for the "ue:themechange" event to redraw (e.g. charts). */
(function () {
  'use strict';
  var root = document.documentElement;
  var me = document.currentScript;
  var SAVE_URL = me && me.getAttribute('data-save-url');
  var CSRF = me && me.getAttribute('data-csrf');
  var media = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;

  function pref() {
    var p = root.getAttribute('data-theme-pref');
    return p === 'dark' || p === 'system' ? p : 'light';   // light unless they chose otherwise
  }
  function effective(p) {
    return p === 'dark' || (p === 'system' && media && media.matches) ? 'dark' : 'light';
  }
  function syncControls() {
    var p = pref(), eff = root.getAttribute('data-theme');
    Array.prototype.forEach.call(document.querySelectorAll('[data-theme-toggle]'), function (btn) {
      var next = eff === 'dark' ? 'light' : 'dark';
      btn.setAttribute('aria-label', 'Switch to ' + next + ' mode');
      btn.setAttribute('title', 'Switch to ' + next + ' mode');
      btn.setAttribute('aria-pressed', eff === 'dark' ? 'true' : 'false');
    });
    Array.prototype.forEach.call(document.querySelectorAll('[data-theme-choice]'), function (input) {
      input.checked = input.value === p;
    });
  }
  function apply(p) {
    var eff = effective(p);
    var changed = root.getAttribute('data-theme') !== eff;
    root.setAttribute('data-theme-pref', p);
    root.setAttribute('data-theme', eff);
    root.style.colorScheme = eff;
    syncControls();
    if (changed) {
      try { window.dispatchEvent(new CustomEvent('ue:themechange', { detail: { theme: eff } })); } catch (e) { /* old browser */ }
    }
  }
  function save(p) {
    try { localStorage.setItem('ue_theme', p); } catch (e) { /* storage blocked */ }
    if (!SAVE_URL) return;
    var body = new FormData();
    body.append('theme', p);
    fetch(SAVE_URL, {
      method: 'POST', body: body, credentials: 'same-origin',
      headers: { 'X-CSRFToken': CSRF || '', 'X-Requested-With': 'XMLHttpRequest' }
    }).catch(function () { /* kept in this browser anyway */ });
  }
  function choose(p) { apply(p); save(p); }

  if (media) {
    var onSystemChange = function () { if (pref() === 'system') apply('system'); };
    if (media.addEventListener) media.addEventListener('change', onSystemChange);
    else if (media.addListener) media.addListener(onSystemChange);
  }

  document.addEventListener('click', function (e) {
    var btn = e.target.closest && e.target.closest('[data-theme-toggle]');
    if (!btn) return;
    e.preventDefault();
    choose(root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark');
  });
  document.addEventListener('change', function (e) {
    var input = e.target;
    if (input && input.hasAttribute && input.hasAttribute('data-theme-choice') && input.checked) choose(input.value);
  });

  window.UETheme = { choose: choose, current: function () { return root.getAttribute('data-theme'); } };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', syncControls);
  else syncControls();
})();

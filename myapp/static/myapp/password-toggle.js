/* UEnvision — "show password" eye button on every password box (log in, sign up, register,
   reset password, Settings > Change password, Accounts > Add account).
   Each <input type="password"> is wrapped in .pw-wrap with a type="button" toggle after it,
   so pressing it never submits the form. The button says what it will do in aria-label
   ("Show password" / "Hide password") and aria-pressed tells screen readers the state. */
(function () {
  'use strict';
  var EYE = '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><circle cx="12" cy="12" r="3" fill="none" stroke="currentColor" stroke-width="2"/></svg>';
  var EYE_OFF = '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M2 12s3.6-7 10-7c2 0 3.7.7 5.1 1.6M22 12s-3.6 7-10 7c-2 0-3.7-.7-5.1-1.6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2M3 3l18 18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>';

  function setState(btn, input, shown) {
    input.type = shown ? 'text' : 'password';
    btn.innerHTML = shown ? EYE_OFF : EYE;
    btn.setAttribute('aria-label', shown ? 'Hide password' : 'Show password');
    btn.setAttribute('title', shown ? 'Hide password' : 'Show password');
    btn.setAttribute('aria-pressed', shown ? 'true' : 'false');
  }

  function enhance(input) {
    if (input.dataset.pwToggle) return;
    input.dataset.pwToggle = '1';
    var wrap = document.createElement('span');
    wrap.className = 'pw-wrap';
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'pw-toggle';
    if (input.id) btn.setAttribute('aria-controls', input.id);
    setState(btn, input, false);
    btn.addEventListener('click', function () {
      setState(btn, input, input.type === 'password');
      input.focus();
    });
    wrap.appendChild(btn);
    // Never leave a password readable after the form is sent (e.g. the browser keeps the page in its back/forward cache).
    if (input.form) input.form.addEventListener('submit', function () { setState(btn, input, false); });
  }

  function init(root) {
    Array.prototype.forEach.call((root || document).querySelectorAll('input[type="password"]'), enhance);
  }
  window.UEPasswordToggle = { init: init };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { init(); });
  else init();
})();

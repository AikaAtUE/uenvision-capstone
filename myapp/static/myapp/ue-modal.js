/* UEnvision — small on-page dialog used instead of the browser's alert() / confirm().
   UEModal.confirm({ title, message, okLabel, cancelLabel, danger, okHref }) -> Promise<boolean>
     * resolves true when the main button is pressed, false on Cancel / Close / Esc / backdrop.
     * okHref: the main button is a link (e.g. "Go to survey") instead of a button.
     * hideOk: only the Cancel / Close button is shown.
   Uses the site's .modal-backdrop / .modal styles, so it follows light and dark mode.
   Keyboard: focus moves into the dialog, Tab stays inside it, Esc closes it, and focus goes
   back to whatever was focused before. */
(function () {
  'use strict';
  if (window.UEModal) return;

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  function confirmDialog(opts) {
    opts = opts || {};
    return new Promise(function (resolve) {
      var before = document.activeElement;
      var backdrop = el('div', 'modal-backdrop modal-backdrop--top ue-modal-backdrop is-active');
      var box = el('div', 'modal ue-modal');
      box.setAttribute('role', 'alertdialog');
      box.setAttribute('aria-modal', 'true');
      var id = 'ue-modal-' + Date.now();
      if (opts.title) {
        var h = el('h2', 'ue-modal-title', opts.title);
        h.id = id + '-t';
        box.setAttribute('aria-labelledby', h.id);
        box.appendChild(h);
      }
      var p = el('p', 'ue-modal-text', opts.message || '');
      p.id = id + '-d';
      box.setAttribute(opts.title ? 'aria-describedby' : 'aria-labelledby', p.id);
      box.appendChild(p);

      var actions = el('div', 'modal-actions');
      var ok;
      if (opts.okHref) {
        ok = el('a', 'btn ' + (opts.danger ? 'btn-red' : 'btn-navy'), opts.okLabel || 'OK');
        ok.href = opts.okHref;
      } else {
        ok = el('button', 'btn ' + (opts.danger ? 'btn-red' : 'btn-navy'), opts.okLabel || 'OK');
        ok.type = 'button';
      }
      ok.setAttribute('data-ue-modal-ok', '');
      var cancel = el('button', 'btn btn-ghost', opts.cancelLabel || 'Cancel');
      cancel.type = 'button';
      cancel.setAttribute('data-ue-modal-cancel', '');
      if (!opts.hideOk) actions.appendChild(ok);
      actions.appendChild(cancel);
      box.appendChild(actions);
      backdrop.appendChild(box);
      document.body.appendChild(backdrop);

      var done = false;
      function close(result) {
        if (done) return;
        done = true;
        document.removeEventListener('keydown', onKey, true);
        backdrop.remove();
        if (before && before.focus && document.contains(before)) { try { before.focus(); } catch (e) {} }
        resolve(result);
      }
      function onKey(e) {
        if (e.key === 'Escape') { e.preventDefault(); close(false); return; }
        if (e.key === 'Tab') {
          var items = opts.hideOk ? [cancel] : [ok, cancel];
          var i = items.indexOf(document.activeElement);
          e.preventDefault();
          items[(i + (e.shiftKey ? items.length - 1 : 1)) % items.length].focus();
        }
      }
      ok.addEventListener('click', function () { close(true); });
      cancel.addEventListener('click', function () { close(false); });
      backdrop.addEventListener('click', function (e) { if (e.target === backdrop) close(false); });
      document.addEventListener('keydown', onKey, true);
      (opts.hideOk ? cancel : ok).focus();
    });
  }

  window.UEModal = { confirm: confirmDialog };
})();

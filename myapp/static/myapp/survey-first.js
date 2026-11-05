/* UEnvision — "Please answer the initial survey first" pop-up.
   Loaded (base.html) only for a student / alumni / faculty member who hasn't answered their
   initial survey yet (middleware.survey_first_context). Clicking a link to a page the server
   would bounce back to the survey shows this pop-up instead of a silent redirect. Links the
   server still allows (the survey itself, Settings, Help, About, Log out, ...) work as usual.
   When the server did redirect (it adds ?required=1), the survey page shows the pop-up once. */
(function () {
  'use strict';
  var dataEl = document.getElementById('survey-first');
  if (!dataEl || !window.UEModal) return;
  var cfg = {};
  try { cfg = JSON.parse(dataEl.textContent || '{}') || {}; } catch (e) { return; }
  if (!cfg.url) return;

  function samePath(a, b) { return a.replace(/\/+$/, '') === b.replace(/\/+$/, ''); }
  var allowed = (cfg.allowed || []).map(function (p) { return p.replace(/\/+$/, ''); });
  var onSurvey = samePath(window.location.pathname, cfg.url);
  var open = false;

  function showPopup() {
    if (open) return;
    open = true;
    window.UEModal.confirm({
      title: 'Please answer the initial survey first.',
      message: 'UEnvision needs your answers before it can show your results.',
      okLabel: 'Go to survey',
      cancelLabel: 'Close',
      // already on the survey: only "Close" (a "Go to survey" button would lead nowhere)
      hideOk: onSurvey,
      okHref: onSurvey ? null : cfg.url
    }).then(function () {
      open = false;
    });
  }

  document.addEventListener('click', function (e) {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    var a = e.target.closest && e.target.closest('a[href]');
    if (!a || a.target === '_blank' || a.hasAttribute('download')) return;
    var url;
    try { url = new URL(a.getAttribute('href'), window.location.href); } catch (err) { return; }
    if (url.origin !== window.location.origin) return;            // mailto:, other sites
    var path = url.pathname.replace(/\/+$/, '');
    if (samePath(url.pathname, window.location.pathname)) return;  // #anchors on this page
    if (allowed.indexOf(path) !== -1) return;
    if (path.indexOf('/static/') === 0 || path.indexOf('/media/') === 0) return;
    e.preventDefault();
    showPopup();
  });

  // The server redirected here (?required=1): show it once, then drop the flag so a reload doesn't repeat it.
  var params = new URLSearchParams(window.location.search);
  if (onSurvey && params.get('required') === '1') {
    params.delete('required');
    var rest = params.toString();
    try { window.history.replaceState(null, '', window.location.pathname + (rest ? '?' + rest : '') + window.location.hash); } catch (e) {}
    showPopup();
  }
})();

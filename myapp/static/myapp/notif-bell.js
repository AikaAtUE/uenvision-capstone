// Administrators' notification bell (top right): open/close the dropdown and
// mark notifications as read the first time it's opened.
(function () {
  var bell = document.getElementById('notif-bell');
  if (!bell) return;
  var btn = document.getElementById('notif-bell-btn');
  var panel = document.getElementById('notif-panel');
  var marked = false;

  function csrfToken() {
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    if (m) return decodeURIComponent(m[1]);
    var input = bell.querySelector('input[name=csrfmiddlewaretoken]') || document.querySelector('input[name=csrfmiddlewaretoken]');
    return input ? input.value : '';
  }

  function open() {
    panel.hidden = false;
    btn.setAttribute('aria-expanded', 'true');
    bell.classList.add('is-open');
    if (!marked && document.getElementById('notif-bell-count')) {
      marked = true;
      fetch(bell.dataset.readUrl, { method: 'POST', credentials: 'same-origin',
        headers: { 'Accept': 'application/json', 'X-CSRFToken': csrfToken() } })
        .then(function (r) {
          if (!r.ok) return;
          var count = document.getElementById('notif-bell-count');
          if (count) count.remove();
          bell.classList.remove('has-unread');
          btn.setAttribute('aria-label', 'Notifications');
        }).catch(function () { marked = false; });
    }
  }
  function close() {
    panel.hidden = true;
    btn.setAttribute('aria-expanded', 'false');
    bell.classList.remove('is-open');
  }

  btn.addEventListener('click', function (e) {
    e.stopPropagation();
    if (panel.hidden) open(); else close();
  });
  document.addEventListener('click', function (e) { if (!panel.hidden && !bell.contains(e.target)) close(); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && !panel.hidden) { close(); btn.focus(); } });
})();

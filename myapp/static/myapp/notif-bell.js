// Administrators' notification bell (top right): open/close the dropdown, mark
// notifications as read when it's opened, and check for new ones every few seconds
// while the tab is visible so they show up without a refresh.
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
          setCount(0);
        }).catch(function () { marked = false; });
    }
  }

  function setCount(n) {
    var count = document.getElementById('notif-bell-count');
    if (n > 0) {
      if (!count) {
        count = document.createElement('span');
        count.className = 'notif-bell-count';
        count.id = 'notif-bell-count';
        btn.appendChild(count);
      }
      count.textContent = n > 99 ? '99+' : String(n);
      btn.setAttribute('aria-label', 'Notifications, ' + n + ' unread');
    } else {
      if (count) count.remove();
      btn.setAttribute('aria-label', 'Notifications');
    }
  }

  // Live updates. The X-Background-Request header tells the server this isn't the
  // user doing something, so polling never keeps an idle session alive.
  var POLL_MS = 15000;
  var polling = false;
  function poll() {
    if (polling || document.visibilityState !== 'visible') return;
    polling = true;
    var url = bell.dataset.pollUrl + '?page=' + encodeURIComponent(location.pathname + location.search);
    fetch(url, { credentials: 'same-origin', headers: { 'Accept': 'application/json', 'X-Background-Request': '1' } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data) return;
        // the CSRF token differs on every render, so leave it out when checking for changes
        var strip = function (h) { return h.replace(/name="csrfmiddlewaretoken" value="[^"]*"/g, ''); };
        if (strip(panel.innerHTML) !== strip(data.html)) panel.innerHTML = data.html;
        if (!panel.hidden && data.unread > 0) {
          // the dropdown is open, so the new ones are being seen right now
          marked = false;
          setCount(data.unread);
          open();
        } else {
          setCount(data.unread);
          if (data.unread > 0) marked = false;
        }
      })
      .catch(function () {})
      .then(function () { polling = false; });
  }
  setInterval(poll, POLL_MS);
  document.addEventListener('visibilitychange', poll);
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

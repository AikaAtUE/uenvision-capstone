// Idle timeout (all roles). While this tab is open and visible on screen the user
// counts as active, so we ping the server every few minutes to keep the session.
// When the tab is hidden (another tab, minimized browser, locked screen) nothing
// is sent, so after 30 minutes away the server (IdleTimeoutMiddleware) logs the
// user out. Coming back to the tab after that reloads it into the login screen.
(function () {
  var me = document.currentScript;
  if (!me) return;
  var TIMEOUT_MS = (parseInt(me.dataset.timeout, 10) || 1800) * 1000;
  var PING_URL = me.dataset.pingUrl;
  var LOGIN_URL = me.dataset.loginUrl;
  var PING_EVERY_MS = Math.min(5 * 60 * 1000, TIMEOUT_MS / 3);
  var STORE_KEY = 'uenvision-last-active';  // shared by open tabs

  var lastSeen = Date.now();  // last moment this tab was visible
  var lastPing = Date.now();  // loading this page already counted as activity

  function readShared() {
    try { return parseInt(localStorage.getItem(STORE_KEY), 10) || 0; } catch (e) { return 0; }
  }
  function writeShared(t) {
    try { localStorage.setItem(STORE_KEY, String(t)); } catch (e) { /* private mode */ }
  }

  function csrfToken() {
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : (me.dataset.csrf || '');
  }

  function ping() {
    lastPing = Date.now();
    fetch(PING_URL, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Accept': 'application/json', 'X-CSRFToken': csrfToken() }
    }).then(function (r) {
      if (r.status === 401) window.location.href = LOGIN_URL;
    }).catch(function () { /* offline: try again on the next tick */ });
  }

  function tick() {
    if (document.hidden) return;
    var now = Date.now();
    lastSeen = now;
    writeShared(now);
    if (now - lastPing >= PING_EVERY_MS) ping();
  }

  document.addEventListener('visibilitychange', function () {
    if (document.hidden) { lastSeen = Date.now(); writeShared(lastSeen); return; }
    var away = Date.now() - Math.max(lastSeen, readShared());
    if (away > TIMEOUT_MS) {
      // Away for too long: reload and let the server send us to the login page
      // (another visible tab may have kept the session alive, then this is just a refresh).
      window.location.reload();
    } else {
      tick();
      ping();
    }
  });

  writeShared(lastSeen);
  setInterval(tick, Math.min(30 * 1000, PING_EVERY_MS / 2));
})();

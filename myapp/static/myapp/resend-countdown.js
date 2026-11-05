/* UEnvision — "Resend" buttons that wait before they can be pressed again.
   <button data-countdown="30" data-label="Resend link"> starts disabled, says "Resend in 30s",
   counts down every second and turns on at 0. The server enforces the same wait
   (email_verification.RESEND_WAIT_SECONDS), so this only saves a wasted click. */
(function () {
  'use strict';
  Array.prototype.forEach.call(document.querySelectorAll('[data-countdown]'), function (btn) {
    var left = parseInt(btn.getAttribute('data-countdown'), 10) || 0;
    var label = btn.getAttribute('data-label') || btn.textContent;
    var statusId = btn.getAttribute('aria-describedby');
    var status = statusId && document.getElementById(statusId);
    function draw() {
      if (left > 0) {
        btn.disabled = true;
        btn.textContent = 'Resend in ' + left + 's';
      } else {
        btn.disabled = false;
        btn.textContent = label;
        if (status) status.textContent = 'You can send it again now.';
      }
    }
    draw();
    if (left <= 0) return;
    var timer = setInterval(function () {
      left -= 1;
      draw();
      if (left <= 0) clearInterval(timer);
    }, 1000);
  });
})();

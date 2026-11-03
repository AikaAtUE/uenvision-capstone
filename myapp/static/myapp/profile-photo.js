/* UEnvision — Settings: profile picture. Crops the chosen picture to a square, shrinks it
   to 256x256 JPEG in the browser (so uploads stay small), then submits #photo-form. */
(function () {
  'use strict';
  var form = document.getElementById('photo-form');
  if (!form) return;
  var input = document.getElementById('photo-input');
  var msg = document.getElementById('photo-msg');
  var SIZE = 256;

  document.getElementById('photo-pick').addEventListener('click', function () { input.click(); });

  input.addEventListener('change', function () {
    var file = input.files && input.files[0];
    if (!file) return;
    if (!/^image\//.test(file.type)) { msg.textContent = 'Please choose a picture (JPEG or PNG).'; return; }
    msg.textContent = 'Uploading…';
    var img = new Image();
    var url = URL.createObjectURL(file);
    img.onload = function () {
      var side = Math.min(img.naturalWidth, img.naturalHeight);
      var canvas = document.createElement('canvas');
      canvas.width = canvas.height = SIZE;
      var ctx = canvas.getContext('2d');
      ctx.fillStyle = '#fff';
      ctx.fillRect(0, 0, SIZE, SIZE);
      ctx.drawImage(img, (img.naturalWidth - side) / 2, (img.naturalHeight - side) / 2, side, side, 0, 0, SIZE, SIZE);
      URL.revokeObjectURL(url);
      canvas.toBlob(function (blob) {
        if (!blob) { msg.textContent = 'That picture could not be read. Please try another one.'; return; }
        var data = new FormData();
        data.append('csrfmiddlewaretoken', form.querySelector('input[name=csrfmiddlewaretoken]').value);
        data.append('photo', blob, 'photo.jpg');
        fetch(form.action, { method: 'POST', body: data, credentials: 'same-origin' })
          .then(function () { window.location.reload(); })
          .catch(function () { msg.textContent = 'Upload failed. Please check your connection and try again.'; });
      }, 'image/jpeg', 0.85);
    };
    img.onerror = function () { URL.revokeObjectURL(url); msg.textContent = 'That picture could not be read. Please try another one.'; };
    img.src = url;
  });
})();

/* Recommendations page: "Generate selected" POSTs to /recommendations/generate/
   for the checked skills only (so simply opening the page never calls Gemini),
   then drops the returned resource cards into that skill's slot. */
(function () {
  'use strict';
  var form = document.getElementById('rec-form');
  if (!form) return;

  var btn = document.getElementById('rec-generate-btn');
  var status = document.getElementById('rec-status');
  var errEl = document.getElementById('rec-error');
  var DEFAULT_PHOTO = window.__recDefaultPhoto || '';

  function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); }

  function cardEl(r) {
    var card = document.createElement('div'); card.className = 'rec-card';
    var img = document.createElement('img'); img.className = 'rec-card-img'; img.alt = '';
    img.src = r.photo || DEFAULT_PHOTO;
    img.addEventListener('error', function () { img.onerror = null; img.src = DEFAULT_PHOTO; });
    var body = document.createElement('div'); body.className = 'rec-card-body';
    var type = document.createElement('span'); type.className = 'pill rec-card-type'; type.textContent = r.type;
    var a = document.createElement('a'); a.className = 'rec-card-name'; a.href = r.link;
    a.target = '_blank'; a.rel = 'noopener noreferrer'; a.textContent = r.name;
    body.appendChild(type); body.appendChild(a);
    if (r.provider) {
      var p = document.createElement('span'); p.className = 'muted rec-card-provider'; p.textContent = r.provider;
      body.appendChild(p);
    }
    card.appendChild(img); card.appendChild(body);
    return card;
  }

  function findSlot(skill) {
    var slots = form.querySelectorAll('.rec-resources');
    for (var i = 0; i < slots.length; i++) {
      if (slots[i].getAttribute('data-skill-slot') === skill) return slots[i];
    }
    return null;
  }

  function ensureDownloadLink() {
    if (document.querySelector('.rec-download')) return;
    var p = document.createElement('p'); p.className = 'rec-download';
    var a = document.createElement('a'); a.className = 'btn btn-ghost btn-sm';
    a.href = window.__recDownloadUrl; a.textContent = 'Download CSV';
    p.appendChild(a);
    form.parentNode.insertBefore(p, form.nextSibling);
  }

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var checked = Array.prototype.slice.call(form.querySelectorAll('input[name="skills"]:checked'));
    if (!checked.length) { errEl.textContent = 'Choose at least one skill.'; return; }
    errEl.textContent = '';
    btn.disabled = true;
    var prevText = btn.textContent;
    btn.textContent = 'Generating…';
    status.textContent = 'Calling Gemini for ' + checked.length + ' skill(s) — this can take a little while.';

    var fd = new FormData(form);
    fetch(window.__recGenerateUrl, {
      method: 'POST', body: fd, credentials: 'same-origin', headers: { Accept: 'application/json' },
    })
      .then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (body) { return { ok: r.ok, body: body }; });
      })
      .then(function (res) {
        btn.disabled = false; btn.textContent = prevText;
        if (!res.ok || !res.body || res.body.ok !== true) {
          errEl.textContent = (res.body && res.body.error) || 'Could not reach the server.';
          status.textContent = '';
          return;
        }
        var results = res.body.results || {};
        var errors = res.body.errors || {};
        var okSkills = Object.keys(results);
        var failSkills = Object.keys(errors);

        okSkills.forEach(function (skill) {
          var slot = findSlot(skill);
          if (!slot) return;
          clear(slot);
          results[skill].forEach(function (r) { slot.appendChild(cardEl(r)); });
          var row = slot.closest('.rec-skill');
          var head = row && row.querySelector('.rec-skill-head');
          if (head && !head.querySelector('.rec-pill-generated')) {
            var pill = document.createElement('span'); pill.className = 'pill rec-pill-generated'; pill.textContent = 'generated';
            head.appendChild(pill);
          }
        });

        var msgs = [];
        if (okSkills.length) msgs.push(okSkills.length + ' skill(s) updated.');
        if (failSkills.length) {
          msgs.push(failSkills.length + ' failed: ' + failSkills.map(function (s) { return s + ' (' + errors[s] + ')'; }).join('; '));
        }
        status.textContent = msgs.join(' ');
        if (okSkills.length) ensureDownloadLink();
      })
      .catch(function () {
        btn.disabled = false; btn.textContent = prevText;
        errEl.textContent = 'Could not reach the server. Try again.';
        status.textContent = '';
      });
  });
})();

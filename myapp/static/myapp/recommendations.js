/* Recommendations page (and the student/alumni dashboard, which reuses it with its
   own window.__recGenerateUrl): "Generate selected" POSTs to /recommendations/generate/
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
  var MAX = parseInt(form.getAttribute('data-max'), 10) || 0;
  var VERB = form.getAttribute('data-verb') || 'Generate';
  var busy = false;

  function boxes() { return Array.prototype.slice.call(form.querySelectorAll('input[name="skills"]')); }
  function checkedBoxes() { return boxes().filter(function (b) { return b.checked; }); }

  /* Only as many skills as one run allows start out checked, and the button says
     how many will be sent, so nothing is silently dropped past the limit. */
  function syncSelection() {
    if (busy) return;
    var n = checkedBoxes().length;
    btn.disabled = n === 0;
    btn.textContent = n ? VERB + ' for ' + n + ' skill' + (n === 1 ? '' : 's') : 'Select skills below';
    boxes().forEach(function (b) {
      var full = MAX && n >= MAX && !b.checked;
      b.disabled = full;
      var row = b.closest('.rec-skill');
      if (row) { row.classList.toggle('is-selected', b.checked); row.classList.toggle('is-maxed', full); }
    });
  }
  if (MAX) {
    var seen = 0;
    boxes().forEach(function (b) { if (b.checked && ++seen > MAX) b.checked = false; });
  }
  form.addEventListener('change', function (e) { if (e.target.name === 'skills') syncSelection(); });
  var clearBtn = document.getElementById('rec-clear');
  if (clearBtn) clearBtn.addEventListener('click', function () {
    boxes().forEach(function (b) { b.checked = false; });
    syncSelection();
  });
  syncSelection();

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
    if (r.verified === 'link checked') {
      var check = document.createElement('span'); check.className = 'rec-card-check'; check.textContent = '\u2713 Link checked';
      body.appendChild(check);
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
    if (!window.__recDownloadUrl || document.querySelector('.rec-download')) return;
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
    busy = true;
    btn.disabled = true;
    btn.textContent = 'Searching…';
    checked.forEach(function (b) {
      var slot = findSlot(b.value);
      if (slot) slot.classList.add('is-loading');
    });
    function done() {
      busy = false;
      Array.prototype.forEach.call(form.querySelectorAll('.rec-resources.is-loading'), function (s) { s.classList.remove('is-loading'); });
      syncSelection();
    }
    status.textContent = 'Calling Gemini for ' + checked.length + ' skill(s) — this can take a little while.';

    var fd = new FormData(form);
    fetch(window.__recGenerateUrl, {
      method: 'POST', body: fd, credentials: 'same-origin', headers: { Accept: 'application/json' },
    })
      .then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (body) { return { ok: r.ok, body: body }; });
      })
      .then(function (res) {
        done();
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
        var keyErrors = res.body.key_errors || [];
        if (keyErrors.length) {
          msgs.push('API key problems: ' + keyErrors.map(function (k) { return k.key + ' (' + k.error + ')'; }).join('; '));
        }
        status.textContent = msgs.join(' ');
        if (okSkills.length) ensureDownloadLink();
      })
      .catch(function () {
        done();
        errEl.textContent = 'Could not reach the server. Try again.';
        status.textContent = '';
      });
  });
})();

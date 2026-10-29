/* UEnvision — Student / Alumni / Professor curriculum-mapping surveys.
   Each page embeds its data as <script type="application/json" id="cs-bootstrap">
   (built server-side in views.py) and a form with a matching id. This file reads
   that, renders the dynamic subject/skill pickers, and POSTs the finished answers
   to bootstrap.submitUrl — following the same CSRF + fetch + localStorage-fallback
   pattern as survey.js on the Feedback page. */
(function () {
  'use strict';

  var bootstrapEl = document.getElementById('cs-bootstrap');
  if (!bootstrapEl) return;
  var BOOT = {};
  try { BOOT = JSON.parse(bootstrapEl.textContent || '{}'); } catch (e) { BOOT = {}; }

  /* ---------- Data Privacy consent: a second checkbox above Submit ---------- */
  // Some respondents scroll past the notice at the top and miss its checkbox, so the same
  // checkbox is repeated near the Submit button. Ticking either one ticks both.
  Array.prototype.forEach.call(document.querySelectorAll('input[data-mirror]'), function (copy) {
    var main = document.getElementById(copy.getAttribute('data-mirror'));
    if (!main) return;
    copy.checked = main.checked;
    copy.addEventListener('change', function () { main.checked = copy.checked; });
    main.addEventListener('change', function () { copy.checked = main.checked; });
  });

  /* ---------- shared helpers ---------- */
  function qs(sel, root) { return (root || document).querySelector(sel); }
  function qsa(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  function escapeHtml(str) {
    return String(str == null ? '' : str).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  var toastTimer = null;
  function showToast(message, isError) {
    var toast = qs('#toast');
    if (!toast) return;
    toast.textContent = message;
    toast.classList.toggle('is-error', !!isError);
    toast.classList.add('is-active');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toast.classList.remove('is-active'); }, 3200);
  }
  function setFormError(id, msg) {
    var p = document.getElementById(id);
    if (!p) return;
    p.textContent = msg || '';
    p.hidden = !msg;
  }
  // Suggestions are per subject code: BSIT and BSCS share some subjects, and a
  // shared code is the same subject whichever program it's taken in.
  function skillsFor(program, code) {
    return (BOOT.skills && BOOT.skills[code]) || [];
  }

  function csrfToken() {
    var tokenInput = qs('input[name=csrfmiddlewaretoken]');
    return tokenInput ? tokenInput.value : '';
  }

  function postJson(url, payload) {
    return fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
      credentials: 'same-origin',
      body: JSON.stringify(payload)
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (body) { return { ok: r.ok, body: body }; });
    });
  }

  /* onSuccess(body) runs after the server saved the answers. A validation error
     from the server is shown on the form (onError); only a network failure falls
     back to keeping the answers in this browser. */
  function submitPayload(url, form, payload, onSuccess, onError) {
    var btn = qs('button[type=submit]', form);
    if (btn) btn.disabled = true;
    postJson(url, payload).then(function (res) {
      if (btn) btn.disabled = false;
      if (!res.ok || !res.body || res.body.ok !== true) {
        var msg = (res.body && res.body.error) || 'The server could not save your answers. Please try again.';
        if (onError) onError(msg); else showToast(msg, true);
        return;
      }
      onSuccess(res.body);
    }).catch(function (err) {
      if (btn) btn.disabled = false;
      try {
        var key = 'ue_curriculum_survey_fallback';
        var existing = JSON.parse(localStorage.getItem(key) || '[]');
        existing.push(Object.assign({}, payload, { _savedAt: new Date().toISOString(), _error: String(err) }));
        localStorage.setItem(key, JSON.stringify(existing));
      } catch (e) { /* storage unavailable */ }
      showToast('Could not reach the server, so your answers were saved on this device instead. Please tell us if this keeps happening.', true);
      onSuccess({});
    });
  }

  /* Student / alumni thank-you: point them to registration (or their dashboard). */
  function showLearnerDone(form, body) {
    if (body && body.next_url) { window.location.href = body.next_url; return; }
    form.hidden = true;
    var done = qs('#cs-done');
    done.hidden = false;
    if (body && body.register_url) {
      var p = document.createElement('p');
      p.textContent = 'Want to see how your skills compare with what employers ask for, plus learning resources picked for your gaps? Create your account to see your results.';
      var a = document.createElement('a');
      a.className = 'btn btn-red'; a.href = body.register_url; a.textContent = 'Create my account and see my results';
      done.appendChild(p); done.appendChild(a);
    }
    window.scrollTo(0, 0);
  }

  /* ---------- skill picker (shared by all three surveys) ----------
     A tag input: one text box per subject. Focusing it lists the skills
     suggested for the subject; typing filters those and searches the skills
     ontology (+ custom skills), with an "add as a new skill" option when
     nothing matches. A chosen skill becomes a fixed box (its name can't be
     edited) with a level select and an × to remove it.
     `levelOptions` is an array of {value,label} — proficiency levels for
     Student/Alumni, I/P/A for Professor. With a single option there is no
     select. Returns an API object the caller uses to read the chosen skills. */
  var MAX_LOCAL_MATCHES = 8;

  function buildSkillPicker(container, suggestedNames, levelOptions, idPrefix, initial) {
    var askLevel = levelOptions.length > 1;
    var optionsHtml = '<option value="">Choose level…</option>' + levelOptions.map(function (o) {
      return '<option value="' + escapeHtml(o.value) + '">' + escapeHtml(o.label) + '</option>';
    }).join('');

    var listId = idPrefix + '-options';
    container.innerHTML =
      '<div class="cs-tagbox">' +
        '<div class="cs-chips"></div>' +
        '<input type="text" class="cs-tag-input" autocomplete="off" role="combobox" aria-expanded="false"' +
          ' aria-controls="' + escapeHtml(listId) + '" aria-autocomplete="list"' +
          ' placeholder="' + (suggestedNames.length ? 'Type a skill or pick from the suggestions' : 'Type to search for a skill (e.g. Docker, Excel, UML)') + '"' +
          ' aria-label="Add a skill">' +
      '</div>' +
      '<div class="cs-skill-results" id="' + escapeHtml(listId) + '" role="listbox" hidden></div>';

    var box = qs('.cs-tagbox', container);
    var chips = qs('.cs-chips', container);
    var input = qs('.cs-tag-input', container);
    var resultsBox = qs('.cs-skill-results', container);
    var searchTimer = null, searchSeq = 0, active = -1;
    var quiet = false;   // focus moved here by the picker itself: don't pop the list open

    function focusQuietly() { quiet = true; input.focus(); quiet = false; }

    function chosen() {
      return qsa('.cs-chip', chips).map(function (c) { return c.dataset.skill; });
    }
    function isChosen(name) {
      var low = name.toLowerCase();
      return chosen().some(function (n) { return n.toLowerCase() === low; });
    }

    // `level` / `silent` are used when filling in skills already saved (My subjects & skills)
    function addChip(name, level, silent) {
      if (!silent) { input.value = ''; closeResults(); }
      if (isChosen(name)) { if (!silent) focusQuietly(); return; }
      var known = levelOptions.some(function (o) { return o.value === level; });
      var chip = document.createElement('span');
      chip.className = 'cs-chip';
      chip.dataset.skill = name;
      chip.dataset.level = askLevel ? (known ? level : '') : levelOptions[0].value;
      chip.innerHTML = '<span class="cs-chip-name">' + escapeHtml(name) + '</span>' +
        (askLevel ? '<select class="cs-chip-level" aria-label="Level for ' + escapeHtml(name) + '">' + optionsHtml + '</select>' : '') +
        '<button type="button" class="cs-chip-remove" aria-label="Remove ' + escapeHtml(name) + '">×</button>';
      chips.appendChild(chip);
      var sel = qs('.cs-chip-level', chip);
      if (sel && known) sel.value = level;
      if (silent) return;
      if (sel) sel.focus(); else focusQuietly();
      container.dispatchEvent(new Event('change', { bubbles: true }));
    }
    (initial || []).forEach(function (s) { if (s && s.name) addChip(String(s.name), String(s.level || '').toLowerCase(), true); });

    function closeResults() {
      resultsBox.hidden = true; resultsBox.innerHTML = ''; active = -1;
      input.setAttribute('aria-expanded', 'false');
    }
    function optionButtons() { return qsa('.cs-skill-result', resultsBox); }
    function setActive(i) {
      var opts = optionButtons();
      if (!opts.length) return;
      active = (i + opts.length) % opts.length;
      opts.forEach(function (b, j) { b.classList.toggle('is-active', j === active); });
      opts[active].scrollIntoView({ block: 'nearest' });
    }

    function render(query, serverResults) {
      var low = query.toLowerCase();
      var names = [];
      var aliases = {};   // lower-case name -> the synonym that matched ("JS" for JavaScript)
      var exactHit = false;
      function push(n) {
        if (!n || isChosen(n)) return;
        if (names.some(function (x) { return x.toLowerCase() === n.toLowerCase(); })) return;
        names.push(n);
      }
      var server = serverResults || [];
      server.forEach(function (r) {
        if (r.synonym) aliases[r.name.toLowerCase()] = r.synonym;
        if (r.exact) exactHit = true;
      });
      // an exact name/synonym match first, then the subject's own suggestions, then the rest of the search
      server.filter(function (r) { return r.exact; }).forEach(function (r) { push(r.name); });
      suggestedNames.filter(function (n) { return !low || n.toLowerCase().indexOf(low) !== -1; })
        .slice(0, low ? MAX_LOCAL_MATCHES : suggestedNames.length).forEach(push);
      server.forEach(function (r) { push(r.name); });

      var html = '';
      if (!low && names.length) html += '<div class="cs-skill-results-head">Suggested for this subject</div>';
      html += names.map(function (n) {
        var alias = aliases[n.toLowerCase()];
        return '<button type="button" class="cs-skill-result" role="option" tabindex="-1" data-name="' + escapeHtml(n) + '">' + escapeHtml(n) +
          (alias ? ' <span class="cs-skill-alias">also called ' + escapeHtml(alias) + '</span>' : '') + '</button>';
      }).join('');
      var exact = low && (exactHit || names.some(function (n) { return n.toLowerCase() === low; }) || isChosen(query));
      if (low && !exact && serverResults && BOOT.skillAddUrl) {
        html += '<button type="button" class="cs-skill-result cs-skill-result--new" role="option" tabindex="-1" data-new="' + escapeHtml(query) + '">' +
          (names.length ? 'Not listed? ' : 'Not in the skills list. ') + 'Add “' + escapeHtml(query) + '” as a new skill</button>';
      }
      resultsBox.innerHTML = html;
      resultsBox.hidden = !html;
      input.setAttribute('aria-expanded', html ? 'true' : 'false');
      active = -1;
      if (low && optionButtons().length) setActive(0);
    }

    function refresh() {
      var query = input.value.trim();
      render(query, null);   // local suggestions right away
      if (!query || !BOOT.skillSearchUrl) return;
      var my = ++searchSeq;
      fetch(BOOT.skillSearchUrl + '?q=' + encodeURIComponent(query), { credentials: 'same-origin', headers: { Accept: 'application/json' } })
        .then(function (r) { return r.json(); })
        .then(function (body) { if (my === searchSeq && input.value.trim() === query) render(query, (body && body.results) || []); })
        .catch(function () { if (my === searchSeq && input.value.trim() === query) render(query, []); });
    }

    function addNewSkill(name) {
      postJson(BOOT.skillAddUrl, { name: name }).then(function (res) {
        if (!res.ok || !res.body || res.body.ok !== true) {
          showToast((res.body && res.body.error) || 'Could not add that skill.', true);
          return;
        }
        addChip(res.body.name);
        if (res.body.created) showToast('“' + res.body.name + '” was added to the skills list.');
      }).catch(function () { showToast('Could not reach the server.', true); });
    }
    function pick(button) {
      if (button.hasAttribute('data-new')) addNewSkill(button.getAttribute('data-new'));
      else addChip(button.getAttribute('data-name'));
    }

    box.addEventListener('click', function (e) {
      if (e.target === box || e.target === chips) { input.focus(); if (resultsBox.hidden) refresh(); }
    });
    input.addEventListener('focus', function () { if (!quiet) refresh(); });
    input.addEventListener('input', function () {
      clearTimeout(searchTimer);
      render(input.value.trim(), null);
      searchTimer = setTimeout(refresh, 200);
    });
    input.addEventListener('keydown', function (e) {
      var opts = optionButtons();
      if (e.key === 'ArrowDown') { e.preventDefault(); if (resultsBox.hidden) refresh(); else setActive(active + 1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); setActive(active - 1); }
      else if (e.key === 'Enter') {
        e.preventDefault();   // never submit the whole survey from here
        if (!resultsBox.hidden && opts.length) pick(opts[active >= 0 ? active : 0]);
      } else if (e.key === 'Escape') {
        closeResults();
      } else if (e.key === 'Backspace' && !input.value) {
        var last = chips.lastElementChild;
        if (last) last.remove();
      }
    });
    // mousedown (not click) so the input doesn't blur and close the list first
    resultsBox.addEventListener('mousedown', function (e) {
      var b = e.target.closest('.cs-skill-result');
      if (!b) return;
      e.preventDefault();
      pick(b);
    });
    input.addEventListener('blur', function () {
      setTimeout(function () { if (document.activeElement !== input) closeResults(); }, 120);
    });
    chips.addEventListener('click', function (e) {
      var x = e.target.closest('.cs-chip-remove');
      if (!x) return;
      x.closest('.cs-chip').remove();
      focusQuietly();
      container.dispatchEvent(new Event('change', { bubbles: true }));
    });
    chips.addEventListener('change', function (e) {
      if (!e.target.classList.contains('cs-chip-level')) return;
      e.target.classList.remove('is-missing');
      e.target.closest('.cs-chip').dataset.level = e.target.value;   // drives the chip's color
    });

    return {
      collect: function () {
        return qsa('.cs-chip', chips).map(function (chip) {
          var sel = qs('.cs-chip-level', chip);
          return { name: chip.dataset.skill, level: sel ? sel.value : levelOptions[0].value };
        });
      }
    };
  }

  /* Every chosen skill needs a level before submitting. Marks the empty ones and
     returns an error message, or '' when all are set. */
  function missingLevelError(form) {
    var empty = qsa('.cs-chip-level', form).filter(function (s) { return !s.value; });
    empty.forEach(function (s) { s.classList.add('is-missing'); });
    if (!empty.length) return '';
    empty[0].focus();
    return 'Please choose a level for every skill you added (' +
      empty.map(function (s) { return s.closest('.cs-chip').dataset.skill; }).slice(0, 3).join(', ') +
      (empty.length > 3 ? ', …' : '') + ').';
  }

  var PROFICIENCY_LEVELS = [
    { value: 'beginner', label: 'Beginner' },
    { value: 'intermediate', label: 'Intermediate' },
    { value: 'advanced', label: 'Advanced' },
    { value: 'expert', label: 'Expert' }
  ];
  var IPA_LEVELS = [
    { value: 'introduced', label: 'Introduced' },
    { value: 'practiced', label: 'Practiced' },
    { value: 'applied', label: 'Applied' }
  ];

  // Subject codes contain spaces ("CCP 1101"), which can't go into an element id as-is.
  function domId(s) { return String(s).replace(/[^A-Za-z0-9_-]/g, '_'); }

  function isUeEmail(email) {
    var domain = (BOOT.ueEmailDomain || 'ue.edu.ph').toLowerCase();
    var at = email.lastIndexOf('@');
    if (at < 1) return false;
    var host = email.slice(at + 1).toLowerCase();
    return host === domain || host.slice(-(domain.length + 1)) === '.' + domain;
  }

  /* Where a subject sits in the curriculum: "Y1S1IT" = 1st year, 1st semester, BSIT
     (S3 = summer). Blue for BSIT, green for BSCS, darker for higher years.
     `program` limits it to one curriculum (students/alumni see only their own). */
  function termTagsHtml(code, program) {
    var tags = ((BOOT.termTags || {})[code] || []).filter(function (t) { return !program || t.program === program; });
    if (!tags.length) return '';
    return '<span class="cs-term-tags">' + tags.map(function (t) {
      return '<span class="cs-term-tag cs-term-tag--' + t.program.toLowerCase() + ' cs-term-tag--y' + t.year + '">' + escapeHtml(t.tag) + '</span>';
    }).join('') + '</span>';
  }

  /* "Find a subject" box: hides the subject checkboxes that don't match, per
     grid, and says so when a grid has none left. Matches inside a closed
     <details> (earlier semesters) open it. */
  function wireSubjectFilter(root, input) {
    function apply() {
      var q = input.value.trim().toLowerCase();
      qsa('.cs-subject-grid', root).forEach(function (grid) {
        var shown = 0;
        qsa('.cs-subject-check', grid).forEach(function (lab) {
          var hit = !q || lab.textContent.toLowerCase().indexOf(q) !== -1;
          lab.classList.toggle('is-filtered-out', !hit);
          if (hit) shown++;
        });
        var note = grid.nextElementSibling && grid.nextElementSibling.classList.contains('cs-no-match') ? grid.nextElementSibling : null;
        if (shown && note) note.remove();
        if (!shown) {
          if (!note) { grid.insertAdjacentHTML('afterend', '<p class="cs-no-match"></p>'); note = grid.nextElementSibling; }
          note.textContent = 'No subject here matches “' + input.value.trim() + '”.';
        }
        var details = grid.closest('details');
        if (details && q && shown) details.open = true;
      });
    }
    input.addEventListener('input', apply);
    return apply;
  }

  /* "Add a subject that isn't listed" (professors): code + title + whether it has
     BSIT/BSCS students. A subject with neither is skipped, not added.
     opts: { knownCodes: [...], isTaken: fn(code), onAdd: fn({code, name, programs}) } */
  function buildOtherSubjectForm(container, opts) {
    var uid = 'cs-other-' + Math.random().toString(36).slice(2, 8);
    container.innerHTML =
      '<div class="cs-other">' +
        '<button type="button" class="btn btn-ghost btn-sm cs-other-toggle">+ Add a subject that isn\'t listed</button>' +
        '<div class="cs-other-form" hidden>' +
          '<p class="muted">For example, the Professional Elective you handle. Only subjects taken by BSIT or BSCS students are part of this survey.</p>' +
          '<div class="cs-other-fields">' +
            '<label class="field"><span>Subject code</span><input type="text" class="cs-other-code" maxlength="20" placeholder="e.g. CIT 4101" autocomplete="off"></label>' +
            '<label class="field cs-other-name-wrap"><span>Subject title</span><input type="text" class="cs-other-name" maxlength="120" placeholder="e.g. Cloud Computing" autocomplete="off"></label>' +
          '</div>' +
          '<fieldset class="cs-other-programs"><legend>Does this subject have BSIT or BSCS students?</legend>' +
            '<label><input type="radio" name="' + uid + '" value="BSIT"> Yes, BSIT students</label>' +
            '<label><input type="radio" name="' + uid + '" value="BSCS"> Yes, BSCS students</label>' +
            '<label><input type="radio" name="' + uid + '" value="both"> Yes, both</label>' +
            '<label><input type="radio" name="' + uid + '" value="none"> No, neither</label>' +
          '</fieldset>' +
          '<p class="cs-other-skip" hidden>Then please skip this subject. This survey only covers subjects taken by BSIT or BSCS students.</p>' +
          '<p class="form-msg form-msg--error cs-other-error" hidden></p>' +
          '<div class="cs-other-actions"><button type="button" class="btn btn-navy btn-sm cs-other-add">Add subject</button>' +
          '<button type="button" class="link-inline cs-other-cancel">Cancel</button></div>' +
        '</div>' +
      '</div>';
    var toggle = qs('.cs-other-toggle', container);
    var formEl = qs('.cs-other-form', container);
    var codeIn = qs('.cs-other-code', container);
    var nameIn = qs('.cs-other-name', container);
    var skip = qs('.cs-other-skip', container);
    var err = qs('.cs-other-error', container);
    var addBtn = qs('.cs-other-add', container);
    var known = {};
    (opts.knownCodes || []).forEach(function (c) { known[c] = true; });

    function choice() { var r = qs('input[name="' + uid + '"]:checked', container); return r ? r.value : ''; }
    function showError(msg) { err.textContent = msg; err.hidden = !msg; }
    function open(show) {
      formEl.hidden = !show;
      toggle.hidden = show;
      if (show) codeIn.focus();
    }
    function reset() {
      codeIn.value = ''; nameIn.value = '';
      qsa('input[type=radio]', container).forEach(function (r) { r.checked = false; });
      skip.hidden = true; addBtn.disabled = false; showError('');
    }
    function add() {
      var code = codeIn.value.toUpperCase().split(/\s+/).filter(Boolean).join(' ');
      var name = nameIn.value.trim().split(/\s+/).join(' ');
      var pick = choice();
      if (!/^[A-Z0-9][A-Z0-9 \-]{1,19}$/.test(code)) { showError('Enter the subject code, e.g. CIT 4101.'); codeIn.focus(); return; }
      if (known[code]) { showError(code + ' is already in the curriculum list. For an elective, use the elective\'s own subject code.'); codeIn.focus(); return; }
      if (opts.isTaken(code)) { showError('You already added ' + code + '.'); codeIn.focus(); return; }
      if (name.length < 2) { showError('Enter the subject title.'); nameIn.focus(); return; }
      if (!pick) { showError('Say whether this subject has BSIT or BSCS students.'); return; }
      if (pick === 'none') return;
      opts.onAdd({ code: code, name: name, programs: pick === 'both' ? ['BSIT', 'BSCS'] : [pick] });
      reset();
      open(false);
    }

    toggle.addEventListener('click', function () { open(true); });
    qs('.cs-other-cancel', container).addEventListener('click', function () { reset(); open(false); });
    addBtn.addEventListener('click', add);
    container.addEventListener('change', function (e) {
      if (e.target.type !== 'radio') return;
      var none = choice() === 'none';
      skip.hidden = !none;
      addBtn.disabled = none;
      showError('');
    });
    [codeIn, nameIn].forEach(function (inp) {
      inp.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); add(); } });
    });
  }

  function addedTag(programs) {
    return '<span class="cs-added-tag">Added by you' + (programs && programs.length ? ' · ' + escapeHtml(programs.join(', ')) : '') + '</span>';
  }

  /* =====================================================================
     STUDENT SURVEY
  ===================================================================== */
  (function initStudentSurvey() {
    var form = document.getElementById('student-survey-form');
    if (!form) return;

    var programSel = qs('#student-program', form);
    var yearSel = qs('#student-year', form);
    var currentWrap = qs('#student-current-subjects', form);
    var previousWrap = qs('#student-previous-subjects', form);
    var earlierWrap = qs('#student-earlier-subjects', form);
    var blocksWrap = qs('#student-subject-blocks', form);
    var pickers = {}; // code -> { api, term }
    var tools = qs('#student-subject-tools', form);
    var hint = qs('#student-hint', form);
    var filterInput = qs('#student-subject-filter', form);
    var pickedCount = qs('#student-picked-count', form);
    var applyFilter = filterInput ? wireSubjectFilter(form, filterInput) : function () {};
    function updatePickedCount() {
      if (!pickedCount) return;
      var n = Object.keys(pickers).length;
      pickedCount.textContent = n ? n + ' subject' + (n === 1 ? '' : 's') + ' selected' : 'No subjects selected yet';
    }
    function showTools(show) {
      if (tools) tools.hidden = !show;
      if (hint) hint.hidden = show;
      updatePickedCount();
    }

    function subjectCheckHtml(subj, bucket, termKey) {
      return '<label class="cs-subject-check">' +
        '<input type="checkbox" class="cs-subject-pick" value="' + escapeHtml(subj.code) + '" data-bucket="' + bucket + '" data-term-key="' + escapeHtml(termKey) + '">' +
        '<span class="cs-subject-text"><span><span class="cs-subject-code">' + escapeHtml(subj.code) + '</span>' + escapeHtml(subj.name) +
        ' <span class="cs-subject-units">(' + subj.units + ' units)</span></span>' + termTagsHtml(subj.code, programSel.value) + '</span>' +
      '</label>';
    }

    function termGrid(term, bucket) {
      return '<div class="cs-subject-grid">' + term.subjects.map(function (subj) {
        return subjectCheckHtml(subj, bucket, term.term_key);
      }).join('') + '</div>';
    }

    function currentElig() {
      return ((BOOT.eligibility || {})[programSel.value] || {})[yearSel.value];
    }

    function renderSubjectGroups() {
      var program = programSel.value;
      var year = yearSel.value;
      blocksWrap.innerHTML = '';
      pickers = {};
      earlierWrap.innerHTML = '';
      if (!program || !year) {
        currentWrap.innerHTML = '';
        previousWrap.innerHTML = '';
        showTools(false);
        return;
      }
      var elig = currentElig();
      if (!elig) {
        currentWrap.innerHTML = '<p class="cs-section--empty">That combination isn\'t in the curriculum catalog.</p>';
        previousWrap.innerHTML = '';
        showTools(false);
        return;
      }
      showTools(true);
      currentWrap.innerHTML =
        '<h3>Current semester subjects <span class="muted">(' + escapeHtml(elig.current.term_label) + ' — ' + escapeHtml(BOOT.currentSemLabel) + ')</span></h3>' +
        '<p class="muted">Select the subjects you are taking this semester. At least one is required.</p>' +
        termGrid(elig.current, 'current');

      if (elig.previous) {
        previousWrap.innerHTML =
          '<h3>Previous semester subjects <span class="muted">(' + escapeHtml(elig.previous.term_label) + ')</span></h3>' +
          '<p class="muted">Select the subjects you took in your last regular semester' +
            ((elig.previous_summer || []).length ? ' and the summer term after it' : '') + '. At least one is required.</p>' +
          termGrid(elig.previous, 'previous') +
          (elig.previous_summer || []).map(function (term) {
            return '<h4>' + escapeHtml(term.term_label) + '</h4>' + termGrid(term, 'previous');
          }).join('');
      } else {
        previousWrap.innerHTML = '<p class="cs-section--empty">This is your first semester at UE, so there is no previous semester to report.</p>';
      }

      if (elig.earlier && elig.earlier.length) {
        earlierWrap.innerHTML =
          '<details class="cs-earlier"><summary>+ Also report subjects from earlier semesters (optional)</summary>' +
          elig.earlier.map(function (term) {
            return '<h4>' + escapeHtml(term.term_label) + '</h4>' + termGrid(term, 'earlier');
          }).join('') +
          '</details>';
      }
      applyFilter();
    }

    function addSubjectBlock(code, name, program, termLabel, termBucket) {
      var blockId = 'cs-subj-' + domId(code);
      blocksWrap.insertAdjacentHTML('beforeend',
        '<div class="cs-subject-block" id="' + blockId + '" data-code="' + escapeHtml(code) + '" data-term="' + termBucket + '">' +
          '<h4>' + escapeHtml(code) + ' — ' + escapeHtml(name) + '</h4>' +
          '<p class="cs-subject-term">' + escapeHtml(termLabel) + '</p>' +
          '<div class="cs-skill-picker"></div>' +
        '</div>'
      );
      var container = qs('#' + blockId + ' .cs-skill-picker');
      var api = buildSkillPicker(container, skillsFor(program, code), PROFICIENCY_LEVELS, blockId);
      pickers[code] = { api: api, name: name, termLabel: termLabel, termBucket: termBucket };
    }

    function removeSubjectBlock(code) {
      var el = document.getElementById('cs-subj-' + domId(code));
      if (el) el.remove();
      delete pickers[code];
    }

    [currentWrap, previousWrap, earlierWrap].forEach(function (wrap) {
      wrap.addEventListener('change', function (e) {
        if (!e.target.classList.contains('cs-subject-pick')) return;
        var elig = currentElig();
        var bucket = e.target.getAttribute('data-bucket');
        var termKey = e.target.getAttribute('data-term-key');
        var terms = bucket === 'earlier' ? elig.earlier
          : bucket === 'previous' ? [elig.previous].concat(elig.previous_summer || []) : [elig[bucket]];
        var term = terms.filter(function (t) { return t.term_key === termKey; })[0];
        var subj = term.subjects.filter(function (s) { return s.code === e.target.value; })[0];
        if (e.target.checked) {
          addSubjectBlock(subj.code, subj.name, programSel.value, term.term_label, bucket);
        } else {
          removeSubjectBlock(subj.code);
        }
        updatePickedCount();
      });
    });

    programSel.addEventListener('change', renderSubjectGroups);
    yearSel.addEventListener('change', renderSubjectGroups);

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      setFormError('student-error', '');
      var levelError = missingLevelError(form);
      if (levelError) { setFormError('student-error', levelError); return; }

      var name = qs('#student-name', form).value.trim();
      var email = qs('#student-email', form).value.trim();
      var course = programSel.value;
      var studentNumber = qs('#student-number', form).value.trim();
      var year = yearSel.value;
      var consent = qs('#student-consent', form).checked;

      if (!name || !email || !course || !studentNumber || !year) {
        setFormError('student-error', 'Please fill in every personal info field.');
        return;
      }
      if (!isUeEmail(email)) {
        setFormError('student-error', 'Please use your UE email address (ending in @' + (BOOT.ueEmailDomain || 'ue.edu.ph') + ').');
        return;
      }
      if (!consent) {
        setFormError('student-error', 'Please tick “I have read the Data Privacy Notice” just above the Submit button.');
        return;
      }
      var currentChecked = qsa('.cs-subject-pick:checked', currentWrap);
      if (!currentChecked.length) {
        setFormError('student-error', 'Please select at least one current-semester subject.');
        return;
      }
      var hasPrevious = !!(currentElig() || {}).previous;
      if (hasPrevious && !qsa('.cs-subject-pick:checked', previousWrap).length) {
        setFormError('student-error', 'Please select at least one previous-semester subject.');
        return;
      }

      var subjects = Object.keys(pickers).map(function (code) {
        var p = pickers[code];
        return { code: code, name: p.name, term: p.termBucket, term_label: p.termLabel, skills: p.api.collect() };
      });

      var payload = {
        consent: true,
        personal_info: { name: name, ue_email: email, course: course, student_number: studentNumber, year_level: Number(year) },
        has_previous: hasPrevious,
        target_role: BOOT.targetRole || '',
        subjects: subjects
      };

      submitPayload(BOOT.submitUrl, form, payload, function (body) {
        showLearnerDone(form, body);
      }, function (msg) { setFormError('student-error', msg); });
    });
  })();

  /* =====================================================================
     ALUMNI SURVEY
  ===================================================================== */
  (function initAlumniSurvey() {
    var form = document.getElementById('alumni-survey-form');
    if (!form) return;

    var programSel = qs('#alumni-program', form);
    var termSel = qs('#alumni-term', form);
    var subjectsWrap = qs('#alumni-subjects', form);
    var blocksWrap = qs('#alumni-subject-blocks', form);
    var overallWrap = qs('#alumni-overall-skills', form);
    var pickers = {};
    var overallPicker = null;

    function subjectCheckHtml(subj) {
      return '<label class="cs-subject-check">' +
        '<input type="checkbox" class="cs-subject-pick" value="' + escapeHtml(subj.code) + '">' +
        '<span class="cs-subject-text"><span><span class="cs-subject-code">' + escapeHtml(subj.code) + '</span>' + escapeHtml(subj.name) +
        ' <span class="cs-subject-units">(' + subj.units + ' units)</span></span>' + termTagsHtml(subj.code, programSel.value) + '</span>' +
      '</label>';
    }

    function renderTermOptions() {
      var program = programSel.value;
      var terms = (BOOT.termsByProgram || {})[program] || [];
      termSel.innerHTML = terms.map(function (t) {
        return '<option value="' + t.key + '">' + escapeHtml(t.label) + '</option>';
      }).join('');
      if (terms.length) termSel.value = terms[terms.length - 1].key; // default: the final term
      renderSubjects();
      renderOverallSkills();
    }

    function renderSubjects() {
      blocksWrap.innerHTML = '';
      pickers = {};
      var program = programSel.value;
      var termKey = termSel.value;
      if (!program || !termKey) { subjectsWrap.innerHTML = ''; return; }
      var subjects = ((BOOT.subjectsByProgramTerm || {})[program] || {})[termKey] || [];
      var terms = (BOOT.termsByProgram || {})[program] || [];
      var termLabel = (terms.filter(function (t) { return t.key === termKey; })[0] || {}).label || termKey;
      subjectsWrap.innerHTML =
        '<h3>Subjects from your last semester <span class="muted">(' + escapeHtml(termLabel) + ')</span></h3>' +
        '<p class="muted">Select every subject you took in that term.</p>' +
        '<div class="cs-subject-grid">' + subjects.map(subjectCheckHtml).join('') + '</div>';
    }

    function addSubjectBlock(code, name, program, termLabel) {
      var blockId = 'cs-asubj-' + domId(code);
      blocksWrap.insertAdjacentHTML('beforeend',
        '<div class="cs-subject-block" id="' + blockId + '" data-code="' + escapeHtml(code) + '">' +
          '<h4>' + escapeHtml(code) + ' — ' + escapeHtml(name) + '</h4>' +
          '<p class="cs-subject-term">' + escapeHtml(termLabel) + '</p>' +
          '<div class="cs-skill-picker"></div>' +
        '</div>'
      );
      var container = qs('#' + blockId + ' .cs-skill-picker');
      var api = buildSkillPicker(container, skillsFor(program, code), PROFICIENCY_LEVELS, blockId);
      pickers[code] = { api: api, name: name, termLabel: termLabel };
    }
    function removeSubjectBlock(code) {
      var el = document.getElementById('cs-asubj-' + domId(code));
      if (el) el.remove();
      delete pickers[code];
    }

    subjectsWrap.addEventListener('change', function (e) {
      if (!e.target.classList.contains('cs-subject-pick')) return;
      var program = programSel.value;
      var termKey = termSel.value;
      var subjects = ((BOOT.subjectsByProgramTerm || {})[program] || {})[termKey] || [];
      var terms = (BOOT.termsByProgram || {})[program] || [];
      var termLabel = (terms.filter(function (t) { return t.key === termKey; })[0] || {}).label || termKey;
      var subj = subjects.filter(function (s) { return s.code === e.target.value; })[0];
      if (e.target.checked) addSubjectBlock(subj.code, subj.name, program, termLabel);
      else removeSubjectBlock(subj.code);
    });

    function renderOverallSkills() {
      var program = programSel.value;
      if (!program) { overallWrap.innerHTML = ''; overallPicker = null; return; }
      var codes = [];
      var byTerm = (BOOT.subjectsByProgramTerm || {})[program] || {};
      Object.keys(byTerm).forEach(function (termKey) {
        byTerm[termKey].forEach(function (s) { codes.push(s.code); });
      });
      var names = [];
      codes.forEach(function (code) {
        skillsFor(program, code).forEach(function (n) { if (names.indexOf(n) === -1) names.push(n); });
      });
      overallWrap.innerHTML =
        '<h3>Overall skills learned throughout your stay at UE</h3>' +
        '<p class="muted">Not tied to one subject — the skills you feel you came away from the whole program with.</p>' +
        '<div class="cs-skill-picker" id="alumni-overall-picker"></div>';
      overallPicker = buildSkillPicker(qs('#alumni-overall-picker', overallWrap), names.slice(0, 24), PROFICIENCY_LEVELS, 'alumni-overall');
    }

    programSel.addEventListener('change', renderTermOptions);
    termSel.addEventListener('change', function () { renderSubjects(); });

    /* ---- employment branch ---- */
    var employedRadios = qsa('input[name="alumni-employed"]', form);
    var employedBranch = qs('#alumni-employed-branch', form);
    var unemployedBranch = qs('#alumni-unemployed-branch', form);
    employedRadios.forEach(function (r) {
      r.addEventListener('change', function () {
        var isEmployed = r.value === 'yes' && r.checked;
        employedBranch.hidden = !isEmployed;
        unemployedBranch.hidden = isEmployed;
      });
    });
    var upskillRadios = qsa('input[name="alumni-upskilling"]', form);
    var upskillBranch = qs('#alumni-upskilling-branch', form);
    upskillRadios.forEach(function (r) {
      r.addEventListener('change', function () {
        upskillBranch.hidden = !(r.value === 'yes' && r.checked);
      });
    });

    function tagInput(inputId, listId) {
      var input = document.getElementById(inputId);
      var list = document.getElementById(listId);
      var values = [];
      function render() {
        list.innerHTML = values.map(function (v, i) {
          return '<span class="checkbox" style="display:inline-flex;margin:2px 4px 2px 0;padding:4px 10px;border-radius:999px;border:1px solid #d5d3cc;">' +
            escapeHtml(v) + ' <button type="button" data-i="' + i + '" style="margin-left:6px;border:none;background:none;cursor:pointer;">&times;</button></span>';
        }).join('');
      }
      input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') {
          e.preventDefault();
          var v = input.value.trim();
          if (v) { values.push(v); input.value = ''; render(); }
        }
      });
      list.addEventListener('click', function (e) {
        var i = e.target.getAttribute('data-i');
        if (i != null) { values.splice(Number(i), 1); render(); }
      });
      return { get: function () { return values.slice(); } };
    }
    var skillsToLearnTags = tagInput('alumni-skills-to-learn-input', 'alumni-skills-to-learn-list');
    var upskillTags = tagInput('alumni-upskilling-input', 'alumni-upskilling-list');

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      setFormError('alumni-error', '');
      var levelError = missingLevelError(form);
      if (levelError) { setFormError('alumni-error', levelError); return; }

      var name = qs('#alumni-name', form).value.trim();
      var email = qs('#alumni-email', form).value.trim();
      var course = programSel.value;
      var studentNumber = qs('#alumni-number', form).value.trim();
      var yearGraduated = qs('#alumni-year-graduated', form).value.trim();
      var consent = qs('#alumni-consent', form).checked;

      if (email && !isUeEmail(email)) {
        setFormError('alumni-error', 'Please use your UE email address (ending in @' + (BOOT.ueEmailDomain || 'ue.edu.ph') + ').');
        return;
      }
      if (!name || !email || !course || !studentNumber || !yearGraduated) {
        setFormError('alumni-error', 'Please fill in every personal info field.');
        return;
      }
      if (!consent) {
        setFormError('alumni-error', 'Please tick “I have read the Data Privacy Notice” just above the Submit button.');
        return;
      }
      var subjectChecks = qsa('.cs-subject-pick:checked', subjectsWrap);
      if (!subjectChecks.length) {
        setFormError('alumni-error', 'Please select at least one subject from your last semester.');
        return;
      }
      var employedChoice = (employedRadios.filter(function (r) { return r.checked; })[0] || {}).value;
      if (!employedChoice) {
        setFormError('alumni-error', 'Please answer whether you are currently employed.');
        return;
      }

      var subjects = Object.keys(pickers).map(function (code) {
        var p = pickers[code];
        return { code: code, name: p.name, term_label: p.termLabel, skills: p.api.collect() };
      });

      var employment;
      if (employedChoice === 'yes') {
        var appliedPicker = window.__alumniAppliedPicker;
        employment = {
          status: 'employed',
          current_role: qs('#alumni-role', form).value.trim(),
          first_job_applied: (qsa('input[name="alumni-first-job"]:checked', form)[0] || {}).value === 'yes',
          skills_applied: appliedPicker ? appliedPicker.collect().map(function (s) { return s.name; }) : [],
          skills_to_learn: skillsToLearnTags.get()
        };
      } else {
        var jobsApplied = qs('#alumni-jobs-applied', form).value.trim();
        var rejectionReason = qs('#alumni-rejection-reason', form).value.trim();
        var upskillingChoice = (upskillRadios.filter(function (r) { return r.checked; })[0] || {}).value === 'yes';
        employment = {
          status: 'unemployed',
          jobs_applied: jobsApplied ? Number(jobsApplied) : null,
          rejection_reason: rejectionReason || null,
          upskilling: upskillingChoice,
          upskilling_skills: upskillingChoice ? upskillTags.get() : []
        };
      }

      var payload = {
        consent: true,
        personal_info: { name: name, ue_email: email, course: course, student_number: studentNumber, year_graduated: yearGraduated },
        target_role: BOOT.targetRole || '',
        last_semester: { program: course, term_key: termSel.value, term_label: (((BOOT.termsByProgram || {})[course] || []).filter(function (t) { return t.key === termSel.value; })[0] || {}).label },
        subjects: subjects,
        overall_skills: overallPicker ? overallPicker.collect() : [],
        employment: employment
      };

      submitPayload(BOOT.submitUrl, form, payload, function (body) {
        showLearnerDone(form, body);
      }, function (msg) { setFormError('alumni-error', msg); });
    });

    /* "skills applied" picker for the employed branch, built from the same
       overall-skill pool once the program is known */
    programSel.addEventListener('change', function () {
      var program = programSel.value;
      var wrap = qs('#alumni-skills-applied-picker', form);
      if (!wrap) return;
      if (!program) { wrap.innerHTML = ''; window.__alumniAppliedPicker = null; return; }
      var codes = [];
      var byTerm = (BOOT.subjectsByProgramTerm || {})[program] || {};
      Object.keys(byTerm).forEach(function (termKey) { byTerm[termKey].forEach(function (s) { codes.push(s.code); }); });
      var names = [];
      codes.forEach(function (code) { skillsFor(program, code).forEach(function (n) { if (names.indexOf(n) === -1) names.push(n); }); });
      window.__alumniAppliedPicker = buildSkillPicker(wrap, names.slice(0, 24), [{ value: 'applied', label: 'Applied' }], 'alumni-applied');
    });
  })();

  /* =====================================================================
     PROFESSOR SURVEY
  ===================================================================== */
  (function initProfessorSurvey() {
    var form = document.getElementById('professor-survey-form');
    if (!form) return;

    // The survey is also the professor's editable record: BOOT.record holds their
    // saved subjects (null on a first visit), which are pre-filled below.
    var pickers = {};
    var blocksWrap = qs('#professor-subject-blocks');
    var statusEl = document.getElementById('professor-status');
    var saveBtn = document.getElementById('professor-save');
    var editing = !!BOOT.record;
    var dirty = false;
    var poolOf = {};   // code -> {subj, poolKey}
    ['current', 'previous_semester', 'previous_summer'].forEach(function (key) {
      (((BOOT.pools || {})[key]) || []).forEach(function (subj) { if (!poolOf[subj.code]) poolOf[subj.code] = { subj: subj, poolKey: key }; });
    });

    function markDirty() {
      if (dirty || !editing) return;
      dirty = true;
      if (statusEl) { statusEl.textContent = 'Unsaved changes'; statusEl.classList.add('is-dirty'); }
    }

    function subjectCheckHtml(subj) {
      return '<label class="cs-subject-check">' +
        '<input type="checkbox" class="cs-subject-pick" value="' + escapeHtml(subj.code) + '">' +
        '<span class="cs-subject-text"><span><span class="cs-subject-code">' + escapeHtml(subj.code) + '</span>' + escapeHtml(subj.name) + '</span>' +
        termTagsHtml(subj.code) + '</span>' +
      '</label>';
    }

    /* One "skills per subject" block. extra: {tag html, removable, custom, programs, termLabel, bucket} */
    function addBlock(code, name, skills, extra) {
      if (pickers[code]) return;
      var blockId = 'cs-psubj-' + domId(code);
      blocksWrap.insertAdjacentHTML('beforeend',
        '<div class="cs-subject-block" id="' + blockId + '" data-code="' + escapeHtml(code) + '">' +
          '<div class="ms-subject-head"><h4>' + escapeHtml(code) + ' — ' + escapeHtml(name) + (extra.tag ? ' ' + extra.tag : '') + '</h4>' +
          (extra.removable ? '<button type="button" class="ms-remove-subject cs-remove-added">Remove subject</button>' : '') + '</div>' +
          '<div class="cs-skill-picker"></div>' +
        '</div>'
      );
      var block = document.getElementById(blockId);
      var api = buildSkillPicker(qs('.cs-skill-picker', block), extra.custom ? [] : skillsFor('', code), IPA_LEVELS, blockId, skills || []);
      pickers[code] = { api: api, name: name, programs: extra.programs || [], code: code,
                        termLabel: extra.termLabel || '', bucket: extra.bucket || '', custom: !!extra.custom };
      return block;
    }
    function removeBlock(code) {
      var el = document.getElementById('cs-psubj-' + domId(code));
      if (el) el.remove();
      delete pickers[code];
    }

    function renderPool(wrapId, poolKey) {
      var wrap = document.getElementById(wrapId);
      if (!wrap) return;
      var pool = ((BOOT.pools || {})[poolKey]) || [];
      wrap.innerHTML = '<div class="cs-subject-grid">' + pool.map(subjectCheckHtml).join('') + '</div>';
      wrap.addEventListener('change', function (e) {
        if (!e.target.classList.contains('cs-subject-pick')) return;
        var code = e.target.value;
        var subj = pool.filter(function (s) { return s.code === code; })[0];
        if (e.target.checked) {
          addBlock(code, subj.name, [], { programs: subj.programs, termLabel: subj.term_label, bucket: poolKey });
        } else {
          var n = pickers[code] ? pickers[code].api.collect().length : 0;
          if (n && !window.confirm('Remove ' + code + ' and its ' + n + ' skill' + (n === 1 ? '' : 's') + ' from your record?')) {
            e.target.checked = true;
            return;
          }
          removeBlock(code);
        }
      });
    }

    // filter box + running count over every subject list on the page
    var filterInput = document.getElementById('professor-subject-filter');
    var pickedCount = document.getElementById('professor-picked-count');
    function updatePickedCount() {
      if (!pickedCount) return;
      var n = Object.keys(pickers).length;
      pickedCount.textContent = n ? n + ' subject' + (n === 1 ? '' : 's') + ' selected' : 'No subjects selected yet';
    }
    if (filterInput) wireSubjectFilter(form, filterInput);
    form.addEventListener('change', function (e) {
      if (e.target.classList.contains('cs-subject-pick')) updatePickedCount();
      if (e.target === filterInput || e.target.classList.contains('cs-tag-input') || e.target.closest('.cs-other') || e.target.id === 'professor-consent' || e.target.hasAttribute('data-mirror')) return;
      markDirty();
    });

    function addCustom(subj, skills) {
      var block = addBlock(subj.code, subj.name, skills, { tag: addedTag(subj.programs), removable: true, custom: true,
                                                           programs: subj.programs, termLabel: 'Added by you', bucket: 'added' });
      updatePickedCount();
      return block;
    }

    // subjects that aren't in the lists (electives and the like)
    var otherWrap = document.getElementById('professor-other-subject');
    if (otherWrap) {
      buildOtherSubjectForm(otherWrap, {
        knownCodes: BOOT.knownCodes,
        isTaken: function (code) { return !!pickers[code]; },
        onAdd: function (subj) {
          var block = addCustom(subj, []);
          markDirty();
          block.scrollIntoView({ block: 'nearest' });
          var inp = qs('.cs-tag-input', block); if (inp) inp.focus();
        }
      });
    }
    blocksWrap.addEventListener('click', function (e) {
      var btn = e.target.closest('.cs-remove-added');
      if (!btn) return;
      var block = btn.closest('.cs-subject-block');
      var code = block.getAttribute('data-code');
      var n = pickers[code] ? pickers[code].api.collect().length : 0;
      if (n && !window.confirm('Remove ' + code + ' and its ' + n + ' skill' + (n === 1 ? '' : 's') + ' from your record?')) return;
      removeBlock(code);
      updatePickedCount();
      markDirty();
    });

    renderPool('professor-current-subjects', 'current');
    renderPool('professor-previous-subjects', 'previous_semester');
    renderPool('professor-summer-subjects', 'previous_summer');

    // pre-fill the saved record
    (BOOT.record || []).forEach(function (s) {
      if (s.custom) {
        addCustom({ code: s.code, name: s.name, programs: s.programs || [] }, s.skills);
      } else if (poolOf[s.code]) {
        var box = qsa('.cs-subject-pick', form).filter(function (c) { return c.value === s.code; })[0];
        if (box) box.checked = true;
        var hit = poolOf[s.code];
        addBlock(s.code, hit.subj.name, s.skills, { programs: hit.subj.programs, termLabel: hit.subj.term_label, bucket: hit.poolKey });
      } else {
        // reported before, but not offered in this or last semester: kept until removed
        addBlock(s.code, s.name, s.skills, { tag: '<span class="cs-added-tag">From your record</span>', removable: true });
      }
    });
    updatePickedCount();

    window.addEventListener('beforeunload', function (e) {
      if (!dirty) return;
      e.preventDefault();
      e.returnValue = '';
    });

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      setFormError('professor-error', '');
      var levelError = missingLevelError(form);
      if (levelError) { setFormError('professor-error', levelError); return; }

      var consentBox = qs('#professor-consent', form);
      if (consentBox && !consentBox.checked) {
        setFormError('professor-error', 'Please tick “I have read the Data Privacy Notice” just above the Submit button.');
        return;
      }
      var subjectKeys = qsa('.cs-subject-block', blocksWrap).map(function (b) { return b.getAttribute('data-code'); });
      if (!subjectKeys.length) {
        setFormError('professor-error', 'Please select at least one subject you currently teach or taught last semester.');
        return;
      }

      var subjects = subjectKeys.map(function (key) {
        var p = pickers[key];
        var out = { code: p.code, name: p.name, programs: p.programs, term_label: p.termLabel, term_bucket: p.bucket, skills: p.api.collect() };
        if (p.custom) out.custom = true;
        return out;
      });

      // consent is given once; later saves carry it forward
      var payload = { consent: true, subjects: subjects };
      if (saveBtn) saveBtn.textContent = 'Saving…';

      submitPayload(BOOT.submitUrl, form, payload, function (body) {
        if (saveBtn) saveBtn.textContent = editing ? 'Save changes' : 'Submit survey';
        if (!body || body.ok !== true) return;   // offline fallback: nothing saved on the server
        dirty = false;
        if (body.created) {
          showToast('Thank you! Your subjects and skills were saved. You can edit them here any time.');
          setTimeout(function () { window.location.reload(); }, 1200);
          return;
        }
        if (statusEl) { statusEl.classList.remove('is-dirty'); statusEl.textContent = 'Saved just now'; }
        showToast('Your subjects and skills were saved.');
      }, function (msg) {
        if (saveBtn) saveBtn.textContent = editing ? 'Save changes' : 'Submit survey';
        setFormError('professor-error', msg);
      });
    });
  })();

  /* =====================================================================
     MY SUBJECTS & SKILLS (students / alumni, logged in): the survey record,
     editable any time. Saves the whole list back over the latest response.
  ===================================================================== */
  (function initMySkills() {
    var form = document.getElementById('my-skills-form');
    if (!form || BOOT.mode !== 'my_skills') return;

    var list = document.getElementById('ms-subjects');
    var addSel = document.getElementById('ms-add-subject');
    var emptyHint = document.getElementById('ms-no-subjects');
    var statusEl = document.getElementById('ms-status');
    var saveBtn = document.getElementById('ms-save');
    var pickers = {};          // code -> picker api
    var names = {};            // code -> subject name
    var custom = {};           // code -> {name, programs} for subjects a professor added themselves
    var dirty = false;

    (BOOT.subjectOptions || []).forEach(function (g) {
      g.subjects.forEach(function (s) { names[s.code] = s.name; });
    });

    function markDirty() {
      if (dirty) return;
      dirty = true;
      statusEl.textContent = 'Unsaved changes';
      statusEl.classList.add('is-dirty');
    }

    function refreshAddOptions() {
      var html = '<option value="">Choose a subject to add…</option>';
      (BOOT.subjectOptions || []).forEach(function (g) {
        var opts = g.subjects.filter(function (s) { return !pickers[s.code]; });
        if (!opts.length) return;
        html += '<optgroup label="' + escapeHtml(g.label) + '">' + opts.map(function (s) {
          return '<option value="' + escapeHtml(s.code) + '">' + escapeHtml(s.code + ' — ' + s.name) + '</option>';
        }).join('') + '</optgroup>';
      });
      addSel.innerHTML = html;
      emptyHint.hidden = Object.keys(pickers).length > 0;
    }

    function addSubject(code, name, skills, isNew, customInfo) {
      if (pickers[code]) return;
      if (customInfo) custom[code] = customInfo;
      var blockId = 'ms-subj-' + domId(code);
      var block = document.createElement('div');
      block.className = 'cs-subject-block ms-subject';
      block.id = blockId;
      block.setAttribute('data-code', code);
      block.innerHTML =
        '<div class="ms-subject-head"><h4>' + escapeHtml(code) + ' — ' + escapeHtml(name || names[code] || '') +
        (customInfo ? ' ' + addedTag(customInfo.programs) : '') + '</h4>' +
        '<button type="button" class="ms-remove-subject" aria-label="Remove ' + escapeHtml(code) + '">Remove subject</button></div>' +
        '<div class="cs-skill-picker"></div>';
      if (isNew) list.insertBefore(block, list.firstChild); else list.appendChild(block);
      pickers[code] = buildSkillPicker(qs('.cs-skill-picker', block), skillsFor('', code), (BOOT.levels === 'ipa' ? IPA_LEVELS : PROFICIENCY_LEVELS), blockId, skills || []);
      if (isNew) {
        block.classList.add('is-new');
        block.scrollIntoView({ block: 'nearest' });
        var inp = qs('.cs-tag-input', block); if (inp) inp.focus();
      }
    }

    (BOOT.subjects || []).forEach(function (s) {
      addSubject(s.code, s.name, s.skills, false, s.custom ? { name: s.name, programs: s.programs || [] } : null);
    });

    var otherWrap = document.getElementById('ms-other-subject');
    if (otherWrap) {
      buildOtherSubjectForm(otherWrap, {
        knownCodes: BOOT.knownCodes,
        isTaken: function (code) { return !!pickers[code]; },
        onAdd: function (subj) {
          addSubject(subj.code, subj.name, [], true, { name: subj.name, programs: subj.programs });
          refreshAddOptions();
          markDirty();
        }
      });
    }

    var overallPicker = null;
    if (BOOT.isAlumni) {
      var wrap = document.getElementById('ms-overall');
      wrap.hidden = false;
      var pool = [];
      Object.keys(pickers).forEach(function (code) {
        skillsFor('', code).forEach(function (n) { if (pool.indexOf(n) === -1) pool.push(n); });
      });
      overallPicker = buildSkillPicker(document.getElementById('ms-overall-picker'), pool.slice(0, 24), PROFICIENCY_LEVELS, 'ms-overall', BOOT.overallSkills || []);
    }
    refreshAddOptions();

    addSel.addEventListener('change', function () {
      var code = addSel.value;
      if (!code) return;
      addSubject(code, names[code], [], true);
      refreshAddOptions();
      markDirty();
    });

    list.addEventListener('click', function (e) {
      var btn = e.target.closest('.ms-remove-subject');
      if (!btn) return;
      var block = btn.closest('.ms-subject');
      var code = block.getAttribute('data-code');
      var n = pickers[code] ? pickers[code].collect().length : 0;
      if (n && !window.confirm('Remove ' + code + ' and its ' + n + ' skill' + (n === 1 ? '' : 's') + '?')) return;
      delete pickers[code];
      delete custom[code];
      block.remove();
      refreshAddOptions();
      markDirty();
    });

    form.addEventListener('change', function (e) {
      if (e.target === addSel || e.target.classList.contains('cs-tag-input') || e.target.closest('.cs-other')) return;   // typing alone isn't a change
      markDirty();
    });

    window.addEventListener('beforeunload', function (e) {
      if (!dirty) return;
      e.preventDefault();
      e.returnValue = '';
    });

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      setFormError('ms-error', '');
      var levelError = missingLevelError(form);
      if (levelError) { setFormError('ms-error', levelError); return; }
      // page order = the order shown
      var subjects = qsa('.ms-subject', list).map(function (block) {
        var code = block.getAttribute('data-code');
        var out = { code: code, skills: pickers[code].collect() };
        if (custom[code]) { out.custom = true; out.name = custom[code].name; out.programs = custom[code].programs; }
        return out;
      });
      var payload = { subjects: subjects };
      if (overallPicker) payload.overall_skills = overallPicker.collect();
      saveBtn.disabled = true;
      saveBtn.textContent = 'Saving…';
      postJson(BOOT.saveUrl, payload).then(function (res) {
        saveBtn.disabled = false;
        saveBtn.textContent = 'Save changes';
        if (!res.ok || !res.body || res.body.ok !== true) {
          setFormError('ms-error', (res.body && res.body.error) || 'Could not save. Please try again.');
          return;
        }
        dirty = false;
        statusEl.classList.remove('is-dirty');
        statusEl.textContent = 'Saved just now';
        qsa('.ms-subject.is-new', list).forEach(function (b) { b.classList.remove('is-new'); });
        showToast('Your subjects and skills were saved.');
      }).catch(function () {
        saveBtn.disabled = false;
        saveBtn.textContent = 'Save changes';
        setFormError('ms-error', 'Could not reach the server. Your changes are still on this page; try again.');
      });
    });
  })();
})();

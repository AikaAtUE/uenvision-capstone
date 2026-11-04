/* UEnvision — shared code for the Student / Alumni / Professor curriculum surveys and My Skills.
   Each page also loads its own file (cs-student.js, cs-alumni.js, cs-professor.js,
   cs-my-skills.js), which picks these helpers up from window.UECurriculumSurvey.
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

  /* "About you" box (students/alumni filled it in when they registered): its Change
     button shows the fields so they can fix their year level, section, ... */
  Array.prototype.forEach.call(document.querySelectorAll('[data-reveal]'), function (btn) {
    btn.addEventListener('click', function () {
      var target = document.getElementById(btn.getAttribute('data-reveal'));
      if (target) target.hidden = false;
      btn.hidden = true;
    });
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

  /* ---------- unfinished answers (like Google Forms) ----------
     A logged-in user answering a survey for the first time gets their answers
     kept in this browser as they go, under BOOT.draftKey (views.py sets it only
     then, so editing a saved record never uses it). Opening the survey again
     fills them back in; submitting clears them.
     snapshot() returns the answers as plain JSON; restore(answers) puts them
     back on the page. Returns { clear } for the submit handler. */
  var DRAFT_MAX_AGE_MS = 30 * 24 * 60 * 60 * 1000;

  function surveyDraft(form, snapshot, restore) {
    var key = BOOT.draftKey;
    if (!key) return { clear: function () {} };
    var timer = null, restoring = false, stopped = false;

    var status = document.createElement('p');
    status.className = 'muted cs-draft-status';
    status.setAttribute('role', 'status');
    var submitBtn = qs('button[type=submit]', form);
    var anchor = submitBtn && submitBtn.parentNode !== form ? submitBtn.parentNode : submitBtn;
    if (anchor) anchor.insertAdjacentElement('afterend', status);

    function save() {
      clearTimeout(timer); timer = null;
      if (restoring || stopped) return;
      try {
        localStorage.setItem(key, JSON.stringify({ savedAt: Date.now(), answers: snapshot() }));
        status.textContent = 'Your answers are saved on this device until you submit.';
      } catch (e) { /* storage full or blocked: the survey still works, just without a draft */ }
    }
    function saveSoon() {
      if (restoring || stopped) return;
      clearTimeout(timer);
      timer = setTimeout(save, 400);
    }

    var saved = null;
    try { saved = JSON.parse(localStorage.getItem(key) || 'null'); } catch (e) { saved = null; }
    if (saved && saved.answers && Date.now() - (saved.savedAt || 0) < DRAFT_MAX_AGE_MS) {
      restoring = true;
      try { restore(saved.answers); } catch (e) { /* a draft from an older version of the survey */ }
      restoring = false;
      var note = document.createElement('div');
      note.className = 'cs-banner cs-draft-banner';
      note.innerHTML = '<span>We filled in the answers you started earlier. Pick up where you left off.</span>' +
        '<button type="button" class="link-inline cs-draft-reset">Start over</button>';
      form.insertBefore(note, form.firstChild);
      qs('.cs-draft-reset', note).addEventListener('click', function () {
        if (!window.confirm('Clear the answers you started and begin again?')) return;
        stopped = true;
        try { localStorage.removeItem(key); } catch (e) {}
        window.location.reload();
      });
      status.textContent = 'Your answers are saved on this device until you submit.';
    } else if (saved) {
      try { localStorage.removeItem(key); } catch (e) {}
    }

    // Typing and picking fire input/change on the form; adding or removing a skill
    // fires change on its picker, which bubbles up here too.
    form.addEventListener('input', saveSoon);
    form.addEventListener('change', saveSoon);
    window.addEventListener('pagehide', function () { if (timer) save(); });

    return {
      clear: function () {
        stopped = true;
        clearTimeout(timer);
        try { localStorage.removeItem(key); } catch (e) {}
        status.textContent = '';
      }
    };
  }

  // Plain fields by id: text/select value, or checked for a checkbox.
  function readFields(ids) {
    var out = {};
    ids.forEach(function (id) {
      var el = document.getElementById(id);
      if (el) out[id] = el.type === 'checkbox' ? el.checked : el.value;
    });
    return out;
  }
  // Fires change on each one so the page reacts as if it was picked by hand
  // (e.g. choosing the course lists its subjects).
  function writeFields(values, ids) {
    ids.forEach(function (id) {
      var el = document.getElementById(id);
      if (!el || !values || !(id in values)) return;
      if (el.type === 'checkbox') el.checked = !!values[id]; else el.value = values[id];
      el.dispatchEvent(new Event('change', { bubbles: true }));
    });
  }
  function readRadios(form, names) {
    var out = {};
    names.forEach(function (name) {
      var r = qs('input[name="' + name + '"]:checked', form);
      out[name] = r ? r.value : '';
    });
    return out;
  }
  function writeRadios(form, values, names) {
    names.forEach(function (name) {
      var r = values && values[name] && qs('input[name="' + name + '"][value="' + values[name] + '"]', form);
      if (!r) return;
      r.checked = true;
      r.dispatchEvent(new Event('change', { bubbles: true }));
    });
  }
  // Checks a subject box as if clicked, so its "skills per subject" block appears.
  function pickSubject(box) {
    box.checked = true;
    box.dispatchEvent(new Event('change', { bubbles: true }));
    var details = box.closest('details');
    if (details) details.open = true;
  }
  function addSkills(api, skills) {
    if (api) (skills || []).forEach(function (s) { if (s && s.name) api.add(String(s.name), String(s.level || '')); });
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
      return '<option value="' + escapeHtml(o.value) + '"' + (o.desc ? ' title="' + escapeHtml(o.desc) + '"' : '') + '>' + escapeHtml(o.label) + '</option>';
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
        if (last) { last.remove(); container.dispatchEvent(new Event('change', { bubbles: true })); }
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
      // fills in a skill without moving focus (restoring a draft)
      add: function (name, level) { addChip(name, level, true); },
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

  // `desc` explains each level: shown in the level guide above the skill boxes and as the
  // tooltip of each choice in a skill's level menu.
  var PROFICIENCY_LEVELS = [
    { value: 'beginner', label: 'Beginner', desc: 'You know what it is and can use it with step-by-step guidance, examples or a tutorial.' },
    { value: 'intermediate', label: 'Intermediate', desc: 'You can use it on your own for common tasks, looking things up now and then.' },
    { value: 'advanced', label: 'Advanced', desc: 'You use it confidently on complex tasks or whole projects and can fix problems without help.' },
    { value: 'expert', label: 'Expert', desc: 'You know it in depth: you could teach it to others or lead a project that depends on it.' }
  ];
  var IPA_LEVELS = [
    { value: 'introduced', label: 'Introduced', desc: 'Students first meet the skill: it is explained or demonstrated in lectures or readings, but students are not yet expected to do it on their own.' },
    { value: 'practiced', label: 'Practiced', desc: 'Students do it themselves in guided lab work, exercises, quizzes or assignments, with your help and feedback.' },
    { value: 'applied', label: 'Applied', desc: 'Students use it independently in a graded output, such as a project, case study or capstone, where it is part of what is assessed.' }
  ];

  // Students and alumni use the same Introduced / Practiced / Applied levels as the
  // Professor Survey (so answers line up), described from the learner's side.
  var LEARNER_IPA_LEVELS = [
    { value: 'introduced', label: 'Introduced', desc: 'You first met the skill: it was explained or shown in lectures or readings, but you did not do it on your own yet.' },
    { value: 'practiced', label: 'Practiced', desc: 'You did it yourself in guided lab work, exercises, quizzes or assignments, with your teacher\u2019s help and feedback.' },
    { value: 'applied', label: 'Applied', desc: 'You used it on your own in a graded output, such as a project, case study or capstone, where it was part of what was assessed.' }
  ];

  /* "What do the levels mean?" box above the skill boxes. */
  function levelGuideHtml(levels, intro) {
    return '<div class="cs-level-guide">' +
      '<p class="cs-level-guide-title">' + escapeHtml(intro) + '</p>' +
      '<dl>' + levels.map(function (o) {
        return '<div class="cs-level-guide-row cs-level-guide-row--' + escapeHtml(o.value) + '"><dt>' + escapeHtml(o.label) + '</dt><dd>' + escapeHtml(o.desc || '') + '</dd></div>';
      }).join('') + '</dl></div>';
  }
  function insertLevelGuide(target, levels, intro) {
    if (target) target.insertAdjacentHTML('beforebegin', levelGuideHtml(levels, intro));
  }

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
     opts: { knownCodes: [...], isTaken: fn(code), onAdd: fn({code, name, programs}),
             learner: true for students / alumni: no BSIT/BSCS question (the subject
             belongs to their own course) and elective wording } */
  function buildOtherSubjectForm(container, opts) {
    var uid = 'cs-other-' + Math.random().toString(36).slice(2, 8);
    var learner = !!opts.learner;
    container.innerHTML =
      '<div class="cs-other">' +
        '<button type="button" class="btn btn-ghost btn-sm cs-other-toggle">+ Add a subject that isn\'t listed</button>' +
        '<div class="cs-other-form" hidden>' +
          (learner
            ? '<p class="muted">For example, the Professional Elective you took. Use its own subject code and title from your class schedule or grades.</p>'
            : '<p class="muted">For example, the Professional Elective you handle. Only subjects taken by BSIT or BSCS students are part of this survey.</p>') +
          '<div class="cs-other-fields">' +
            '<label class="field"><span>Subject code</span><input type="text" class="cs-other-code" maxlength="20" placeholder="e.g. CIT 4101" autocomplete="off"></label>' +
            '<label class="field cs-other-name-wrap"><span>Subject title</span><input type="text" class="cs-other-name" maxlength="120" placeholder="e.g. Cloud Computing" autocomplete="off"></label>' +
          '</div>' +
          '<fieldset class="cs-other-programs"' + (learner ? ' hidden' : '') + '><legend>Does this subject have BSIT or BSCS students?</legend>' +
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
      if (learner) {
        opts.onAdd({ code: code, name: name, programs: [] });   // the server tags it with their course
        reset();
        open(false);
        return;
      }
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

  /* ---------- "Select all" for subject lists ----------
     addSelectAll(wrap) puts a "Select all" button above every subject grid in `wrap`
     (one per semester). A button with data-select-all="<css selector>" (e.g. the one for
     the whole page) works on every grid that selector matches. Checking or unchecking
     goes through each box's change event, so the page adds or removes the skill boxes
     exactly as if each subject was clicked. Subjects hidden by "Find a subject" are skipped. */
  function addSelectAll(wrap) {
    qsa('.cs-subject-grid', wrap).forEach(function (grid) {
      var prev = grid.previousElementSibling;
      if (prev && prev.classList.contains('cs-select-all-row')) return;
      grid.insertAdjacentHTML('beforebegin',
        '<div class="cs-select-all-row"><button type="button" class="cs-select-all">Select all</button></div>');
    });
    refreshSelectAll();
  }
  function selectAllBoxes(btn) {
    var sel = btn.getAttribute('data-select-all');
    var grids = sel ? qsa(sel) : [btn.parentNode.nextElementSibling];
    var boxes = [];
    grids.forEach(function (g) {
      if (g) qsa('.cs-subject-pick', g).forEach(function (b) { if (!b.closest('.is-filtered-out')) boxes.push(b); });
    });
    return boxes;
  }
  function refreshSelectAll() {
    qsa('.cs-select-all').forEach(function (btn) {
      var boxes = selectAllBoxes(btn);
      var all = boxes.length && boxes.every(function (b) { return b.checked; });
      btn.textContent = all ? (btn.getAttribute('data-clear-label') || 'Clear all') : (btn.getAttribute('data-label') || 'Select all');
      btn.disabled = !boxes.length;
      btn.setAttribute('aria-pressed', all ? 'true' : 'false');
    });
  }
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('.cs-select-all');
    if (!btn) return;
    var boxes = selectAllBoxes(btn);
    var all = boxes.length && boxes.every(function (b) { return b.checked; });
    boxes.forEach(function (b) {
      if (b.checked === !all) return;
      b.checked = !all;
      b.dispatchEvent(new Event('change', { bubbles: true }));
    });
    refreshSelectAll();
  });
  document.addEventListener('change', function (e) {
    if (e.target.classList && e.target.classList.contains('cs-subject-pick')) setTimeout(refreshSelectAll);
  });
  document.addEventListener('input', function (e) {
    if (e.target.type === 'search') setTimeout(refreshSelectAll);   // "Find a subject" changes what's visible
  });

  /* ---------- × on each "Skills per subject" block ----------
     Removes the subject without scrolling back up to its checkbox: unticks the
     checkbox (so the page reacts as if it was clicked), or, for a subject without
     one, presses the block's own "Remove subject" button. */
  function blockCloseHtml(code) {
    return '<button type="button" class="cs-block-x" aria-label="Remove ' + escapeHtml(code) + '" title="Remove this subject">×</button>';
  }
  document.addEventListener('click', function (e) {
    var x = e.target.closest('.cs-block-x');
    if (!x) return;
    var block = x.closest('.cs-subject-block');
    var code = block && block.getAttribute('data-code');
    var root = block.closest('form') || document;
    var box = qsa('.cs-subject-pick', root).filter(function (c) { return c.value === code && c.checked; })[0];
    if (box) {
      box.checked = false;
      box.dispatchEvent(new Event('change', { bubbles: true }));
    } else {
      var alt = qs('.cs-remove-added, .ms-remove-subject', block);
      if (alt) alt.click();
    }
  });

  window.UECurriculumSurvey = {
    BOOT: BOOT,
    qs: qs,
    qsa: qsa,
    escapeHtml: escapeHtml,
    showToast: showToast,
    setFormError: setFormError,
    skillsFor: skillsFor,
    csrfToken: csrfToken,
    postJson: postJson,
    submitPayload: submitPayload,
    showLearnerDone: showLearnerDone,
    surveyDraft: surveyDraft,
    readFields: readFields,
    writeFields: writeFields,
    readRadios: readRadios,
    writeRadios: writeRadios,
    pickSubject: pickSubject,
    addSkills: addSkills,
    buildSkillPicker: buildSkillPicker,
    missingLevelError: missingLevelError,
    PROFICIENCY_LEVELS: PROFICIENCY_LEVELS,
    IPA_LEVELS: IPA_LEVELS,
    LEARNER_IPA_LEVELS: LEARNER_IPA_LEVELS,
    domId: domId,
    isUeEmail: isUeEmail,
    termTagsHtml: termTagsHtml,
    wireSubjectFilter: wireSubjectFilter,
    buildOtherSubjectForm: buildOtherSubjectForm,
    addedTag: addedTag,
    levelGuideHtml: levelGuideHtml,
    insertLevelGuide: insertLevelGuide,
    addSelectAll: addSelectAll,
    refreshSelectAll: refreshSelectAll,
    blockCloseHtml: blockCloseHtml
  };
})();

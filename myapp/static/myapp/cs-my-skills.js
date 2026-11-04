/* UEnvision — My Skills page (students and professors). Needs curriculum-survey.js (shared helpers) loaded first. */
(function () {
  'use strict';

  var CS = window.UECurriculumSurvey;
  if (!CS) return;
  var BOOT = CS.BOOT,
      qs = CS.qs,
      qsa = CS.qsa,
      escapeHtml = CS.escapeHtml,
      showToast = CS.showToast,
      setFormError = CS.setFormError,
      skillsFor = CS.skillsFor,
      postJson = CS.postJson,
      buildSkillPicker = CS.buildSkillPicker,
      missingLevelError = CS.missingLevelError,
      LEARNER_LEVELS = CS.LEARNER_IPA_LEVELS,
      IPA_LEVELS = CS.IPA_LEVELS,
      domId = CS.domId,
      buildOtherSubjectForm = CS.buildOtherSubjectForm,
      addedTag = CS.addedTag;

  // On-page dialog (ue-modal.js); falls back to "yes" so the page still works without it.
  function ask(message, okLabel, danger) {
    if (window.UEModal) return window.UEModal.confirm({ message: message, okLabel: okLabel, cancelLabel: 'Cancel', danger: danger });
    return Promise.resolve(true);
  }

  /* =====================================================================
     MY SUBJECTS & SKILLS (students / alumni, logged in): the survey record.
     It opens read-only with an "Edit" button. Edit turns on editing and shows
     "Save changes", "Cancel" (back to the saved answers) and "Clear all answers".
     Saving sends the whole list back over the latest response.
  ===================================================================== */
  (function initMySkills() {
    var form = document.getElementById('my-skills-form');
    if (!form || BOOT.mode !== 'my_skills') return;

    var list = document.getElementById('ms-subjects');
    if (CS.insertLevelGuide) {
      CS.insertLevelGuide(list, BOOT.levels === 'ipa' ? IPA_LEVELS : LEARNER_LEVELS,
        BOOT.levels === 'ipa' ? 'How far each skill is taught:' : 'What the levels mean:');
    }
    var levelSet = BOOT.levels === 'ipa' ? IPA_LEVELS : LEARNER_LEVELS;
    var addSel = document.getElementById('ms-add-subject');
    var emptyHint = document.getElementById('ms-no-subjects');
    var statusEl = document.getElementById('ms-status');
    var saveBtn = document.getElementById('ms-save');
    var editBtn = document.getElementById('ms-edit');
    var cancelBtn = document.getElementById('ms-cancel');
    var clearBtn = document.getElementById('ms-clear');
    var pickers = {};          // code -> picker api
    var names = {};            // code -> subject name
    var custom = {};           // code -> {name, programs} for subjects a professor added themselves
    var dirty = false;
    var editing = false;
    var savedStatus = statusEl.textContent;

    // What is saved on the server: shown again on Cancel, replaced after a save.
    var saved = {
      subjects: (BOOT.subjects || []).map(function (s) { return JSON.parse(JSON.stringify(s)); }),
      overall: JSON.parse(JSON.stringify(BOOT.overallSkills || []))
    };

    (BOOT.subjectOptions || []).forEach(function (g) {
      g.subjects.forEach(function (s) { names[s.code] = s.name; });
    });
    (BOOT.subjects || []).forEach(function (s) { if (!names[s.code] && s.name) names[s.code] = s.name; });

    function markDirty() {
      if (!editing || dirty) return;
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
      pickers[code] = buildSkillPicker(qs('.cs-skill-picker', block), skillsFor('', code), levelSet, blockId, skills || []);
      if (isNew) {
        block.classList.add('is-new');
        block.scrollIntoView({ block: 'nearest' });
        var inp = qs('.cs-tag-input', block); if (inp) inp.focus();
      }
    }

    var otherWrap = document.getElementById('ms-other-subject');
    if (otherWrap) {
      buildOtherSubjectForm(otherWrap, {
        learner: BOOT.levels !== 'ipa',
        knownCodes: BOOT.knownCodes,
        isTaken: function (code) { return !!pickers[code]; },
        onAdd: function (subj) {
          addSubject(subj.code, subj.name, [], true, { name: subj.name, programs: subj.programs });
          refreshAddOptions();
          markDirty();
        }
      });
    }

    var overallWrap = document.getElementById('ms-overall');
    var overallPicker = null;
    function buildOverall(skills) {
      if (!BOOT.isAlumni) return;
      overallWrap.hidden = false;
      var pool = [];
      Object.keys(pickers).forEach(function (code) {
        skillsFor('', code).forEach(function (n) { if (pool.indexOf(n) === -1) pool.push(n); });
      });
      overallPicker = buildSkillPicker(document.getElementById('ms-overall-picker'), pool.slice(0, 24), LEARNER_LEVELS, 'ms-overall', skills || []);
    }

    // Draw the page from a saved state (on load and on Cancel).
    function render(state) {
      qsa('.ms-subject', list).forEach(function (b) { b.remove(); });
      pickers = {};
      custom = {};
      state.subjects.forEach(function (s) {
        addSubject(s.code, s.name, s.skills, false, s.custom ? { name: s.name, programs: s.programs || [] } : null);
      });
      buildOverall(state.overall);
      refreshAddOptions();
    }

    // Read-only: every box on the page is switched off except the Edit / Save / Cancel buttons.
    function setEditing(on) {
      editing = on;
      form.classList.toggle('is-readonly', !on);
      qsa('input, select, textarea, button', form).forEach(function (el) {
        if (el.type === 'hidden' || el.hasAttribute('data-ms-action')) return;
        el.disabled = !on;
      });
      editBtn.hidden = on;
      saveBtn.hidden = !on;
      cancelBtn.hidden = !on;
      if (clearBtn) clearBtn.hidden = !on;
    }

    function stopEditing(state) {
      dirty = false;
      statusEl.classList.remove('is-dirty');
      render(state);
      setEditing(false);
    }

    render(saved);
    setEditing(false);

    editBtn.addEventListener('click', function () {
      setEditing(true);
      statusEl.textContent = 'Editing: press Save changes when you are done.';
      try { addSel.focus({ preventScroll: true }); } catch (e) { addSel.focus(); }
    });

    cancelBtn.addEventListener('click', function () {
      var back = function () {
        stopEditing(saved);
        statusEl.textContent = savedStatus;
        setFormError('ms-error', '');
        editBtn.focus();
      };
      if (!dirty) { back(); return; }
      ask('Discard your changes? Your saved subjects and skills will be shown again.', 'Discard changes', true)
        .then(function (yes) { if (yes) back(); });
    });

    if (clearBtn) {
      clearBtn.addEventListener('click', function () {
        ask('Clear all your answers on this page? Nothing is saved until you press Save changes.', 'Clear all answers', true)
          .then(function (yes) {
            if (!yes) return;
            qsa('.ms-subject', list).forEach(function (b) { b.remove(); });
            pickers = {};
            custom = {};
            if (overallPicker) buildOverall([]);
            refreshAddOptions();
            setEditing(true);      // the rebuilt boxes start switched on
            dirty = false; markDirty();
            showToast('All answers on this page were cleared. Press Save changes to keep it that way, or Cancel.');
          });
      });
    }

    addSel.addEventListener('change', function () {
      var code = addSel.value;
      if (!code) return;
      addSubject(code, names[code], [], true);
      refreshAddOptions();
      markDirty();
    });

    list.addEventListener('click', function (e) {
      var btn = e.target.closest('.ms-remove-subject');
      if (!btn || !editing) return;
      var block = btn.closest('.ms-subject');
      var code = block.getAttribute('data-code');
      var n = pickers[code] ? pickers[code].collect().length : 0;
      var remove = function () {
        delete pickers[code];
        delete custom[code];
        block.remove();
        refreshAddOptions();
        markDirty();
      };
      if (!n) { remove(); return; }
      ask('Remove ' + code + ' and its ' + n + ' skill' + (n === 1 ? '' : 's') + '?', 'Remove', true)
        .then(function (yes) { if (yes) remove(); });
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
      if (!editing) return;
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
        saved = {
          subjects: subjects.map(function (s) {
            return { code: s.code, name: s.custom ? s.name : (names[s.code] || s.name || ''), custom: !!s.custom,
                     programs: s.programs || [], skills: s.skills };
          }),
          overall: payload.overall_skills || saved.overall
        };
        stopEditing(saved);
        savedStatus = 'Saved just now';
        statusEl.textContent = savedStatus;
        showToast('Your subjects and skills were saved.');
        editBtn.focus();
      }).catch(function () {
        saveBtn.disabled = false;
        saveBtn.textContent = 'Save changes';
        setFormError('ms-error', 'Could not reach the server. Your changes are still on this page; try again.');
      });
    });
  })();
})();

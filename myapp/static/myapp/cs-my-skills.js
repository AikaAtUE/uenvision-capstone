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
      PROFICIENCY_LEVELS = CS.PROFICIENCY_LEVELS,
      IPA_LEVELS = CS.IPA_LEVELS,
      domId = CS.domId,
      buildOtherSubjectForm = CS.buildOtherSubjectForm,
      addedTag = CS.addedTag;

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

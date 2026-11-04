/* UEnvision — Student survey page. Needs curriculum-survey.js (shared helpers) loaded first. */
(function () {
  'use strict';

  var CS = window.UECurriculumSurvey;
  if (!CS) return;
  var BOOT = CS.BOOT,
      qs = CS.qs,
      qsa = CS.qsa,
      escapeHtml = CS.escapeHtml,
      setFormError = CS.setFormError,
      skillsFor = CS.skillsFor,
      submitPayload = CS.submitPayload,
      showLearnerDone = CS.showLearnerDone,
      surveyDraft = CS.surveyDraft,
      readFields = CS.readFields,
      writeFields = CS.writeFields,
      aboutNames = CS.aboutNames || function () { return {}; },
      pickSubject = CS.pickSubject,
      addSkills = CS.addSkills,
      buildSkillPicker = CS.buildSkillPicker,
      missingLevelError = CS.missingLevelError,
      LEARNER_LEVELS = CS.LEARNER_IPA_LEVELS,
      domId = CS.domId,
      isUeEmail = CS.isUeEmail,
      termTagsHtml = CS.termTagsHtml,
      wireSubjectFilter = CS.wireSubjectFilter,
      addSelectAll = CS.addSelectAll,
      blockCloseHtml = CS.blockCloseHtml,
      insertLevelGuide = CS.insertLevelGuide,
      buildOtherSubjectForm = CS.buildOtherSubjectForm,
      addedTag = CS.addedTag;

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
    var laterWrap = qs('#student-later-subjects', form);
    var blocksWrap = qs('#student-subject-blocks', form);
    insertLevelGuide(blocksWrap, LEARNER_LEVELS, 'What the levels mean (choose how far you got with each skill in the subject):');
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
      // Subjects they added themselves don't depend on the course / year, so they stay.
      var added = Object.keys(pickers).filter(function (c) { return pickers[c].custom; }).map(function (c) {
        return { code: c, name: pickers[c].name, skills: pickers[c].api.collect() };
      });
      blocksWrap.innerHTML = '';
      pickers = {};
      added.forEach(function (s) { addCustomBlock(s.code, s.name, s.skills); });
      earlierWrap.innerHTML = '';
      if (laterWrap) laterWrap.innerHTML = '';
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

      // Irregular or advanced students sometimes take a higher year's subject early.
      if (laterWrap && elig.later && elig.later.length) {
        laterWrap.innerHTML =
          '<details class="cs-earlier"><summary>+ Also report subjects from higher year levels (optional)</summary>' +
          '<p class="muted">For subjects you took ahead of your year level, for example as an irregular student.</p>' +
          elig.later.map(function (term) {
            return '<h4>' + escapeHtml(term.term_label) + '</h4>' + termGrid(term, 'later');
          }).join('') +
          '</details>';
      }
      [currentWrap, previousWrap, earlierWrap, laterWrap].forEach(function (w) { if (w) addSelectAll(w); });
      applyFilter();
    }

    function addSubjectBlock(code, name, program, termLabel, termBucket) {
      var blockId = 'cs-subj-' + domId(code);
      blocksWrap.insertAdjacentHTML('beforeend',
        '<div class="cs-subject-block" id="' + blockId + '" data-code="' + escapeHtml(code) + '" data-term="' + termBucket + '">' +
          blockCloseHtml(code) +
          '<h4>' + escapeHtml(code) + ' — ' + escapeHtml(name) + '</h4>' +
          '<p class="cs-subject-term">' + escapeHtml(termLabel) + '</p>' +
          '<div class="cs-skill-picker"></div>' +
        '</div>'
      );
      var container = qs('#' + blockId + ' .cs-skill-picker');
      var api = buildSkillPicker(container, skillsFor(program, code), LEARNER_LEVELS, blockId);
      pickers[code] = { api: api, name: name, termLabel: termLabel, termBucket: termBucket };
    }

    /* A subject that isn't listed (e.g. the Professional Elective they took). */
    function addCustomBlock(code, name, skills) {
      if (pickers[code]) return null;
      var blockId = 'cs-subj-' + domId(code);
      blocksWrap.insertAdjacentHTML('beforeend',
        '<div class="cs-subject-block" id="' + blockId + '" data-code="' + escapeHtml(code) + '" data-term="added">' +
          '<div class="ms-subject-head"><h4>' + escapeHtml(code) + ' — ' + escapeHtml(name) + ' ' + addedTag([]) + '</h4>' +
          '<button type="button" class="ms-remove-subject cs-remove-added">Remove subject</button></div>' +
          '<div class="cs-skill-picker"></div>' +
        '</div>'
      );
      var block = document.getElementById(blockId);
      var api = buildSkillPicker(qs('.cs-skill-picker', block), [], LEARNER_LEVELS, blockId, skills || []);
      pickers[code] = { api: api, name: name, termLabel: 'Added by you', termBucket: 'added', custom: true };
      return block;
    }
    blocksWrap.addEventListener('click', function (e) {
      var btn = e.target.closest('.cs-remove-added');
      if (!btn) return;
      removeSubjectBlock(btn.closest('.cs-subject-block').getAttribute('data-code'));
      updatePickedCount();
      form.dispatchEvent(new Event('change'));   // keep the saved draft in step
    });
    var otherWrap = qs('#student-other-subject', form);
    if (otherWrap) {
      buildOtherSubjectForm(otherWrap, {
        learner: true,
        knownCodes: BOOT.knownCodes,
        isTaken: function (code) { return !!pickers[code]; },
        onAdd: function (subj) {
          var block = addCustomBlock(subj.code, subj.name, []);
          updatePickedCount();
          form.dispatchEvent(new Event('change'));
          if (block) { block.scrollIntoView({ block: 'nearest' }); var inp = qs('.cs-tag-input', block); if (inp) inp.focus(); }
        }
      });
    }

    function removeSubjectBlock(code) {
      var el = document.getElementById('cs-subj-' + domId(code));
      if (el) el.remove();
      delete pickers[code];
    }

    [currentWrap, previousWrap, earlierWrap, laterWrap].filter(Boolean).forEach(function (wrap) {
      wrap.addEventListener('change', function (e) {
        if (!e.target.classList.contains('cs-subject-pick')) return;
        var elig = currentElig();
        var bucket = e.target.getAttribute('data-bucket');
        var termKey = e.target.getAttribute('data-term-key');
        var terms = bucket === 'earlier' ? elig.earlier
          : bucket === 'later' ? (elig.later || [])
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

    // Course (and year level) already filled in from registration: list the subjects now.
    if (programSel.value) programSel.dispatchEvent(new Event('change'));

    var FIELDS = ['student-name', 'student-email', 'student-program', 'student-number', 'student-year', 'student-section', 'student-consent'];
    var draft = surveyDraft(form, function () {
      return {
        fields: readFields(FIELDS),
        subjects: Object.keys(pickers).map(function (code) {
          var box = qsa('.cs-subject-pick:checked', form).filter(function (c) { return c.value === code; })[0];
          return { code: code, termKey: box ? box.getAttribute('data-term-key') : '', skills: pickers[code].api.collect(),
                   custom: !!pickers[code].custom, name: pickers[code].name };
        })
      };
    }, function (d) {
      writeFields(d.fields, FIELDS);   // course + year level list the subjects
      (d.subjects || []).forEach(function (s) {
        if (s.custom) { addCustomBlock(s.code, s.name || '', s.skills); return; }
        var box = qsa('.cs-subject-pick', form).filter(function (c) {
          return c.value === s.code && c.getAttribute('data-term-key') === s.termKey;
        })[0];
        if (!box) return;   // no longer offered (a new semester started)
        pickSubject(box);
        addSkills(pickers[s.code] && pickers[s.code].api, s.skills);
      });
    });

    // "Clear all answers": drop the subjects they added, then redraw the subject lists for the
    // same course and year level (every box unticked, every skill block gone).
    CS.wireClearAll(document.getElementById('student-clear'), function () {
      Object.keys(pickers).forEach(removeSubjectBlock);
      pickers = {};
      renderSubjectGroups();
      updatePickedCount();
      setFormError('student-error', '');
      form.dispatchEvent(new Event('change'));
    }, draft);

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
      var section = qs('#student-section', form).value.trim();
      var consent = qs('#student-consent', form).checked;

      if (!name || !email || !course || !studentNumber || !year || !section) {
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
        var out = { code: code, name: p.name, term: p.termBucket, term_label: p.termLabel, skills: p.api.collect() };
        if (p.custom) out.custom = true;
        return out;
      });

      var payload = {
        consent: true,
        personal_info: Object.assign({ name: name, ue_email: email, course: course, student_number: studentNumber, year_level: Number(year), section: section }, aboutNames()),
        has_previous: hasPrevious,
        target_role: BOOT.targetRole || '',
        subjects: subjects
      };

      submitPayload(BOOT.submitUrl, form, payload, function (body) {
        if (body && body.ok) draft.clear();
        showLearnerDone(form, body);
      }, function (msg) { setFormError('student-error', msg); });
    });
  })();
})();

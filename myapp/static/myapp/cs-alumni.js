/* UEnvision — Alumni survey page. Needs curriculum-survey.js (shared helpers) loaded first. */
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
      readRadios = CS.readRadios,
      writeRadios = CS.writeRadios,
      pickSubject = CS.pickSubject,
      addSkills = CS.addSkills,
      buildSkillPicker = CS.buildSkillPicker,
      missingLevelError = CS.missingLevelError,
      LEARNER_LEVELS = CS.LEARNER_IPA_LEVELS,
      domId = CS.domId,
      termTagsHtml = CS.termTagsHtml,
      wireSubjectFilter = CS.wireSubjectFilter,
      addSelectAll = CS.addSelectAll,
      blockCloseHtml = CS.blockCloseHtml,
      insertLevelGuide = CS.insertLevelGuide,
      buildOtherSubjectForm = CS.buildOtherSubjectForm,
      addedTag = CS.addedTag;

  /* =====================================================================
     ALUMNI SURVEY
  ===================================================================== */
  (function initAlumniSurvey() {
    var form = document.getElementById('alumni-survey-form');
    if (!form) return;

    var programSel = qs('#alumni-program', form);
    var subjectsWrap = qs('#alumni-subjects', form);   // one list per year level
    var blocksWrap = qs('#alumni-subject-blocks', form);
    insertLevelGuide(blocksWrap, LEARNER_LEVELS, 'What the levels mean (choose how far you got with each skill in the subject):');
    var overallWrap = qs('#alumni-overall-skills', form);
    var pickers = {};
    var overallPicker = null;
    // Laid out like the faculty survey: one open list per year level (1st to 4th Year, every
    // semester and summer of that year together), with Find a subject, Select all and a count.
    var tools = qs('#alumni-subject-tools', form);
    var hint = qs('#alumni-hint', form);
    var filterInput = qs('#alumni-subject-filter', form);
    var pickedCount = qs('#alumni-picked-count', form);
    var applyFilter = filterInput ? wireSubjectFilter(form, filterInput) : function () {};
    function updatePickedCount() {
      // each folded year says how many of its subjects are ticked, so nothing hides when closed
      qsa('.cs-year', subjectsWrap).forEach(function (fold) {
        var n = qsa('.cs-subject-pick:checked', fold).length;
        var tag = qs('.cs-year-picked', fold);
        if (tag) tag.textContent = n ? n + ' selected' : '';
      });
      if (!pickedCount) return;
      var n = Object.keys(pickers).length;
      pickedCount.textContent = n ? n + ' subject' + (n === 1 ? '' : 's') + ' selected' : 'No subjects selected yet';
    }
    function showTools(show) {
      if (tools) tools.hidden = !show;
      if (hint) hint.hidden = show;
      updatePickedCount();
    }

    function subjectCheckHtml(subj, termKey) {
      return '<label class="cs-subject-check">' +
        '<input type="checkbox" class="cs-subject-pick" value="' + escapeHtml(subj.code) + '" data-term-key="' + escapeHtml(termKey) + '">' +
        '<span class="cs-subject-text"><span><span class="cs-subject-code">' + escapeHtml(subj.code) + '</span>' + escapeHtml(subj.name) +
        ' <span class="cs-subject-units">(' + subj.units + ' units)</span></span>' + termTagsHtml(subj.code, programSel.value) + '</span>' +
      '</label>';
    }

    function termsOf(program) { return (BOOT.termsByProgram || {})[program] || []; }
    function termLabelOf(program, termKey) {
      return (termsOf(program).filter(function (t) { return t.key === termKey; })[0] || {}).label || termKey;
    }
    function subjectsOf(program, termKey) {
      return ((BOOT.subjectsByProgramTerm || {})[program] || {})[termKey] || [];
    }

    function gridHtml(program, termKey) {
      return '<div class="cs-subject-grid">' + subjectsOf(program, termKey).map(function (subj) {
        return subjectCheckHtml(subj, termKey);
      }).join('') + '</div>';
    }

    // The latest term with a ticked subject: saved as their last semester at UE.
    function lastTermKey() {
      var keys = termsOf(programSel.value).map(function (t) { return t.key; });
      var best = -1;
      qsa('.cs-subject-pick:checked', form).forEach(function (box) {
        best = Math.max(best, keys.indexOf(box.getAttribute('data-term-key')));
      });
      return best >= 0 ? keys[best] : '';
    }

    var YEAR_NAMES = { 1: '1st Year', 2: '2nd Year', 3: '3rd Year', 4: '4th Year' };
    function yearName(y) { return YEAR_NAMES[y] || ('Year ' + y); }

    function renderSubjects() {
      // Subjects they added themselves don't depend on the course, so they stay.
      var added = Object.keys(pickers).filter(function (c) { return pickers[c].custom; }).map(function (c) {
        return { code: c, name: pickers[c].name, skills: pickers[c].api.collect() };
      });
      blocksWrap.innerHTML = '';
      pickers = {};
      added.forEach(function (s) { addCustomBlock(s.code, s.name, s.skills); });
      var program = programSel.value;
      var terms = termsOf(program);
      subjectsWrap.innerHTML = '';
      if (!program || !terms.length) { showTools(false); return; }
      showTools(true);
      var years = [];
      var byYear = {};
      terms.forEach(function (t) {
        if (!byYear[t.year]) { byYear[t.year] = []; years.push(t.year); }
        byYear[t.year].push(t);
      });
      // Newest year first (4th Year on top, open); the other years are folded until opened.
      // Find a subject and Select all open a fold when they reach into it.
      subjectsWrap.innerHTML = years.slice().reverse().map(function (y, i) {
        var subjects = '';
        byYear[y].forEach(function (t) {
          subjectsOf(program, t.key).forEach(function (subj) { subjects += subjectCheckHtml(subj, t.key); });
        });
        var count = (subjects.match(/class="cs-subject-pick"/g) || []).length;
        return '<details class="cs-section cs-year" data-year="' + y + '"' + (i === 0 ? ' open' : '') + '>' +
          '<summary><span class="cs-year-title">' + escapeHtml(yearName(y)) + ' subjects</span>' +
          ' <span class="muted cs-year-meta">' + count + ' subject' + (count === 1 ? '' : 's') + ' · ' +
          escapeHtml(byYear[y].map(function (t) { return t.label.replace(/^\d\w+ Year – /, ''); }).join(' · ')) + '</span>' +
          '<span class="cs-year-picked" aria-live="polite"></span></summary>' +
          '<div class="cs-subject-grid">' + subjects + '</div>' +
        '</details>';
      }).join('');
      addSelectAll(subjectsWrap);
      applyFilter();
    }

    function addSubjectBlock(code, name, program, termLabel, termKey, bucket) {
      if (pickers[code]) return;
      var blockId = 'cs-asubj-' + domId(code);
      blocksWrap.insertAdjacentHTML('beforeend',
        '<div class="cs-subject-block" id="' + blockId + '" data-code="' + escapeHtml(code) + '">' +
          blockCloseHtml(code) +
          '<h4>' + escapeHtml(code) + ' — ' + escapeHtml(name) + '</h4>' +
          '<p class="cs-subject-term">' + escapeHtml(termLabel) + '</p>' +
          '<div class="cs-skill-picker"></div>' +
        '</div>'
      );
      var container = qs('#' + blockId + ' .cs-skill-picker');
      var api = buildSkillPicker(container, skillsFor(program, code), LEARNER_LEVELS, blockId);
      pickers[code] = { api: api, name: name, termLabel: termLabel, termKey: termKey, bucket: bucket };
    }
    /* A subject that isn't listed (e.g. the Professional Elective they took). */
    function addCustomBlock(code, name, skills) {
      if (pickers[code]) return null;
      var blockId = 'cs-asubj-' + domId(code);
      blocksWrap.insertAdjacentHTML('beforeend',
        '<div class="cs-subject-block" id="' + blockId + '" data-code="' + escapeHtml(code) + '">' +
          '<div class="ms-subject-head"><h4>' + escapeHtml(code) + ' — ' + escapeHtml(name) + ' ' + addedTag([]) + '</h4>' +
          '<button type="button" class="ms-remove-subject cs-remove-added">Remove subject</button></div>' +
          '<div class="cs-skill-picker"></div>' +
        '</div>'
      );
      var block = document.getElementById(blockId);
      var api = buildSkillPicker(qs('.cs-skill-picker', block), CS.titleSuggestions ? CS.titleSuggestions(name) : [], LEARNER_LEVELS, blockId, skills || []);
      pickers[code] = { api: api, name: name, termLabel: 'Added by you', termKey: '', bucket: 'added', custom: true };
      return block;
    }
    blocksWrap.addEventListener('click', function (e) {
      var btn = e.target.closest('.cs-remove-added');
      if (!btn) return;
      removeSubjectBlock(btn.closest('.cs-subject-block').getAttribute('data-code'));
      updatePickedCount();
      form.dispatchEvent(new Event('change'));
    });
    var otherWrap = qs('#alumni-other-subject', form);
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
      var el = document.getElementById('cs-asubj-' + domId(code));
      if (el) el.remove();
      delete pickers[code];
    }

    [subjectsWrap].forEach(function (wrap) {
      wrap.addEventListener('change', function (e) {
        if (!e.target.classList.contains('cs-subject-pick')) return;
        var program = programSel.value;
        var termKey = e.target.getAttribute('data-term-key');
        var subj = subjectsOf(program, termKey).filter(function (s) { return s.code === e.target.value; })[0];
        if (!subj) return;
        if (e.target.checked) {
          var term = termsOf(program).filter(function (t) { return t.key === termKey; })[0] || {};
          addSubjectBlock(subj.code, subj.name, program, termLabelOf(program, termKey), termKey,
                          term.year ? 'year' + term.year : 'earlier');
        } else {
          removeSubjectBlock(subj.code);
        }
        updatePickedCount();
      });
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
      overallPicker = buildSkillPicker(qs('#alumni-overall-picker', overallWrap), names.slice(0, 24), LEARNER_LEVELS, 'alumni-overall');
    }

    programSel.addEventListener('change', function () { renderSubjects(); renderOverallSkills(); });

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
    // A reload can bring back a ticked "Currently employed" / "upskilling" answer without a
    // change event (the browser restores form state), which left its questions hidden.
    function syncBranches() {
      var employed = (employedRadios.filter(function (r) { return r.checked; })[0] || {}).value;
      employedBranch.hidden = employed !== 'yes';
      unemployedBranch.hidden = employed !== 'no';
      var up = (upskillRadios.filter(function (r) { return r.checked; })[0] || {}).value;
      upskillBranch.hidden = up !== 'yes';
    }
    syncBranches();
    window.addEventListener('pageshow', syncBranches);

    function tagInput(inputId, listId) {
      var input = document.getElementById(inputId);
      var list = document.getElementById(listId);
      var values = [];
      function render() {
        list.dispatchEvent(new Event('change', { bubbles: true }));
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
      return {
        get: function () { return values.slice(); },
        set: function (list) { values = (list || []).map(String); render(); }
      };
    }
    // "Which technical skills do you feel you still need to learn?": a skill box like the others,
    // suggesting the skills job postings ask for most for their course (BOOT.learnSuggestions);
    // anything else is found by typing. No level is asked.
    var learnWrap = qs('#alumni-skills-to-learn-picker', form);
    var learnPicker = null;
    function buildLearnPicker(names) {
      if (!learnWrap) return;
      var suggested = (BOOT.learnSuggestions || {})[programSel.value] || [];
      learnPicker = buildSkillPicker(learnWrap, suggested, [{ value: 'learn', label: 'To learn' }], 'alumni-learn',
        (names || []).map(function (n) { return { name: n, level: 'learn' }; }));
    }
    var skillsToLearnTags = {
      get: function () { return learnPicker ? learnPicker.collect().map(function (s) { return s.name; }) : []; },
      set: function (list) { buildLearnPicker((list || []).map(String)); }
    };
    buildLearnPicker([]);
    // a new course brings its own suggestions; skills already added stay
    programSel.addEventListener('change', function () { buildLearnPicker(skillsToLearnTags.get()); });
    var upskillTags = tagInput('alumni-upskilling-input', 'alumni-upskilling-list');

    // "Clear all answers": drop the subjects they added, redraw the subject lists, the overall
    // and "skills applied" pickers for the same course (all empty), and empty the employment
    // answers. "About you" (name, course, student number, ...) stays as it is.
    CS.wireClearAll(document.getElementById('alumni-clear'), function () {
      Object.keys(pickers).forEach(removeSubjectBlock);
      pickers = {};
      programSel.dispatchEvent(new Event('change'));
      updatePickedCount();
      skillsToLearnTags.set([]);
      upskillTags.set([]);
      qsa('input[name="alumni-employed"], input[name="alumni-first-job"], input[name="alumni-upskilling"]', form)
        .forEach(function (r) { r.checked = false; });
      ['alumni-role', 'alumni-jobs-applied', 'alumni-rejection-reason', 'alumni-upskilling-input']
        .forEach(function (id) { var el = document.getElementById(id); if (el) el.value = ''; });
      employedBranch.hidden = true;
      unemployedBranch.hidden = true;
      upskillBranch.hidden = true;
      setFormError('alumni-error', '');
      form.dispatchEvent(new Event('change'));
    }, { discard: function () { if (typeof draft !== 'undefined' && draft) draft.discard(); } });

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

      // Alumni may use any email: many no longer have their UE account.
      if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
        setFormError('alumni-error', 'Please enter a valid email address.');
        return;
      }
      if (!name || !email || !course || !yearGraduated) {   // the student number is optional for alumni
        setFormError('alumni-error', 'Please fill in your name, email, course and the year you graduated.');
        return;
      }
      if (!consent) {
        setFormError('alumni-error', 'Please tick “I have read the Data Privacy Notice” just above the Submit button.');
        return;
      }
      var termKey = lastTermKey();
      if (!termKey) {
        setFormError('alumni-error', 'Please select at least one subject you took at UE.');
        return;
      }
      var skillsError = CS.missingSkillsError(blocksWrap);
      if (skillsError) { setFormError('alumni-error', skillsError); return; }
      var employedChoice = (employedRadios.filter(function (r) { return r.checked; })[0] || {}).value;
      if (!employedChoice) {
        setFormError('alumni-error', 'Please answer whether you are currently employed.');
        return;
      }

      var subjects = Object.keys(pickers).map(function (code) {
        var p = pickers[code];
        var out = { code: code, name: p.name, term: p.bucket, term_label: p.termLabel, skills: p.api.collect() };
        if (p.custom) out.custom = true;
        return out;
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
        personal_info: Object.assign({ name: name, ue_email: email, course: course, student_number: studentNumber, year_graduated: yearGraduated }, aboutNames()),
        target_role: BOOT.targetRole || '',
        last_semester: { program: course, term_key: termKey, term_label: termLabelOf(course, termKey) },
        subjects: subjects,
        overall_skills: overallPicker ? overallPicker.collect() : [],
        employment: employment
      };

      submitPayload(BOOT.submitUrl, form, payload, function (body) {
        if (body && body.ok) draft.clear();
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

    // Course (and year level) already filled in from registration: list the subjects now.
    if (programSel.value) programSel.dispatchEvent(new Event('change'));

    var FIELDS = ['alumni-name', 'alumni-email', 'alumni-program', 'alumni-number', 'alumni-year-graduated', 'alumni-consent'];
    var MORE_FIELDS = ['alumni-role', 'alumni-jobs-applied', 'alumni-rejection-reason'];
    var RADIOS = ['alumni-employed', 'alumni-first-job', 'alumni-upskilling'];
    var draft = surveyDraft(form, function () {
      return {
        fields: readFields(FIELDS.concat(MORE_FIELDS)),
        radios: readRadios(form, RADIOS),
        subjects: Object.keys(pickers).map(function (code) {
          return { code: code, termKey: pickers[code].termKey, skills: pickers[code].api.collect(), custom: !!pickers[code].custom, name: pickers[code].name };
        }),
        overall: overallPicker ? overallPicker.collect() : [],
        applied: window.__alumniAppliedPicker ? window.__alumniAppliedPicker.collect() : [],
        toLearn: skillsToLearnTags.get(),
        upskilling: upskillTags.get()
      };
    }, function (d) {
      writeFields(d.fields, FIELDS);              // the course lists its subjects + overall skills
      (d.subjects || []).forEach(function (s) {
        if (s.custom) { addCustomBlock(s.code, s.name || '', s.skills); return; }
        var box = qsa('.cs-subject-pick', form).filter(function (c) {
          return c.value === s.code && (!s.termKey || c.getAttribute('data-term-key') === s.termKey);
        })[0];
        if (!box) return;
        pickSubject(box);
        addSkills(pickers[s.code] && pickers[s.code].api, s.skills);
      });
      addSkills(overallPicker, d.overall);
      writeRadios(form, d.radios, RADIOS);
      writeFields(d.fields, MORE_FIELDS);
      addSkills(window.__alumniAppliedPicker, d.applied);
      updatePickedCount();
      skillsToLearnTags.set(d.toLearn);
      upskillTags.set(d.upskilling);
    });
  })();
})();

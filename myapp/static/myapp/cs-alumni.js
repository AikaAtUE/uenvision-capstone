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
      readRadios = CS.readRadios,
      writeRadios = CS.writeRadios,
      pickSubject = CS.pickSubject,
      addSkills = CS.addSkills,
      buildSkillPicker = CS.buildSkillPicker,
      missingLevelError = CS.missingLevelError,
      PROFICIENCY_LEVELS = CS.PROFICIENCY_LEVELS,
      domId = CS.domId,
      isUeEmail = CS.isUeEmail,
      termTagsHtml = CS.termTagsHtml;

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

    var FIELDS = ['alumni-name', 'alumni-email', 'alumni-program', 'alumni-number', 'alumni-year-graduated', 'alumni-consent'];
    var MORE_FIELDS = ['alumni-role', 'alumni-jobs-applied', 'alumni-rejection-reason'];
    var RADIOS = ['alumni-employed', 'alumni-first-job', 'alumni-upskilling'];
    var draft = surveyDraft(form, function () {
      return {
        fields: readFields(FIELDS.concat(['alumni-term'], MORE_FIELDS)),
        radios: readRadios(form, RADIOS),
        subjects: Object.keys(pickers).map(function (code) { return { code: code, skills: pickers[code].api.collect() }; }),
        overall: overallPicker ? overallPicker.collect() : [],
        applied: window.__alumniAppliedPicker ? window.__alumniAppliedPicker.collect() : [],
        toLearn: skillsToLearnTags.get(),
        upskilling: upskillTags.get()
      };
    }, function (d) {
      writeFields(d.fields, FIELDS);              // the course lists its terms + overall skills
      writeFields(d.fields, ['alumni-term']);     // the last semester lists its subjects
      (d.subjects || []).forEach(function (s) {
        var box = qsa('.cs-subject-pick', subjectsWrap).filter(function (c) { return c.value === s.code; })[0];
        if (!box) return;
        pickSubject(box);
        addSkills(pickers[s.code] && pickers[s.code].api, s.skills);
      });
      addSkills(overallPicker, d.overall);
      writeRadios(form, d.radios, RADIOS);
      writeFields(d.fields, MORE_FIELDS);
      addSkills(window.__alumniAppliedPicker, d.applied);
      skillsToLearnTags.set(d.toLearn);
      upskillTags.set(d.upskilling);
    });
  })();
})();

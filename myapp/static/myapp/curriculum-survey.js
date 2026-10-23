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
  function skillsFor(program, code) {
    return (BOOT.skills && BOOT.skills[program + ':' + code]) || [];
  }

  function submitPayload(url, form, payload, onSuccess) {
    var tokenInput = qs('input[name=csrfmiddlewaretoken]', form);
    fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': tokenInput ? tokenInput.value : '' },
      credentials: 'same-origin',
      body: JSON.stringify(payload)
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (body) { return { ok: r.ok, body: body }; });
    }).then(function (res) {
      if (!res.ok || !res.body || res.body.ok !== true) {
        throw new Error((res.body && res.body.error) || 'Submit failed.');
      }
      onSuccess();
    }).catch(function (err) {
      try {
        var key = 'ue_curriculum_survey_fallback';
        var existing = JSON.parse(localStorage.getItem(key) || '[]');
        existing.push(Object.assign({}, payload, { _savedAt: new Date().toISOString(), _error: String(err) }));
        localStorage.setItem(key, JSON.stringify(existing));
      } catch (e) { /* storage unavailable */ }
      showToast('Could not reach the server, so your answers were saved on this device instead. Please tell us if this keeps happening.', true);
      onSuccess();
    });
  }

  /* ---------- skill picker (shared by all three surveys) ----------
     Renders a checkbox per suggested skill + a level/method select that
     enables once checked, plus a free-text "add another skill" row.
     `levelOptions` is an array of {value,label} — proficiency levels for
     Student/Alumni, I/P/A for Professor. Returns an API object the caller
     uses to read back the selected skills. */
  function buildSkillPicker(container, suggestedNames, levelOptions, idPrefix) {
    var optionsHtml = levelOptions.map(function (o) {
      return '<option value="' + escapeHtml(o.value) + '">' + escapeHtml(o.label) + '</option>';
    }).join('');

    function rowHtml(name, custom) {
      return '<div class="cs-skill-row' + (custom ? ' is-custom' : '') + '" data-skill="' + escapeHtml(name) + '">' +
        '<label><input type="checkbox" class="cs-skill-check" ' + (custom ? 'checked' : '') + '>' + escapeHtml(name) + '</label>' +
        '<select class="cs-skill-level" ' + (custom ? '' : 'disabled') + '>' + optionsHtml + '</select>' +
      '</div>';
    }

    var gridId = idPrefix + '-grid';
    container.innerHTML =
      '<div class="cs-skill-grid" id="' + gridId + '">' +
        (suggestedNames.length
          ? suggestedNames.map(function (n) { return rowHtml(n, false); }).join('')
          : '<p class="cs-section--empty">No suggested skills for this subject yet — add your own below.</p>') +
      '</div>' +
      '<div class="cs-add-skill">' +
        '<input type="text" class="cs-add-skill-input" placeholder="Add another skill not listed above">' +
        '<button type="button" class="btn btn-ghost btn-sm cs-add-skill-btn">+ Add</button>' +
      '</div>';

    var grid = qs('#' + gridId, container);

    grid.addEventListener('change', function (e) {
      if (!e.target.classList.contains('cs-skill-check')) return;
      var row = e.target.closest('.cs-skill-row');
      var select = qs('.cs-skill-level', row);
      select.disabled = !e.target.checked;
    });

    var addInput = qs('.cs-add-skill-input', container);
    var addBtn = qs('.cs-add-skill-btn', container);
    function addCustomSkill() {
      var name = addInput.value.trim();
      if (!name) return;
      if (qsa('.cs-skill-row', grid).some(function (r) { return r.dataset.skill.toLowerCase() === name.toLowerCase(); })) {
        addInput.value = '';
        return;
      }
      var empty = qs('.cs-section--empty', grid);
      if (empty) empty.remove();
      grid.insertAdjacentHTML('beforeend', rowHtml(name, true));
      addInput.value = '';
    }
    addBtn.addEventListener('click', addCustomSkill);
    addInput.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { e.preventDefault(); addCustomSkill(); }
    });

    return {
      collect: function () {
        return qsa('.cs-skill-row', grid).filter(function (row) {
          return qs('.cs-skill-check', row).checked;
        }).map(function (row) {
          return { name: row.dataset.skill, level: qs('.cs-skill-level', row).value };
        });
      }
    };
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
    var blocksWrap = qs('#student-subject-blocks', form);
    var pickers = {}; // code -> { api, term }

    function subjectCheckHtml(subj) {
      return '<label class="cs-subject-check">' +
        '<input type="checkbox" class="cs-subject-pick" value="' + escapeHtml(subj.code) + '">' +
        '<span><span class="cs-subject-code">' + escapeHtml(subj.code) + '</span>' + escapeHtml(subj.name) +
        ' <span class="cs-subject-units">(' + subj.units + ' units)</span></span>' +
      '</label>';
    }

    function renderSubjectGroups() {
      var program = programSel.value;
      var year = yearSel.value;
      blocksWrap.innerHTML = '';
      pickers = {};
      if (!program || !year) {
        currentWrap.innerHTML = '';
        previousWrap.innerHTML = '';
        return;
      }
      var elig = ((BOOT.eligibility || {})[program] || {})[year];
      if (!elig) {
        currentWrap.innerHTML = '<p class="cs-section--empty">That combination isn\'t in the curriculum catalog.</p>';
        previousWrap.innerHTML = '';
        return;
      }
      currentWrap.innerHTML =
        '<h3>Current semester subjects <span class="muted">(' + escapeHtml(elig.current.term_label) + ' — ' + escapeHtml(BOOT.currentSemLabel) + ')</span></h3>' +
        '<p class="muted">Select the subjects you are taking this semester. At least one is required.</p>' +
        '<div class="cs-subject-grid">' + elig.current.subjects.map(subjectCheckHtml).join('') + '</div>';

      if (elig.previous) {
        previousWrap.innerHTML =
          '<h3>Previous semester subjects <span class="muted">(optional — ' + escapeHtml(elig.previous.term_label) + ')</span></h3>' +
          '<p class="muted">Optional: subjects from your most recently completed term.</p>' +
          '<div class="cs-subject-grid">' + elig.previous.subjects.map(subjectCheckHtml).join('') + '</div>';
      } else {
        previousWrap.innerHTML = '<p class="cs-section--empty">This is your first semester at UE, so there is no previous semester to report.</p>';
      }
    }

    function addSubjectBlock(code, name, program, termLabel, termBucket) {
      var blockId = 'cs-subj-' + code;
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
      var el = document.getElementById('cs-subj-' + code);
      if (el) el.remove();
      delete pickers[code];
    }

    [currentWrap, previousWrap].forEach(function (wrap) {
      wrap.addEventListener('change', function (e) {
        if (!e.target.classList.contains('cs-subject-pick')) return;
        var program = programSel.value;
        var year = yearSel.value;
        var elig = ((BOOT.eligibility || {})[program] || {})[year];
        var bucket = wrap === currentWrap ? 'current' : 'previous';
        var term = elig[bucket];
        var subj = term.subjects.filter(function (s) { return s.code === e.target.value; })[0];
        if (e.target.checked) {
          addSubjectBlock(subj.code, subj.name, program, term.term_label, bucket);
        } else {
          removeSubjectBlock(subj.code);
        }
      });
    });

    programSel.addEventListener('change', renderSubjectGroups);
    yearSel.addEventListener('change', renderSubjectGroups);

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      setFormError('student-error', '');

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
      if (!consent) {
        setFormError('student-error', 'Please confirm the Data Privacy notice before submitting.');
        return;
      }
      var currentChecked = qsa('.cs-subject-pick:checked', currentWrap);
      if (!currentChecked.length) {
        setFormError('student-error', 'Please select at least one current-semester subject.');
        return;
      }

      var subjects = Object.keys(pickers).map(function (code) {
        var p = pickers[code];
        return { code: code, name: p.name, term: p.termBucket, term_label: p.termLabel, skills: p.api.collect() };
      });

      var payload = {
        consent: true,
        personal_info: { name: name, ue_email: email, course: course, student_number: studentNumber, year_level: Number(year) },
        subjects: subjects
      };

      submitPayload(BOOT.submitUrl, form, payload, function () {
        form.hidden = true;
        qs('#cs-done').hidden = false;
      });
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
        '<span><span class="cs-subject-code">' + escapeHtml(subj.code) + '</span>' + escapeHtml(subj.name) +
        ' <span class="cs-subject-units">(' + subj.units + ' units)</span></span>' +
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
      var blockId = 'cs-asubj-' + code;
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
      var el = document.getElementById('cs-asubj-' + code);
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

      var name = qs('#alumni-name', form).value.trim();
      var email = qs('#alumni-email', form).value.trim();
      var course = programSel.value;
      var studentNumber = qs('#alumni-number', form).value.trim();
      var yearGraduated = qs('#alumni-year-graduated', form).value.trim();
      var consent = qs('#alumni-consent', form).checked;

      if (!name || !email || !course || !studentNumber || !yearGraduated) {
        setFormError('alumni-error', 'Please fill in every personal info field.');
        return;
      }
      if (!consent) {
        setFormError('alumni-error', 'Please confirm the Data Privacy notice before submitting.');
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
        last_semester: { program: course, term_key: termSel.value, term_label: (((BOOT.termsByProgram || {})[course] || []).filter(function (t) { return t.key === termSel.value; })[0] || {}).label },
        subjects: subjects,
        overall_skills: overallPicker ? overallPicker.collect() : [],
        employment: employment
      };

      submitPayload(BOOT.submitUrl, form, payload, function () {
        form.hidden = true;
        qs('#cs-done').hidden = false;
      });
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

    var pickers = {};

    function subjectCheckHtml(subj) {
      return '<label class="cs-subject-check">' +
        '<input type="checkbox" class="cs-subject-pick" data-program="' + escapeHtml(subj.program) + '" value="' + escapeHtml(subj.code) + '">' +
        '<span><span class="cs-subject-code">' + escapeHtml(subj.program) + ' ' + escapeHtml(subj.code) + '</span>' + escapeHtml(subj.name) +
        ' <span class="cs-subject-units">(' + escapeHtml(subj.term_label) + ')</span></span>' +
      '</label>';
    }

    function renderPool(wrapId, poolKey) {
      var wrap = document.getElementById(wrapId);
      var pool = ((BOOT.pools || {})[poolKey]) || [];
      wrap.innerHTML = '<div class="cs-subject-grid">' + pool.map(subjectCheckHtml).join('') + '</div>';
      wrap.addEventListener('change', function (e) {
        if (!e.target.classList.contains('cs-subject-pick')) return;
        var program = e.target.getAttribute('data-program');
        var code = e.target.value;
        var subj = pool.filter(function (s) { return s.code === code && s.program === program; })[0];
        var blockId = 'cs-psubj-' + program + '-' + code;
        if (e.target.checked) {
          qs('#professor-subject-blocks').insertAdjacentHTML('beforeend',
            '<div class="cs-subject-block" id="' + blockId + '" data-program="' + escapeHtml(program) + '" data-code="' + escapeHtml(code) + '">' +
              '<h4>' + escapeHtml(program) + ' ' + escapeHtml(code) + ' — ' + escapeHtml(subj.name) + '</h4>' +
              '<p class="cs-subject-term">' + escapeHtml(subj.term_label) + '</p>' +
              '<div class="cs-skill-picker"></div>' +
            '</div>'
          );
          var container = qs('#' + blockId + ' .cs-skill-picker');
          var api = buildSkillPicker(container, skillsFor(program, code), IPA_LEVELS, blockId);
          pickers[program + ':' + code] = { api: api, name: subj.name, program: program, code: code, termLabel: subj.term_label, bucket: poolKey };
        } else {
          var el = document.getElementById(blockId);
          if (el) el.remove();
          delete pickers[program + ':' + code];
        }
      });
    }

    renderPool('professor-current-subjects', 'current');
    renderPool('professor-previous-subjects', 'previous_semester');
    renderPool('professor-summer-subjects', 'previous_summer');

    var summerToggle = qs('#professor-summer-toggle', form);
    var summerWrap = qs('#professor-summer-subjects', form);
    if (summerToggle) {
      summerToggle.addEventListener('click', function () {
        var showing = !summerWrap.hidden;
        summerWrap.hidden = showing;
        summerToggle.textContent = showing ? ('+ Also report ' + (BOOT.previousSummerLabel || 'summer') + ' subjects') : '− Hide summer subjects';
      });
    }

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      setFormError('professor-error', '');

      var consent = qs('#professor-consent', form).checked;
      if (!consent) {
        setFormError('professor-error', 'Please confirm the Data Privacy notice before submitting.');
        return;
      }
      var subjectKeys = Object.keys(pickers);
      if (!subjectKeys.length) {
        setFormError('professor-error', 'Please select at least one subject you currently teach or taught last semester.');
        return;
      }

      var subjects = subjectKeys.map(function (key) {
        var p = pickers[key];
        return { program: p.program, code: p.code, name: p.name, term_label: p.termLabel, term_bucket: p.bucket, skills: p.api.collect() };
      });

      var payload = {
        consent: true,
        personal_info: {
          name: qs('#professor-name', form).value.trim() || null,
          department: qs('#professor-department', form).value.trim() || null
        },
        subjects: subjects
      };

      submitPayload(BOOT.submitUrl, form, payload, function () {
        form.hidden = true;
        qs('#cs-done').hidden = false;
      });
    });
  })();
})();

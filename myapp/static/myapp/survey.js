/* UEnvision — Feedback page surveys (SUS, UAT, Functional test cases).
   Ported from the old script.js. Loaded only on feedback.html, after script.js.
   Submissions POST to the Django URL in #page-feedback[data-submit-url];
   if that URL isn't set up yet, they fall back to localStorage (like the old version). */
(function () {
  'use strict';

  var page = document.getElementById('page-feedback');
  if (!page) return;
  var SUBMIT_URL = page.dataset.submitUrl || '';

  /* ---------- helpers ---------- */
  function qs(sel, root) { return (root || document).querySelector(sel); }
  function qsa(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  function escapeHtml(str) {
    return String(str).replace(/[&<>"']/g, function (c) {
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
    toastTimer = setTimeout(function () { toast.classList.remove('is-active'); }, 2600);
  }
  function setFormError(id, msg) {
    var p = document.getElementById(id);
    if (!p) return;
    p.textContent = msg || '';
    p.hidden = !msg;
  }

  /* ---------- survey content (same as the old script.js) ---------- */
  // Usability questions adapted from the System Usability Scale: all-positive (Sauro &
  // Lewis, 2011), in plain English, with statements that asked the same thing dropped
  // per the adviser's comments. Every item scores (answer - 1). Keep this list in the
  // same order as SUS_QUESTION_COUNT in views.py expects.
  // Statement 1 ("I would like to use UEnvision to ...") is worded for students, alumni or
  // faculty; the page gets it from SUS_FIRST_STATEMENTS in views.py (data-first-statement).
  var SUS_QUESTIONS = [
    'I would like to use UEnvision again.',
    'UEnvision is easy to use.',
    'It is easy to navigate through UEnvision.',
    'All parts of UEnvision work well together.',
    'UEnvision looks and works the same way on every page.',
    'I felt confident using UEnvision.'
  ];

  // UAT: how satisfied testers are and how UEnvision felt to use (subjective), each rated
  // 1 (Strongly disagree) to 5 (Strongly agree). Whether each feature *works* is checked
  // on the Functional test case sheet instead. Keep the count equal to
  // UAT_QUESTION_COUNT in views/feedback.py.
  var UAT_QUESTIONS = [
    'Overall, I am satisfied with UEnvision.',
    'UEnvision meets my needs for knowing which skills the IT job market asks for.',
    'The dashboard shows the in-demand skills in a way that is clear and easy to understand.',
    'The skill gap analysis helps me see which skills the curriculum should cover more.',
    'The recommendations are useful for improving the subjects I handle.',
    'I trust the results that UEnvision shows.',
    'The look and layout of UEnvision are pleasant.',
    'UEnvision responds quickly when I use it.',
    'I would recommend UEnvision to other faculty members.',
    'I would use UEnvision as part of my work.'
  ];

  // UAT for students and alumni (#uat-questions[data-audience="learner"]): the same ten
  // 1-5 statements and scoring, about their side of UEnvision. Same count as UAT_QUESTIONS.
  var UAT_QUESTIONS_STUDENT = [
    'Overall, I am satisfied with UEnvision.',
    'UEnvision helps me know which skills IT job postings ask for.',
    'My skill gap page clearly shows which in-demand skills I already have and which I still need.',
    'The job readiness score and skill comparison are easy to understand.',
    'The learning resources suggested for my skill gaps are useful to me.',
    'Answering the survey and updating My subjects & skills is easy.',
    'I trust the results that UEnvision shows.',
    'The look and layout of UEnvision are pleasant.',
    'UEnvision responds quickly when I use it.',
    'I would recommend UEnvision to other students and fresh graduates.'
  ];

  // Each case is one scenario paragraph: what the tester does and what should happen,
  // per the adviser (no separate "expected process" / "expected output" columns).
  var FUNCTIONAL_DEFAULT_ROWS = [
    { feature: 'Login', scenario: 'You open the UEnvision login page, type the email and password of your account, and click Log in. You should be taken straight to your home page (the Dashboard for faculty and administrators, My skill gap for students and alumni) with your name shown in the sidebar. If you have a Google account with the same email, clicking Continue with Google instead should log you in to that same account.' },
    { feature: 'Dashboard', scenario: 'You open the Dashboard from the sidebar. The stat cards and the Top in-demand skills chart should load and show the number of job postings and the most requested skills.' },
    { feature: 'Dashboard filters', scenario: 'On the Dashboard, you click Filter, set Number of top skills to 5 and Program to BSIT, and click Apply filters. The Top in-demand skills chart should update to show 5 skills taken only from BSIT-related job postings.' },
    { feature: 'Skill gap analysis', scenario: 'On the Dashboard, you open the Skill gap analysis tab. The Under-taught and Well-covered skill lists should appear, comparing what job postings ask for with what is taught in the subjects.' },
    { feature: 'Recommendations', scenario: 'You open Recommendations from the sidebar and choose one of your subjects. The in-demand skills that fit that subject should be listed, each with suggested learning resources.' },
    { feature: 'Export data', scenario: 'You go to Data, choose a source, and click Export. A CSV file should download containing the rows of the table you were viewing.' },
    { feature: 'Edit settings', scenario: 'You go to Settings, change your name, and click Save. Your new name should be shown right away in Settings and in the sidebar.' }
  ];

  var functionalRowCount = 0;

  /* ---------- saving ---------- */
  function saveToLocalFallback(table, rows) {
    var key = 'ue_survey_' + table;
    var existing = [];
    try { existing = JSON.parse(localStorage.getItem(key) || '[]'); } catch (e) { existing = []; }
    rows.forEach(function (row) {
      existing.push(Object.assign({}, row, { _savedAt: new Date().toISOString() }));
    });
    try { localStorage.setItem(key, JSON.stringify(existing)); } catch (e) { /* storage unavailable */ }
  }

  // Accepts one response object or an array of them (the functional sheet submits many rows).
  // `table` keeps the old Supabase table names so your schema/field names still line up.
  function saveSurveyResponse(type, table, payload, form) {
    var rows = Array.isArray(payload) ? payload : [payload];
    if (!SUBMIT_URL) {
      saveToLocalFallback(table, rows);
      return Promise.resolve({ ok: true, usedFallback: true });
    }
    var tokenInput = form && qs('input[name=csrfmiddlewaretoken]', form);
    return fetch(SUBMIT_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': tokenInput ? tokenInput.value : '' },
      credentials: 'same-origin',
      body: JSON.stringify({ type: type, table: table, rows: rows })
    }).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json().catch(function () { return {}; }).then(function (body) {
        return { ok: true, usedFallback: false, edited: !!body.edited, answers: body.answers || null };
      });
    }).catch(function (err) {
      console.error('Survey submit failed, saving locally instead:', err);
      saveToLocalFallback(table, rows);
      return { ok: true, usedFallback: true };
    });
  }
  var FALLBACK_MSG = 'Saved locally (the server endpoint isn’t connected yet).';

  /* ---------- navigation ---------- */
  function showSurveyHome() {
    qs('#feedback-home').hidden = false;
    qsa('.survey-wrap').forEach(function (el) { el.hidden = true; });
  }
  function showSurveyForm(name) {
    var target = document.getElementById('survey-' + name);
    if (!target) return;
    qs('#feedback-home').hidden = true;
    qsa('.survey-wrap').forEach(function (el) { el.hidden = true; });
    target.hidden = false;
  }

  /* ---------- Likert statements (SUS and UAT) ---------- */
  // Every point is labelled, not just the two ends.
  var LIKERT_LABELS = ['Strongly disagree', 'Disagree', 'Neutral', 'Agree', 'Strongly agree'];
  function likertHtml(questions, prefix) {
    return questions.map(function (question, i) {
      var n = i + 1;
      var options = [1, 2, 3, 4, 5].map(function (v) {
        return '<label class="likert-option"><input type="radio" name="' + prefix + '-q' + n + '" value="' + v + '" required>' +
          '<span class="likert-num">' + v + '</span><span class="likert-label">' + LIKERT_LABELS[v - 1] + '</span></label>';
      }).join('');
      return '<div class="likert-group" role="radiogroup" aria-label="' + escapeHtml(n + '. ' + question) + '">' +
        '<p class="likert-question">' + n + '. ' + escapeHtml(question) + '</p>' +
        '<div class="likert-scale">' + options + '</div></div>';
    }).join('');
  }
  function fillLikert(prefix, count, data) {
    for (var n = 1; n <= count; n++) {
      var input = qs('input[name="' + prefix + '-q' + n + '"][value="' + Number(data['q' + n]) + '"]');
      if (input) input.checked = true;
    }
  }

  /* ---------- answered surveys: shown filled in, read-only, with "Edit answers" ----------
     The page gets this account's saved answers from views/feedback.py (saved_feedback).
     Saving again replaces them on the server (one answer per account per survey). */
  var SAVED = {};
  try { SAVED = JSON.parse((qs('#saved-feedback') || {}).textContent || '{}') || {}; } catch (e) { SAVED = {}; }

  function markAnswered(kind) {
    var link = qs('.feedback-item[data-survey="' + kind + '"]', page);
    if (link && !qs('.fb-done-badge', link)) {
      var badge = document.createElement('span');
      badge.className = 'fb-done-badge';
      badge.textContent = 'Answered \u00b7 edit';
      link.insertBefore(badge, link.lastElementChild);
    }
  }

  // kind: "sus" / "uat" / "functional"; fill(saved) puts the saved answers in the form,
  // blank() empties it (for a first answer).
  function makeEditable(kind, form, fill, blank) {
    var fieldset = qs('#' + kind + '-fields');
    var bar = qs('#' + kind + '-saved');
    var submitBtn = qs('button[type=submit]', form);
    var cancelBtn = qs('[data-cancel="' + kind + '"]', form);
    var editBtn = bar && qs('[data-edit="' + kind + '"]', bar);
    var firstLabel = submitBtn.getAttribute('data-submit-label') || submitBtn.textContent;

    function lock() {
      var saved = SAVED[kind];
      setFormError(kind + '-error', '');
      if (!saved) {
        if (fieldset) fieldset.disabled = false;
        if (bar) bar.hidden = true;
        submitBtn.hidden = false; submitBtn.textContent = firstLabel;
        if (cancelBtn) cancelBtn.hidden = true;
        return;
      }
      fill(saved);
      if (fieldset) fieldset.disabled = true;
      if (bar) {
        bar.hidden = false;
        var when = qs('.fb-saved-when', bar);
        if (when) when.textContent = saved.edited_at ? 'Last edited ' + saved.edited_at + '.' :
          (saved.submitted_at ? 'Submitted ' + saved.submitted_at + '.' : '');
      }
      submitBtn.hidden = true;
      if (cancelBtn) cancelBtn.hidden = true;
      markAnswered(kind);
    }
    function edit() {
      if (fieldset) fieldset.disabled = false;
      if (bar) bar.hidden = true;
      submitBtn.hidden = false; submitBtn.textContent = 'Save changes';
      if (cancelBtn) cancelBtn.hidden = false;
      var first = fieldset && qs('input:not([type=hidden]), textarea', fieldset);
      if (first) { try { first.focus({ preventScroll: true }); } catch (e) { first.focus(); } }
    }
    if (editBtn) editBtn.addEventListener('click', edit);
    if (cancelBtn) cancelBtn.addEventListener('click', lock);
    lock();
    return {
      // After a save: show the new answers read-only (or empty the form if the server
      // wasn't reached and they were only kept in this browser).
      saved: function (result) {
        if (result && !result.usedFallback && result.answers) { SAVED[kind] = result.answers; lock(); }
        else { blank(); lock(); }
      },
      wasEditing: function () { return !!SAVED[kind]; }
    };
  }
  // -> array of answers (1-5), or null if a statement was skipped
  function readLikert(prefix, count) {
    var answers = [];
    for (var n = 1; n <= count; n++) {
      var checked = qs('input[name="' + prefix + '-q' + n + '"]:checked');
      if (!checked) return null;
      answers.push(Number(checked.value));
    }
    return answers;
  }

  /* ---------- SUS ---------- */
  function renderSusQuestions() {
    var container = qs('#sus-questions');
    if (!container || container.childElementCount) return;
    var questions = SUS_QUESTIONS.slice();
    if (container.dataset.firstStatement) questions[0] = container.dataset.firstStatement;
    container.innerHTML = likertHtml(questions, 'sus');
  }

  function computeSusScore(answers) {
    // All items are positive: each scores (answer - 1), scaled to 0-100.
    var total = 0;
    answers.forEach(function (value) { total += value - 1; });
    return Math.round(total / (4 * answers.length) * 100 * 100) / 100;
  }

  function initSusForm() {
    renderSusQuestions();
    var form = qs('#sus-form');
    var editor = makeEditable('sus', form, function (d) {
      form.reset();
      fillLikert('sus', SUS_QUESTIONS.length, d);
      qs('#sus-comments').value = d.comments || '';
    }, function () { form.reset(); });
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      setFormError('sus-error', '');
      var answers = readLikert('sus', SUS_QUESTIONS.length);
      if (!answers) { setFormError('sus-error', 'Please answer every statement before submitting.'); return; }
      var payload = {
        sus_score: computeSusScore(answers),
        comments: qs('#sus-comments').value.trim() || null
      };
      answers.forEach(function (value, i) { payload['q' + (i + 1)] = value; });
      var editing = editor.wasEditing();
      saveSurveyResponse('sus', 'sus_responses', payload, form).then(function (result) {
        editor.saved(result);
        showToast(result.usedFallback ? FALLBACK_MSG : (editing ? 'Your SUS answers were updated.' : 'Thanks! Your SUS evaluation was submitted.'));
        showSurveyHome();
      });
    });
  }

  /* ---------- UAT ---------- */
  function initUatForm() {
    var container = qs('#uat-questions');
    var questions = container && container.dataset.audience === 'learner' ? UAT_QUESTIONS_STUDENT : UAT_QUESTIONS;
    if (container && !container.childElementCount) container.innerHTML = likertHtml(questions, 'uat');
    var form = qs('#uat-form');
    var editor = makeEditable('uat', form, function (d) {
      form.reset();
      fillLikert('uat', questions.length, d);
      qs('#uat-comments').value = d.comments || '';
    }, function () { form.reset(); });
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      setFormError('uat-error', '');
      var answers = readLikert('uat', questions.length);
      if (!answers) { setFormError('uat-error', 'Please answer every statement before submitting.'); return; }
      var payload = { comments: qs('#uat-comments').value.trim() || null };
      answers.forEach(function (value, i) { payload['q' + (i + 1)] = value; });
      var editing = editor.wasEditing();
      saveSurveyResponse('uat', 'uat_responses', payload, form).then(function (result) {
        editor.saved(result);
        showToast(result.usedFallback ? FALLBACK_MSG : (editing ? 'Your UAT answers were updated.' : 'Thanks! Your UAT survey was submitted.'));
        showSurveyHome();
      });
    });
  }

  /* ---------- Functional test case sheet ---------- */
  // Each test case is a card. The given cases show the Feature and Scenario paragraph as
  // plain text (they are not meant to be edited); only cases the tester adds have boxes.
  function functionalCaseHtml(row) {
    functionalRowCount += 1;
    var idx = functionalRowCount;
    var id = 'TC-' + String(idx).padStart(2, '0');
    var custom = !row.feature;
    var head = custom
      ? '<input type="text" class="ft-feature" placeholder="Feature being tested" aria-label="Feature">'
      : '<span class="ft-feature-text">' + escapeHtml(row.feature) + '</span>';
    var scenario = custom
      ? '<textarea class="ft-scenario" rows="3" placeholder="Describe the scenario as a paragraph: what you do, and what should happen, e.g. You open ... The page should ..." aria-label="Scenario"></textarea>'
      : '<p class="ft-text ft-scenario-text">' + escapeHtml(row.scenario) + '</p>';
    var status = ['Yes', 'No'].map(function (opt) {
      return '<label class="checkbox uat-radio"><input type="radio" name="ft-status-' + idx + '" value="' + opt + '"><span>' + opt + '</span></label>';
    }).join('');
    return '<div class="ft-case" data-row="' + idx + '">' +
      '<div class="ft-case-head"><span class="ft-id">' + id + '</span>' + head +
        (custom ? '<button type="button" class="link-inline link-inline--sm ft-remove">Remove</button>' : '') + '</div>' +
      '<div class="ft-cell ft-cell--scenario"><p class="ft-label">Scenario</p>' + scenario + '</div>' +
      '<div class="ft-status-row"><span class="ft-label">Did it happen as expected?</span><div class="uat-check-options">' + status + '</div></div>' +
      '<label class="field ft-field"><span>If No, what happened instead?</span><textarea class="ft-actual" rows="2"></textarea></label>' +
      '<label class="field ft-field"><span>Comments or remarks (optional)</span><input type="text" class="ft-notes"></label>' +
    '</div>';
  }
  function addFunctionalRow(row) {
    var list = qs('#functional-rows');
    if (list) list.insertAdjacentHTML('beforeend', functionalCaseHtml(row || {}));
  }
  function renderFunctionalTable() {
    var list = qs('#functional-rows');
    if (!list || list.childElementCount) return;
    functionalRowCount = 0;
    FUNCTIONAL_DEFAULT_ROWS.forEach(addFunctionalRow);
  }
  function fieldText(card, inputSel, textSel) {
    var input = qs(inputSel, card);
    if (input) return input.value.trim();
    var text = qs(textSel, card);
    return text ? text.textContent.trim() : '';
  }
  function collectFunctionalRows() {
    var submissionId = (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : String(Date.now());
    return qsa('#functional-rows .ft-case').map(function (card) {
      var checked = qs('input[type=radio]:checked', card);
      return {
        submission_id: submissionId,
        test_case_id: qs('.ft-id', card).textContent.trim(),
        feature: fieldText(card, '.ft-feature', '.ft-feature-text'),
        scenario: fieldText(card, '.ft-scenario', '.ft-scenario-text'),
        actual_result: qs('.ft-actual', card).value.trim() || null,
        status: checked ? checked.value : '',
        notes: qs('.ft-notes', card).value.trim() || null
      };
    });
  }

  // Rebuild the sheet from saved rows: the given cases come back as plain text, added ones
  // as boxes, each with its saved Yes / No and notes.
  function fillFunctional(saved) {
    var list = qs('#functional-rows');
    if (!list) return;
    list.innerHTML = '';
    functionalRowCount = 0;
    (saved.rows || []).forEach(function (row) {
      var given = FUNCTIONAL_DEFAULT_ROWS.filter(function (d) { return d.feature === row.feature && d.scenario === row.scenario; })[0];
      addFunctionalRow(given || {});
      var card = list.lastElementChild;
      if (!given) {
        qs('.ft-feature', card).value = row.feature || '';
        qs('.ft-scenario', card).value = row.scenario || '';
      }
      if (row.status === 'Yes' || row.status === 'No') {
        var radio = qs('input[type=radio][value="' + row.status + '"]', card);
        if (radio) radio.checked = true;
      }
      qs('.ft-actual', card).value = row.actual_result || '';
      qs('.ft-notes', card).value = row.notes || '';
    });
  }
  function blankFunctional() {
    qs('#functional-form').reset();
    qs('#functional-rows').innerHTML = '';
    functionalRowCount = 0;
    renderFunctionalTable();
  }

  function initFunctionalForm() {
    renderFunctionalTable();
    var form = qs('#functional-form');
    var editor = makeEditable('functional', form, fillFunctional, blankFunctional);

    qs('#functional-add-row').addEventListener('click', function () { addFunctionalRow(); });

    qs('#functional-rows').addEventListener('click', function (e) {
      if (e.target.classList.contains('ft-remove')) {
        var card = e.target.closest('.ft-case');
        if (card) card.remove();
      }
    });

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      setFormError('functional-error', '');
      var rows = collectFunctionalRows();
      if (rows.some(function (r) { return !r.feature || !r.scenario; })) {
        setFormError('functional-error', 'Please fill in the feature and scenario of every test case you added.');
        return;
      }
      if (rows.some(function (r) { return !r.status; })) {
        setFormError('functional-error', 'Please answer Yes or No for every test case.');
        return;
      }
      if (rows.some(function (r) { return r.status === 'No' && !r.actual_result; })) {
        setFormError('functional-error', 'For every test case you answered No, please write what happened instead.');
        return;
      }
      var editing = editor.wasEditing();
      saveSurveyResponse('functional', 'functional_test_results', rows, form).then(function (result) {
        editor.saved(result);
        showToast(result.usedFallback ? FALLBACK_MSG : (editing ? 'Your test results were updated.' : 'Thanks! Your test results were submitted.'));
        showSurveyHome();
      });
    });
  }

  /* ---------- init ---------- */
  qsa('.feedback-item', page).forEach(function (link) {
    link.addEventListener('click', function (e) {
      e.preventDefault();
      showSurveyForm(link.getAttribute('data-survey'));
    });
  });
  qsa('.survey-back', page).forEach(function (btn) { btn.addEventListener('click', showSurveyHome); });

  initSusForm();
  initUatForm();
  initFunctionalForm();

  // ?survey=sus (from the "Help us evaluate UEnvision" banner) opens that survey directly.
  var wanted = new URLSearchParams(window.location.search).get('survey');
  if (wanted && /^[a-z]+$/.test(wanted)) showSurveyForm(wanted);
})();

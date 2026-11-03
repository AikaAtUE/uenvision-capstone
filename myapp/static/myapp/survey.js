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

  var UAT_CHECKS = [
    { id: 'login', label: 'Logging in (and logging out) worked as expected.' },
    { id: 'dashboard', label: 'The dashboard stats and charts loaded correctly.' },
    { id: 'filter', label: 'Filtering the dashboard updated the results correctly.' },
    { id: 'export', label: 'Exporting data from the Data page worked correctly.' },
    { id: 'settings', label: 'Editing account settings saved correctly.' }
  ];

  // Written as short scenarios ("You open ... "), per the adviser. Logging in and out are
  // left out: every tester has already done both just to reach this sheet.
  var FUNCTIONAL_DEFAULT_ROWS = [
    { feature: 'Dashboard', steps: 'You open the Dashboard from the sidebar.', expected: 'The stat cards and the Top in-demand skills chart load with job posting numbers.' },
    { feature: 'Dashboard filters', steps: 'On the Dashboard, you click Filter, set Number of top skills to 5 and Program to BSIT, and click Apply filters.', expected: 'The Top in-demand skills chart updates to show 5 skills from BSIT-related postings.' },
    { feature: 'Skill gap analysis', steps: 'On the Dashboard, you open the Skill gap analysis tab.', expected: 'The Under-taught and Well-covered skill lists are shown.' },
    { feature: 'Recommendations', steps: 'You open Recommendations from the sidebar and choose one of your subjects.', expected: 'In-demand skills that fit the subject are listed, with suggested resources.' },
    { feature: 'Export data', steps: 'You go to Data, choose a source, and click Export.', expected: 'A CSV file downloads with the rows of the table you are viewing.' },
    { feature: 'Edit settings', steps: 'You go to Settings, change your name, and click Save.', expected: 'Your new name is shown in Settings and in the sidebar.' }
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
      return { ok: true, usedFallback: false };
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

  /* ---------- SUS ---------- */
  function renderSusQuestions() {
    var container = qs('#sus-questions');
    if (!container || container.childElementCount) return;
    var questions = SUS_QUESTIONS.slice();
    if (container.dataset.firstStatement) questions[0] = container.dataset.firstStatement;
    container.innerHTML = questions.map(function (question, i) {
      var n = i + 1;
      var options = [1, 2, 3, 4, 5].map(function (v) {
        return '<label class="likert-option"><input type="radio" name="sus-q' + n + '" value="' + v + '" required><span>' + v + '</span></label>';
      }).join('');
      return '<div class="likert-group">' +
        '<p class="likert-question">' + n + '. ' + escapeHtml(question) + '</p>' +
        '<div class="likert-scale">' +
          '<span class="likert-end">Strongly disagree</span>' + options + '<span class="likert-end">Strongly agree</span>' +
        '</div></div>';
    }).join('');
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
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      setFormError('sus-error', '');
      var answers = [];
      for (var n = 1; n <= SUS_QUESTIONS.length; n++) {
        var checked = qs('input[name="sus-q' + n + '"]:checked');
        if (!checked) { setFormError('sus-error', 'Please answer every statement before submitting.'); return; }
        answers.push(Number(checked.value));
      }
      var payload = {
        sus_score: computeSusScore(answers),
        comments: qs('#sus-comments').value.trim() || null
      };
      answers.forEach(function (value, i) { payload['q' + (i + 1)] = value; });
      saveSurveyResponse('sus', 'sus_responses', payload, form).then(function (result) {
        form.reset();
        showToast(result.usedFallback ? FALLBACK_MSG : 'Thanks! Your SUS evaluation was submitted.');
        showSurveyHome();
      });
    });
  }

  /* ---------- UAT ---------- */
  function renderUatChecks() {
    var container = qs('#uat-checks');
    if (!container || container.childElementCount) return;
    container.innerHTML = UAT_CHECKS.map(function (check) {
      return '<div class="uat-check-row">' +
        '<p class="uat-check-label">' + escapeHtml(check.label) + '</p>' +
        '<div class="uat-check-options">' +
          ['Yes', 'No'].map(function (opt) {
            return '<label class="checkbox uat-radio"><input type="radio" name="uat-' + check.id + '" value="' + opt + '" required><span>' + opt + '</span></label>';
          }).join('') +
        '</div></div>';
    }).join('');
  }

  function initUatForm() {
    renderUatChecks();
    var form = qs('#uat-form');
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      setFormError('uat-error', '');
      var results = {};
      for (var i = 0; i < UAT_CHECKS.length; i++) {
        var check = UAT_CHECKS[i];
        var checked = qs('input[name="uat-' + check.id + '"]:checked');
        if (!checked) { setFormError('uat-error', 'Please answer every item before submitting.'); return; }
        results[check.id] = checked.value;
      }
      var payload = {
        login_worked: results.login,
        dashboard_worked: results.dashboard,
        filter_worked: results.filter,
        export_worked: results.export,
        settings_worked: results.settings,
        comments: qs('#uat-comments').value.trim() || null
      };
      saveSurveyResponse('uat', 'uat_responses', payload, form).then(function (result) {
        form.reset();
        showToast(result.usedFallback ? FALLBACK_MSG : 'Thanks! Your UAT survey was submitted.');
        showSurveyHome();
      });
    });
  }

  /* ---------- Functional test case sheet ---------- */
  // Each test case is a card. The given cases show Feature / Steps / Expected result as
  // plain text (they are not meant to be edited); only cases the tester adds have boxes.
  function functionalCaseHtml(row) {
    functionalRowCount += 1;
    var idx = functionalRowCount;
    var id = 'TC-' + String(idx).padStart(2, '0');
    var custom = !row.feature;
    var head = custom
      ? '<input type="text" class="ft-feature" placeholder="Feature being tested" aria-label="Feature">'
      : '<span class="ft-feature-text">' + escapeHtml(row.feature) + '</span>';
    var steps = custom
      ? '<textarea class="ft-steps" rows="2" placeholder="What the tester does, e.g. You open ..." aria-label="Scenario"></textarea>'
      : '<p class="ft-text ft-steps-text">' + escapeHtml(row.steps) + '</p>';
    var expected = custom
      ? '<textarea class="ft-expected" rows="2" placeholder="What should happen" aria-label="Expected result"></textarea>'
      : '<p class="ft-text ft-expected-text">' + escapeHtml(row.expected) + '</p>';
    var status = ['Yes', 'No'].map(function (opt) {
      return '<label class="checkbox uat-radio"><input type="radio" name="ft-status-' + idx + '" value="' + opt + '"><span>' + opt + '</span></label>';
    }).join('');
    return '<div class="ft-case" data-row="' + idx + '">' +
      '<div class="ft-case-head"><span class="ft-id">' + id + '</span>' + head +
        (custom ? '<button type="button" class="link-inline link-inline--sm ft-remove">Remove</button>' : '') + '</div>' +
      '<div class="ft-grid">' +
        '<div class="ft-cell"><p class="ft-label">Scenario</p>' + steps + '</div>' +
        '<div class="ft-cell"><p class="ft-label">Expected result</p>' + expected + '</div>' +
      '</div>' +
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
        steps: fieldText(card, '.ft-steps', '.ft-steps-text'),
        expected_result: fieldText(card, '.ft-expected', '.ft-expected-text'),
        actual_result: qs('.ft-actual', card).value.trim() || null,
        status: checked ? checked.value : '',
        notes: qs('.ft-notes', card).value.trim() || null
      };
    });
  }

  function initFunctionalForm() {
    renderFunctionalTable();
    var form = qs('#functional-form');

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
      if (rows.some(function (r) { return !r.feature || !r.steps || !r.expected_result; })) {
        setFormError('functional-error', 'Please fill in the feature, steps and expected result of every test case you added.');
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
      saveSurveyResponse('functional', 'functional_test_results', rows, form).then(function (result) {
        form.reset();
        qs('#functional-rows').innerHTML = '';
        functionalRowCount = 0;
        renderFunctionalTable();
        showToast(result.usedFallback ? FALLBACK_MSG : 'Thanks! Your test results were submitted.');
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

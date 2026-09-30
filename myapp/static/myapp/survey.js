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
  // Standard 10-item System Usability Scale (Brooke, 1986).
  var SUS_QUESTIONS = [
    'I think that I would like to use this system frequently.',
    'I found the system unnecessarily complex.',
    'I thought the system was easy to use.',
    'I think that I would need the support of a technical person to be able to use this system.',
    'I found the various functions in this system were well integrated.',
    'I thought there was too much inconsistency in this system.',
    'I would imagine that most people would learn to use this system very quickly.',
    'I found the system very cumbersome to use.',
    'I felt very confident using the system.',
    'I needed to learn a lot of things before I could get going with this system.'
  ];

  var UAT_CHECKS = [
    { id: 'login', label: 'Logging in (and logging out) worked as expected.' },
    { id: 'dashboard', label: 'The dashboard stats and charts loaded correctly.' },
    { id: 'filter', label: 'Filtering the dashboard updated the results correctly.' },
    { id: 'export', label: 'Exporting data from the Data page worked correctly.' },
    { id: 'settings', label: 'Editing account settings saved correctly.' }
  ];

  var FUNCTIONAL_DEFAULT_ROWS = [
    { feature: 'Log in', steps: 'Enter a valid email and password, click Log in.', expected: 'User is taken to the Dashboard.' },
    { feature: 'Dashboard filter', steps: 'Open Filter, uncheck a skill, click Apply filters.', expected: 'Top in-demand skills chart updates to exclude that skill.' },
    { feature: 'Export data', steps: 'Go to Data, choose a source, click Export.', expected: 'A CSV file downloads with the visible table’s rows.' },
    { feature: 'Edit settings', steps: 'Go to Settings, click Edit, change name/email, click Save.', expected: 'The new values are shown in Settings and the sidebar.' },
    { feature: 'Log out', steps: 'Click Log out in the sidebar.', expected: 'User is returned to the Log in screen.' }
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
    container.innerHTML = SUS_QUESTIONS.map(function (question, i) {
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
    // Odd items: (answer - 1). Even items: (5 - answer). Sum x 2.5 = 0-100.
    var total = 0;
    answers.forEach(function (value, idx) { total += ((idx + 1) % 2 === 1) ? (value - 1) : (5 - value); });
    return Math.round(total * 2.5 * 100) / 100;
  }

  function initSusForm() {
    renderSusQuestions();
    var form = qs('#sus-form');
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      setFormError('sus-error', '');
      var answers = [];
      for (var n = 1; n <= 10; n++) {
        var checked = qs('input[name="sus-q' + n + '"]:checked');
        if (!checked) { setFormError('sus-error', 'Please answer every statement before submitting.'); return; }
        answers.push(Number(checked.value));
      }
      var payload = {
        respondent_role: qs('#sus-role').value,
        program: qs('#sus-program').value,
        q1: answers[0], q2: answers[1], q3: answers[2], q4: answers[3], q5: answers[4],
        q6: answers[5], q7: answers[6], q8: answers[7], q9: answers[8], q10: answers[9],
        sus_score: computeSusScore(answers),
        comments: qs('#sus-comments').value.trim() || null
      };
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
          ['Yes', 'Partial', 'No'].map(function (opt) {
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
      var name = qs('#uat-name').value.trim();
      if (!name) { setFormError('uat-error', 'Please enter your name.'); return; }
      var results = {};
      for (var i = 0; i < UAT_CHECKS.length; i++) {
        var check = UAT_CHECKS[i];
        var checked = qs('input[name="uat-' + check.id + '"]:checked');
        if (!checked) { setFormError('uat-error', 'Please answer every item before submitting.'); return; }
        results[check.id] = checked.value;
      }
      var payload = {
        tester_name: name,
        tester_role: qs('#uat-role').value,
        program: qs('#uat-program').value,
        test_date: qs('#uat-date').value || null,
        login_worked: results.login,
        dashboard_worked: results.dashboard,
        filter_worked: results.filter,
        export_worked: results.export,
        settings_worked: results.settings,
        satisfaction: Number(qs('#uat-satisfaction').value),
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
  function functionalRowHtml(row) {
    functionalRowCount += 1;
    var idx = functionalRowCount;
    return '<tr data-row="' + idx + '">' +
      '<td>TC-' + String(idx).padStart(2, '0') + '</td>' +
      '<td><input type="text" class="ft-feature" value="' + escapeHtml(row.feature || '') + '"></td>' +
      '<td><input type="text" class="ft-steps" value="' + escapeHtml(row.steps || '') + '"></td>' +
      '<td><input type="text" class="ft-expected" value="' + escapeHtml(row.expected || '') + '"></td>' +
      '<td><input type="text" class="ft-actual" placeholder="What actually happened"></td>' +
      '<td><select class="ft-status"><option value="Pass">Pass</option><option value="Fail">Fail</option><option value="Blocked">Blocked</option></select></td>' +
      '<td><input type="text" class="ft-notes" placeholder="Optional"></td>' +
      '<td><button type="button" class="link-inline link-inline--sm ft-remove" aria-label="Remove row">Remove</button></td>' +
    '</tr>';
  }
  function addFunctionalRow(row) {
    var tbody = qs('#functional-rows');
    if (tbody) tbody.insertAdjacentHTML('beforeend', functionalRowHtml(row || {}));
  }
  function renderFunctionalTable() {
    var tbody = qs('#functional-rows');
    if (!tbody || tbody.childElementCount) return;
    functionalRowCount = 0;
    FUNCTIONAL_DEFAULT_ROWS.forEach(addFunctionalRow);
  }
  function collectFunctionalRows(testerName) {
    var submissionId = (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : String(Date.now());
    return qsa('#functional-rows tr').map(function (tr) {
      return {
        submission_id: submissionId,
        tester_name: testerName,
        test_case_id: tr.children[0].textContent.trim(),
        feature: qs('.ft-feature', tr).value.trim(),
        steps: qs('.ft-steps', tr).value.trim(),
        expected_result: qs('.ft-expected', tr).value.trim(),
        actual_result: qs('.ft-actual', tr).value.trim(),
        status: qs('.ft-status', tr).value,
        notes: qs('.ft-notes', tr).value.trim() || null
      };
    });
  }

  function initFunctionalForm() {
    renderFunctionalTable();
    var form = qs('#functional-form');

    qs('#functional-add-row').addEventListener('click', function () { addFunctionalRow(); });

    qs('#functional-rows').addEventListener('click', function (e) {
      if (e.target.classList.contains('ft-remove')) {
        var tr = e.target.closest('tr');
        if (tr && qsa('#functional-rows tr').length > 1) tr.remove();
        else showToast('Keep at least one test case, or use Back to cancel.', true);
      }
    });

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      setFormError('functional-error', '');
      var tester = qs('#functional-tester').value.trim();
      if (!tester) { setFormError('functional-error', 'Please enter the tester’s name.'); return; }
      var rows = collectFunctionalRows(tester);
      if (rows.some(function (r) { return !r.actual_result; })) {
        setFormError('functional-error', 'Please fill in the actual result for every test case.');
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
})();

/* UEnvision — onboarding tours (spotlight walkthrough).
   The page is dimmed, one part stays lit, and a short card with an arrow explains it.
   Four tours, each shown once per account (saved on the account through cfg.saveUrl):
     * "survey"  — on the student / alumni / professor survey, before the first answer
                   (only while survey-first.js says the survey is still required).
     * "results" — on My skill gap (students, alumni) or the Dashboard (faculty, administrators).
     * "extraction" — administrators, the first time they open Data Extraction.
     * "accounts"   — administrators, the first time they open Accounts.
                   Each runs on its own page only. Promoting someone to administrator makes
                   both unseen again (views.accounts.account_edit_view).
   How to use replays any tour with ?tour=<name>. A step whose part of the page isn't there
   (hidden for this account, or not drawn yet) is skipped, so the steps follow the real page.
   On phones the menu is hidden, so menu steps point at the ☰ button instead.
   Config: the JSON in #ue-tour-config (context_processors.onboarding_tour). */
(function () {
  'use strict';
  var cfgEl = document.getElementById('ue-tour-config');
  if (!cfgEl) return;
  var cfg = {};
  try { cfg = JSON.parse(cfgEl.textContent || '{}') || {}; } catch (e) { return; }
  var me = document.currentScript;
  var PAGE = (me && me.getAttribute('data-page')) || '';
  var CSRF = (me && me.getAttribute('data-csrf')) || '';
  var seen = (cfg.seen || []).slice();

  /* ---------------- helpers ---------------- */
  function qsa(sel) {
    try { return Array.prototype.slice.call(document.querySelectorAll(sel)); } catch (e) { return []; }   // :has() on old browsers
  }
  function isShown(el) {
    if (!el || el.closest('[hidden]')) return false;
    var r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return false;
    var cs = window.getComputedStyle(el);
    return cs.visibility !== 'hidden' && cs.display !== 'none';
  }
  function offScreen(el) {
    var r = el.getBoundingClientRect();
    return r.right <= 0 || r.left >= window.innerWidth;
  }
  // First matching element that is on the page and visible: {el, index of the selector that matched}
  function find(sels) {
    for (var i = 0; i < sels.length; i++) {
      var list = qsa(sels[i]);
      for (var j = 0; j < list.length; j++) if (isShown(list[j])) return { el: list[j], alt: i > 0 };
    }
    return null;
  }
  function isPhone() { return window.innerWidth <= 720; }
  function reduceMotion() { return window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches; }
  function el(tag, cls, html) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    return e;
  }
  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; });
  }

  /* ---------------- where are we ---------------- */
  var surveyRole = document.getElementById('student-survey-form') ? 'student'
    : document.getElementById('alumni-survey-form') ? 'alumni'
    : document.getElementById('professor-survey-form') ? 'faculty' : null;
  var resultsKind = null;
  if (PAGE === 'student_dashboard' || PAGE === 'dashboard') {
    resultsKind = document.getElementById('page-student-dashboard') ? 'learner'
      : document.getElementById('page-dashboard') ? 'faculty' : null;
  }
  var adminPage = document.getElementById('page-data-extraction') ? 'extraction'
    : document.getElementById('page-accounts') ? 'accounts' : null;
  var inApp = !!document.getElementById('app');

  /* ---------------- the tours ---------------- */
  function surveySteps(role) {
    var p = role === 'faculty' ? 'professor' : role;
    var blocks = '#' + p + '-subject-blocks';
    var skillsSection = '.cs-section:has(' + blocks + ')';
    var steps = [
      { title: 'Before you start',
        text: role === 'faculty'
          ? 'Please answer this survey once before using the rest of UEnvision. It takes about 10 minutes, and you can edit it later.'
          : 'This survey takes about ' + (role === 'alumni' ? '10' : '5 to 10') + ' minutes. Here is how to answer it, step by step.' },
      { sel: ['.survey-purpose'], title: 'Why we ask',
        text: role === 'faculty'
          ? 'Your answers show which skills each subject teaches, so UEnvision can find what the curriculum under-teaches.'
          : role === 'alumni'
          ? 'Your answers show which skills UE taught you, so UEnvision can compare them with what IT and CS jobs ask for.'
          : 'Your answers show which skills you learn in each subject, so UEnvision can compare them with what IT and CS jobs ask for.' },
      { sel: ['#' + p + '-privacy'], title: 'Agree to the privacy notice',
        text: 'Read it, then tick the box. Your answers are used only for this research.' }
    ];
    if (role !== 'faculty') {
      steps.push({ sel: ['#' + p + '-about', '.cs-row-3:has(#' + p + '-program)'], title: 'Check your details',
        text: role === 'alumni'
          ? 'Make sure your course and graduation year are right. Your subjects appear once your course is set.'
          : 'Make sure your course, year level and section are right. Your subjects appear once your course and year level are set.' });
    }
    var form = '#' + p + '-survey-form';
    function ticked() { return qsa(form + ' .cs-subject-pick:checked').length > 0; }
    var gridSel = role === 'student' ? '#student-current-subjects'
      : role === 'alumni' ? '#alumni-subjects' : '#professor-current-subjects';
    steps.push(role === 'student'
      ? { sel: ['#student-subject-tools', '#student-hint'], title: 'Ways to pick your subjects',
          text: 'Select all ticks this and last semester at once, or every subject from this and previous years. Find a subject searches by code or name.' }
      : role === 'alumni'
      ? { sel: ['#alumni-term'], title: 'Pick your last semester',
          text: 'Choose your last term at UE. Its subjects appear below, and Select all subjects from every year ticks your whole curriculum.' }
      : { sel: ['.cs-subject-tools', '.cs-section:has(#professor-current-subjects)'], title: 'Ways to find your subjects',
          text: 'Find a subject searches by code or name, and + Add a subject that isn’t listed is for electives.' });
    // the whole picker is lit: the subject search plus every semester's list (not just this
    // semester's), so earlier semesters can be ticked here too and aren't skipped
    var pickerSel = role === 'alumni' ? '.cs-section:has(#alumni-subjects)' : '#' + p + '-subject-picker';
    steps.push(
      // hands-on: the tour waits here until a subject is ticked
      { sel: [pickerSel, gridSel + ' .cs-subject-grid', gridSel], keep: true, hands: true, need: ticked,
        title: role === 'faculty' ? 'Now tick the subjects you teach' : 'Now tick your subjects',
        text: role === 'faculty'
          ? 'Tick every subject you teach this semester and every one you taught last semester. Scroll down for the earlier semesters, or type a code or name in Find a subject. A skill box opens below for each one.'
          : role === 'alumni'
          ? 'Tick the subjects you took. Scroll down for the earlier years too. A skill box opens below for each one.'
          : 'Tick the subjects you took this semester and in earlier semesters. Scroll down for the earlier ones, or type a code or name in Find a subject. A skill box opens below for each one.',
        doneText: role === 'faculty'
          ? 'Nice! Now tick the rest you teach, including last semester’s, then press Next.'
          : 'Nice! Now tick the rest you took, including earlier semesters, then press Next.' },
      { sel: [skillsSection], title: 'What is a technical skill?',
        text: 'A tool, language or method you can actually use' + (role === 'faculty' ? ' and teach' : '') + ' in IT work, like Python, SQL, Git, Figma or setting up a network. Teamwork and communication are soft skills, so leave those out here.' },
      // hands-on: the tour waits here until a skill is added to a subject
      // dropRoom: the lit area already holds the space the search results drop into
      { sel: [blocks + ' .cs-subject-block'], keep: true, hands: true, dropRoom: 290,
        need: function () { return qsa(blocks + ' .cs-chip').length > 0; },
        title: 'Search for a skill and add it',
        text: 'Click the skill box and type part of a name, like “sql” or “dock”. It searches every skill, not just the suggestions. Pick one from the list to add it.',
        doneText: 'Added! Choose its level (Introduced, Practiced or Applied), then press Next.' },
      { sel: [blocks + ' .cs-subject-block', skillsSection],
        title: role === 'faculty' ? 'Add every skill you teach' : 'Add every skill you learned',
        text: role === 'faculty'
          ? 'Add as many technical skills as each subject covers, and choose how far each is taught: Introduced, Practiced or Applied. The more you add, the more accurate the curriculum gap.'
          : 'Add as many technical skills from each subject as you can, then choose how far you got: Introduced, Practiced or Applied. The more you add, the more accurate your skill gap.' });
    if (role === 'alumni') {
      steps.push({ sel: ['#alumni-overall-skills .cs-tagbox', '#alumni-overall-skills'], title: 'Skills from your whole stay at UE',
        text: 'Some skills don’t belong to one subject, like ones you picked up in your org, capstone or on your own while at UE. Add those here, with the same search.' });
      steps.push({ sel: ['.cs-section:has(#alumni-employed-branch)'], title: 'Tell us about your work',
        text: 'Choose your employment status, then answer a few questions about your job or job search.' });
    }
    steps.push(role === 'faculty'
      ? { sel: ['.cs-submit-row'], title: 'Submit, edit any time',
          text: 'Press Submit survey. You can change your answers later under Data › Professor Survey.' }
      : { sel: ['.cs-submit-row'], title: 'Submit to see your results',
          text: 'Press Submit survey. Your own skill gap opens right away.' });
    return steps;
  }

  function resultsSteps(kind) {
    var help = { sel: ['[data-tour="nav-help"]'], menu: 'How to use', title: 'Need this again?',
                 text: 'How to use has the full guide and buttons to replay these tours.' };
    if (kind === 'learner') {
      return [
        { title: 'Your results are ready', text: 'Here is a 1-minute tour of your skill gap page.' },
        { sel: ['[data-tour="nav-gap"]'], menu: 'My skill gap', title: 'My skill gap',
          text: 'Your home page: your skills compared with what employers ask for.' },
        { sel: ['.sd-role-form'], title: 'Pick the job you want',
          text: 'Choose a job role to see the skills it asks for most. Leave it on Any IT/CS role for the overall top skills.' },
        { sel: ['.sd-stats'], title: 'Your readiness at a glance',
          text: 'Job readiness is the share of the top skills you have at Practiced or Applied.' },
        { sel: ['.sd-cols > .panel'], title: 'Compare skill by skill',
          text: 'How often jobs ask for each skill, and your level in it. Tap or point at a level to see what it means.' },
        { sel: ['#learning-resources'], title: 'Close your gaps',
          text: 'Tick the skills you want to build, then press Find resources for courses and tutorials.' },
        { sel: ['[data-tour="nav-skills"]'], menu: 'My subjects & skills', title: 'Keep your skills current',
          text: 'Finished a subject or learned something new? Update your subjects and skills here.' },
        help
      ];
    }
    return [
      { title: 'Welcome to UEnvision', text: 'Here is a 1-minute tour of the Dashboard.' },
      { sel: ['#page-dashboard .stat-grid'], title: 'The key numbers',
        text: 'Job postings analyzed, the most in-demand skill, the alignment score and the high-priority skill gaps.' },
      { sel: ['#filter-btn'], title: 'Narrow the data',
        text: 'Choose which postings and skills the charts use. Reset brings back the defaults.' },
      { sel: ['#skills-panel .tabs'], title: 'Three views',
        text: 'Top in-demand skills, how they trend over time, and the skill gap between job postings and what UE teaches.' },
      { sel: ['[data-tour="edit-survey"]'], title: 'Edit your survey',
        text: 'Change the subjects and skills you reported at any time.' },
      { sel: ['[data-tour="nav-recs"]'], menu: 'Recommendations', title: 'Recommendations',
        text: 'Training and learning resources for the in-demand skills the curriculum covers least.' },
      { sel: ['[data-tour="nav-data"]'], menu: 'Data', title: 'Data',
        text: 'The job postings, extracted skills and survey answers behind every chart. Your Professor Survey is here too.' },
      help
    ];
  }

  function extractionSteps() {
    return [
      { title: 'Data Extraction',
        text: 'This is where new job postings come in and their skills are pulled out. Here is a 1-minute tour of the page.' },
      { sel: ['.data-tabs'], title: 'Tabs only administrators see',
        text: 'Import Data, Data Extraction, Survey Responses and Recommendations are for administrators only.' },
      { sel: ['#scrape > summary', '#scrape'], title: 'Scrape job postings',
        text: 'Pick the job sites and what to search: one keyword, or the CHED list of IT and CS job roles. The pause settings keep the sites from being overloaded.' },
      { sel: ['#skills > summary', '#skills'], title: 'Extract the skills',
        text: 'Gemini reads each posting and pulls out its skills. Add your Gemini API keys here, one per line.' },
      { sel: ['#ghost > summary', '#ghost'], title: 'Mark ghost jobs',
        text: 'Postings that look fake or duplicated are only marked. Nothing is deleted.' },
      { sel: ['#run'], title: 'Run it',
        text: 'Tick the steps you want, then press Run now. Settings on this page save by themselves.' },
      { sel: ['#automation > summary', '#automation'], title: 'Or run it on a schedule',
        text: 'Turn on Automation to run every step by itself, every few days or on set weekdays.' },
      { sel: ['[data-tour="nav-console"]'], menu: 'Console', title: 'Watch a run',
        text: 'The Console shows the progress and log of every run as it happens.' }
    ];
  }

  function accountsSteps() {
    return [
      { title: 'Accounts',
        text: 'Everything about user accounts is on this page. Here is a 1-minute tour.' },
      { sel: ['#add-account-btn'], title: 'Add an account',
        text: 'Create an account for a student, alumnus, faculty member or administrator.' },
      { sel: ['.acct-toolbar'], title: 'Find an account',
        text: 'Search by name or email. Filter narrows the list by role, approval or test accounts.' },
      { sel: ['.acct-pending-note', '#accounts-table'], title: 'Approve new faculty',
        text: 'Faculty who sign up show Not approved yet. Approve real faculty, or use Move to Student for a student who picked the wrong role.' },
      { sel: ['#accounts-table .row-actions'], title: 'Edit, reset or remove',
        text: 'Change someone’s name or role, send a new temporary password, or remove the account.' }
    ];
  }

  function stepsFor(name) {
    if (name === 'survey') return surveyRole ? surveySteps(surveyRole) : null;
    if (name === 'results') return resultsKind ? resultsSteps(resultsKind) : null;
    if (name === 'extraction') return cfg.admin && adminPage === 'extraction' ? extractionSteps() : null;
    if (name === 'accounts') return cfg.admin && adminPage === 'accounts' ? accountsSteps() : null;
    return null;
  }

  /* ---------------- the overlay ---------------- */
  var run = null;          // {name, steps, i, dir}
  var ui = null;           // overlay elements
  var target = null;       // element lit up for the current step
  var raf = 0;

  function buildUI() {
    var root = el('div', 'uet');
    root.innerHTML =
      '<div class="uet-block"></div>' +
      '<div class="uet-hole is-none"></div>' +
      '<svg class="uet-arrow" aria-hidden="true" focusable="false"><path class="uet-arrow-line" d=""></path><path class="uet-arrow-head" d=""></path></svg>' +
      '<div class="uet-tip" role="dialog" aria-modal="true" aria-labelledby="uet-title" aria-describedby="uet-text"></div>';
    document.body.appendChild(root);
    ui = { root: root, block: root.querySelector('.uet-block'), hole: root.querySelector('.uet-hole'), tip: root.querySelector('.uet-tip'),
           line: root.querySelector('.uet-arrow-line'), head: root.querySelector('.uet-arrow-head') };
    if (reduceMotion()) root.classList.add('uet--still');
    root.addEventListener('click', function (e) {
      var b = e.target.closest('[data-uet]');
      if (b) act(b.getAttribute('data-uet'));
    });
    document.addEventListener('keydown', onKey, true);
    window.addEventListener('resize', schedule);
    window.addEventListener('scroll', schedule, true);
  }
  function destroyUI() {
    if (!ui) return;
    document.removeEventListener('keydown', onKey, true);
    window.removeEventListener('resize', schedule);
    window.removeEventListener('scroll', schedule, true);
    ui.root.remove();
    ui = null;
    document.documentElement.classList.remove('uet-open');
  }
  function onKey(e) {
    if (!ui) return;
    // hands-on step: keys typed in the page (the skill search uses arrows, Tab and Esc) are the page's
    if (handsOn && !ui.tip.contains(document.activeElement)) return;
    if (e.key === 'Escape') { e.preventDefault(); act('skip'); }
    else if (e.key === 'ArrowRight') { e.preventDefault(); act('next'); }
    else if (e.key === 'ArrowLeft') { e.preventDefault(); act('back'); }
    else if (e.key === 'Tab') {
      // keep keyboard focus inside the card
      var f = Array.prototype.slice.call(ui.tip.querySelectorAll('button:not([disabled])'));
      if (!f.length) return;
      var i = f.indexOf(document.activeElement);
      e.preventDefault();
      f[(i + (e.shiftKey ? -1 : 1) + f.length) % f.length].focus();
    }
  }
  function schedule() {
    if (raf) return;
    raf = window.requestAnimationFrame(function () { raf = 0; position(); });
  }

  function act(a) {
    if (!run) return;
    if (a === 'next') { if (waiting()) { nudge(); return; } go(run.i + 1, 1); }
    else if (a === 'back') go(run.i - 1, -1);
    else if (a === 'skip' || a === 'done') finish();
  }

  function go(i, dir) {
    var steps = run.steps;
    // skip steps whose part of the page isn't there (hidden for this account or not drawn yet)
    while (i >= 0 && i < steps.length) {
      var s = steps[i];
      if (!s.sel || find(s.sel) || (s.menu && menuButton())) break;
      i += dir;
    }
    if (i < 0) return;                                    // nothing before this one
    if (i >= steps.length) { finish(); return; }
    run.i = i;
    render();
  }

  function menuButton() {
    var b = document.getElementById('nav-open');
    return b && isShown(b) ? b : null;
  }

  function render() {
    var steps = run.steps, step = steps[run.i], n = steps.length;
    var text = step.text, found = step.sel ? find(step.sel) : null;
    target = found ? found.el : null;
    stopHands();
    // a hands-on step only waits when its own part is there (e.g. no subjects listed yet: just explain)
    handsOn = !!(step.hands && found && !found.alt);
    if (handsOn && step.need()) text = step.doneText || text;
    if (found && found.alt && step.altText) text = step.altText;
    if (target && step.menu && (target.closest('#sidebar') && offScreen(target))) target = null;
    if (!target && step.menu) {
      // phones: the menu is hidden behind the ☰ button
      target = menuButton();
      text = 'Open the menu (☰) and tap ' + step.menu + '. ' + text;
    }
    var last = run.i === n - 1;
    var dots = '';
    for (var k = 0; k < n; k++) dots += '<i' + (k === run.i ? ' class="is-on"' : '') + '></i>';
    ui.tip.innerHTML =
      '<p class="uet-step">Step ' + (run.i + 1) + ' of ' + n + '</p>' +
      '<h2 class="uet-title" id="uet-title">' + esc(step.title) + '</h2>' +
      '<p class="uet-text" id="uet-text">' + esc(text) + '</p>' +
      '<div class="uet-foot"><span class="uet-dots" aria-hidden="true">' + dots + '</span>' +
        '<span class="uet-btns">' +
          (last ? '' : '<button type="button" class="uet-skip" data-uet="skip">Skip tour</button>') +
          (run.i > 0 ? '<button type="button" class="btn btn-ghost btn-sm" data-uet="back">Back</button>' : '') +
          '<button type="button" class="btn btn-red btn-sm" data-uet="' + (last ? 'done' : 'next') + '"' +
            (handsOn && !step.need() ? ' aria-disabled="true"' : '') + '>' +
            (last ? 'Done' : 'Next') + '</button>' +
        '</span></div>' +
        (handsOn ? '<p class="uet-wait" role="status"' + (step.need() ? ' hidden' : '') + '>Try it on the page to continue.</p>' : '');
    ui.root.classList.toggle('uet--hands', handsOn);
    if (handsOn) startHands(step);
    if (target && handsOn && step.dropRoom) {
      // card above, the skill box under it, and the dropdown's room under that
      position();
      var top0 = isPhone() ? 76 : 24, H0 = window.innerHeight;
      var lit = litRect(target);
      var want = Math.max(top0, Math.min(ui.tip.offsetHeight + 60, H0 - lit.height - 16));
      window.scrollBy(0, lit.top - want);
    } else if (target) {
      var r = target.getBoundingClientRect();
      var topRoom = isPhone() ? 76 : 24;
      if (r.top < topRoom || r.bottom > window.innerHeight - 24) {
        var tall = r.height > window.innerHeight * 0.55;
        try { target.scrollIntoView({ block: tall ? 'start' : 'center', inline: 'nearest', behavior: 'instant' }); }
        catch (e) { target.scrollIntoView(tall); }
        if (tall) window.scrollBy(0, -topRoom);
      }
    }
    position();
    var nextBtn = ui.tip.querySelector('[data-uet="next"], [data-uet="done"]');
    if (nextBtn && !handsOn) nextBtn.focus({ preventScroll: true });
  }

  /* ---------------- hands-on steps ----------------
     The page under the spotlight can be clicked and typed in, and Next waits until the
     step's task is done (a subject ticked, a skill added). The spotlight follows the
     part as it grows (a new skill box, the search results). */
  var handsOn = false, handsTimer = 0, handsDone = false;
  function waiting() {
    var step = run && run.steps[run.i];
    return !!(handsOn && step && step.need && !step.need());
  }
  function nudge() {
    var w = ui && ui.tip.querySelector('.uet-wait');
    if (!w) return;
    w.hidden = false;
    w.classList.remove('is-nudge'); void w.offsetWidth; w.classList.add('is-nudge');
  }
  var padWas = null;
  function startHands(step) {
    handsDone = step.need();
    if (step.dropRoom && padWas === null) {
      // the last skill box may sit at the very end of the page: room to scroll it up
      padWas = document.body.style.paddingBottom;
      document.body.style.paddingBottom = (step.dropRoom + 120) + 'px';
    }
    handsTimer = window.setInterval(function () {
      if (!run || !ui) return stopHands();
      // the part grew or moved (a skill box opened, the results list dropped down)
      var found = find(step.sel);
      if (found && !found.alt) target = found.el;
      // the part under the spotlight plus the open search results, so they stay lit too
      schedule();
      var done = step.need();
      if (done === handsDone) return;
      handsDone = done;
      var btn = ui.tip.querySelector('[data-uet="next"]');
      if (btn) { if (done) btn.removeAttribute('aria-disabled'); else btn.setAttribute('aria-disabled', 'true'); }
      var w = ui.tip.querySelector('.uet-wait');
      if (w) w.hidden = done;
      var t = ui.tip.querySelector('.uet-text');
      if (t) t.textContent = done ? (step.doneText || step.text) : step.text;
      schedule();
    }, 250);
  }
  function stopHands() {
    if (handsTimer) window.clearInterval(handsTimer);
    handsTimer = 0;
    if (padWas !== null) { document.body.style.paddingBottom = padWas; padWas = null; }
  }

  function position() {
    if (!ui || !run) return;
    var W = window.innerWidth, H = window.innerHeight, phone = isPhone();
    var tip = ui.tip;
    var tipW = phone ? W - 24 : Math.min(320, W - 24);
    tip.style.width = tipW + 'px';
    var tipH = tip.offsetHeight;
    ui.line.setAttribute('d', ''); ui.head.setAttribute('d', '');
    ui.block.style.clipPath = '';
    if (!target || !document.body.contains(target)) {
      ui.hole.classList.add('is-none');
      setBox(ui.hole, W / 2, H / 2, 0, 0);
      place((W - tipW) / 2, Math.max(12, (H - tipH) / 2));
      return;
    }
    ui.hole.classList.remove('is-none');
    var r = litRect(target), pad = 6;
    var hx = Math.max(4, r.left - pad), hy = Math.max(4, r.top - pad);
    var hr = Math.min(W - 4, r.right + pad), hb = Math.min(H - 4, r.bottom + pad);
    var gap = 44, side, tx, ty, cur = run.steps[run.i];
    // hands-on part taller than the screen (every semester's subject list): keep the card
    // in a strip at the bottom, off the subjects, and let the list scroll through the lit area
    if (handsOn && cur && !cur.dropRoom && hb > H - tipH - gap - 12 && hy < H - tipH - gap - 160) hb = H - tipH - gap - 12;
    var hw = Math.max(0, hr - hx), hh = Math.max(0, hb - hy);
    setBox(ui.hole, hx, hy, hw, hh);
    // hands-on: the lit part can be clicked, everything else stays blocked
    if (handsOn) ui.block.style.clipPath = "path(evenodd, 'M0 0H" + W + 'V' + H + "H0Z M" + hx + ' ' + hy + 'h' + hw + 'v' + hh + 'h' + (-hw) + "Z')";
    if (handsOn && cur && cur.dropRoom && hy - gap - tipH >= 10) { side = 'above'; ty = hy - gap - tipH; }
    else if (hy + hh + gap + tipH <= H - 10) { side = 'below'; ty = hy + hh + gap; }
    else if (hy - gap - tipH >= 10) { side = 'above'; ty = hy - gap - tipH; }
    else if (!phone && hx + hw + gap + tipW <= W - 10) { side = 'right'; tx = hx + hw + gap; ty = clamp(hy + hh / 2 - tipH / 2, 10, H - tipH - 10); }
    else if (!phone && hx - gap - tipW >= 10) { side = 'left'; tx = hx - gap - tipW; ty = clamp(hy + hh / 2 - tipH / 2, 10, H - tipH - 10); }
    else { side = 'over'; ty = H - tipH - 12; }
    if (side === 'below' || side === 'above' || side === 'over') {
      tx = phone ? 12 : clamp(hx + hw / 2 - tipW / 2 + (hw < 220 ? 50 : 0), 12, W - tipW - 12);
    }
    place(tx, ty);
    var sx, sy, ex, ey;
    if (side === 'below' || side === 'above') {
      sx = clamp(hx + hw / 2 - 24, tx + 36, tx + tipW - 36);
      ex = clamp(sx - 26, hx + 18, hx + hw - 18);
      if (side === 'below') { sy = ty - 6; ey = hy + hh + 9; } else { sy = ty + tipH + 6; ey = hy - 9; }
    } else if (side === 'right' || side === 'left') {
      sy = ty + 28;
      ey = clamp(sy - 16, hy + 14, hy + hh - 14);
      if (side === 'right') { sx = tx - 6; ex = hx + hw + 9; } else { sx = tx + tipW + 6; ex = hx - 9; }
    } else return;
    arrow(sx, sy, ex, ey, side);
  }
  function litRect(t) {
    var r = t.getBoundingClientRect();
    if (!handsOn) return r;
    var box = { left: r.left, top: r.top, right: r.right, bottom: r.bottom };
    var cur = run && run.steps[run.i], field = cur && cur.dropRoom && t.querySelector('.cs-tagbox');
    if (field) box.bottom = Math.max(box.bottom, field.getBoundingClientRect().bottom + cur.dropRoom);
    Array.prototype.forEach.call(t.querySelectorAll('.cs-skill-results:not([hidden])'), function (x) {
      var q = x.getBoundingClientRect();
      if (q.width < 2 || q.height < 2) return;
      box.left = Math.min(box.left, q.left); box.top = Math.min(box.top, q.top);
      box.right = Math.max(box.right, q.right); box.bottom = Math.max(box.bottom, q.bottom);
    });
    box.width = box.right - box.left; box.height = box.bottom - box.top;
    return box;
  }
  function clamp(v, a, b) { return Math.max(a, Math.min(b, v)); }
  function setBox(n, x, y, w, h) { var s = n.style; s.left = x + 'px'; s.top = y + 'px'; s.width = w + 'px'; s.height = h + 'px'; }
  function place(x, y) { ui.tip.style.left = x + 'px'; ui.tip.style.top = y + 'px'; }
  function arrow(sx, sy, ex, ey, side) {
    var cx, cy;
    if (side === 'right' || side === 'left') { cx = (sx + ex) / 2; cy = Math.min(sy, ey) - 24; }
    else { cx = sx + (ex - sx) * 0.15 + (ex >= sx ? -26 : 26); cy = (sy + ey) / 2; }
    ui.line.setAttribute('d', 'M' + sx + ' ' + sy + ' Q' + cx + ' ' + cy + ' ' + ex + ' ' + ey);
    var ang = Math.atan2(ey - cy, ex - cx), L = 12, Wd = 6.5;
    var bx = ex - Math.cos(ang) * L, by = ey - Math.sin(ang) * L, px = -Math.sin(ang) * Wd, py = Math.cos(ang) * Wd;
    ui.head.setAttribute('d', 'M' + (ex + Math.cos(ang) * 2) + ' ' + (ey + Math.sin(ang) * 2) +
      ' L' + (bx + px) + ' ' + (by + py) + ' L' + (bx - px) + ' ' + (by - py) + ' Z');
  }

  /* ---------------- start / finish ---------------- */
  function hideWelcomeCard() {
    // the first-visit menu card says what the results / admin tours show, so it steps aside
    var box = document.getElementById('welcome-tips');
    if (!box) return;
    try { localStorage.setItem(box.getAttribute('data-key'), '1'); } catch (e) { /* storage blocked */ }
    box.hidden = true;
  }

  function start(name, i) {
    var steps = stepsFor(name);
    if (!steps) return false;
    if (name !== 'survey') hideWelcomeCard();
    // leave out parts this account's page doesn't have, so "Step 3 of 8" counts true
    steps = steps.filter(function (s) { return s.keep || !s.sel || find(s.sel) || (s.menu && menuButton()); });
    run = { name: name, steps: steps, i: 0 };
    if (!ui) buildUI();
    document.documentElement.classList.add('uet-open');
    go(i || 0, 1);
    return true;
  }

  function markSeen(name) {
    if (seen.indexOf(name) === -1) seen.push(name);
    if (!cfg.saveUrl) return;
    var body = new FormData();
    body.append('tour', name);
    fetch(cfg.saveUrl, {
      method: 'POST', body: body, credentials: 'same-origin',
      headers: { 'X-CSRFToken': CSRF, 'X-Requested-With': 'XMLHttpRequest' }
    }).catch(function () { /* it shows again next time; nothing else breaks */ });
  }

  function finish() {
    var name = run && run.name;
    run = null; target = null;
    stopHands(); handsOn = false;
    try { sessionStorage.removeItem('ue_tour_run'); } catch (e) { /* left over from the old two-page tour */ }
    destroyUI();
    if (!name) return;
    markSeen(name);
  }

  window.UETour = { start: start };

  /* ---------------- which tour, if any, starts on this page ---------------- */
  function pick() {
    var params = new URLSearchParams(window.location.search);
    var asked = params.get('tour');
    if (asked) {
      params.delete('tour');
      var rest = params.toString();
      try { window.history.replaceState(null, '', window.location.pathname + (rest ? '?' + rest : '') + window.location.hash); } catch (e) {}
      if (stepsFor(asked)) return { name: asked, i: 0 };
    }
    if (surveyRole && document.getElementById('survey-first') && seen.indexOf('survey') === -1) return { name: 'survey', i: 0 };
    if (resultsKind && seen.indexOf('results') === -1) return { name: 'results', i: 0 };
    // administrators: each admin page has its own tour, the first time they open that page
    if (cfg.admin && inApp && adminPage && seen.indexOf(adminPage) === -1) return { name: adminPage, i: 0 };
    return null;
  }

  function boot() {
    if (seen.indexOf('results') !== -1) hideWelcomeCard();
    var choice = pick();
    if (!choice) return;
    var tries = 0;
    (function whenFree() {
      // wait for a pop-up already on screen (e.g. "Please answer the initial survey first.")
      if (document.querySelector('.ue-modal-backdrop') && tries++ < 600) { setTimeout(whenFree, 300); return; }
      start(choice.name, choice.i);
    })();
  }

  // after the survey scripts have drawn the subjects, and fonts have settled
  if (document.readyState === 'complete') setTimeout(boot, 200);
  else window.addEventListener('load', function () { setTimeout(boot, 200); });
})();

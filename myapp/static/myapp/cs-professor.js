/* UEnvision — Professor survey page. Needs curriculum-survey.js (shared helpers) loaded first. */
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
      submitPayload = CS.submitPayload,
      surveyDraft = CS.surveyDraft,
      writeFields = CS.writeFields,
      buildSkillPicker = CS.buildSkillPicker,
      missingLevelError = CS.missingLevelError,
      IPA_LEVELS = CS.IPA_LEVELS,
      domId = CS.domId,
      termTagsHtml = CS.termTagsHtml,
      wireSubjectFilter = CS.wireSubjectFilter,
      buildOtherSubjectForm = CS.buildOtherSubjectForm,
      addedTag = CS.addedTag,
      addSelectAll = CS.addSelectAll,
      blockCloseHtml = CS.blockCloseHtml,
      insertLevelGuide = CS.insertLevelGuide;

  /* =====================================================================
     PROFESSOR SURVEY
  ===================================================================== */
  (function initProfessorSurvey() {
    var form = document.getElementById('professor-survey-form');
    if (!form) return;

    // The survey is also the professor's editable record: BOOT.record holds their
    // saved subjects (null on a first visit), which are pre-filled below.
    var pickers = {};
    var blocksWrap = qs('#professor-subject-blocks');
    insertLevelGuide(blocksWrap, IPA_LEVELS, 'How far each skill is taught (choose one per skill):');
    var statusEl = document.getElementById('professor-status');
    var saveBtn = document.getElementById('professor-save');
    // With a saved record the page opens read-only; "Edit" turns editing on, then
    // "Save changes" or "Cancel" (back to the saved record). A first answer is always editable.
    var hasRecord = !!BOOT.record;
    var editing = !hasRecord;
    var savedRecord = BOOT.record ? JSON.parse(JSON.stringify(BOOT.record)) : null;
    var savedStatus = statusEl ? statusEl.textContent : '';
    var dirty = false;
    var askFirst = CS.askFirst || function () { return Promise.resolve(true); };
    var poolOf = {};   // code -> {subj, poolKey}
    ['current', 'previous_semester', 'previous_summer'].forEach(function (key) {
      (((BOOT.pools || {})[key]) || []).forEach(function (subj) { if (!poolOf[subj.code]) poolOf[subj.code] = { subj: subj, poolKey: key }; });
    });

    function markDirty() {
      if (dirty || !hasRecord || !editing) return;
      dirty = true;
      if (statusEl) { statusEl.textContent = 'Unsaved changes'; statusEl.classList.add('is-dirty'); }
    }

    function subjectCheckHtml(subj) {
      return '<label class="cs-subject-check">' +
        '<input type="checkbox" class="cs-subject-pick" value="' + escapeHtml(subj.code) + '">' +
        '<span class="cs-subject-text"><span><span class="cs-subject-code">' + escapeHtml(subj.code) + '</span>' + escapeHtml(subj.name) + '</span>' +
        termTagsHtml(subj.code) + '</span>' +
      '</label>';
    }

    /* One "skills per subject" block. extra: {tag html, removable, custom, programs, termLabel, bucket} */
    function addBlock(code, name, skills, extra) {
      if (pickers[code]) return;
      var blockId = 'cs-psubj-' + domId(code);
      blocksWrap.insertAdjacentHTML('beforeend',
        '<div class="cs-subject-block" id="' + blockId + '" data-code="' + escapeHtml(code) + '">' +
          (extra.removable ? '' : blockCloseHtml(code)) +
          '<div class="ms-subject-head"><h4>' + escapeHtml(code) + ' — ' + escapeHtml(name) + (extra.tag ? ' ' + extra.tag : '') + '</h4>' +
          (extra.removable ? '<button type="button" class="ms-remove-subject cs-remove-added">Remove subject</button>' : '') + '</div>' +
          '<div class="cs-skill-picker"></div>' +
        '</div>'
      );
      var block = document.getElementById(blockId);
      var suggested = extra.custom ? (CS.titleSuggestions ? CS.titleSuggestions(name) : []) : skillsFor('', code);
      var api = buildSkillPicker(qs('.cs-skill-picker', block), suggested, IPA_LEVELS, blockId, skills || []);
      pickers[code] = { api: api, name: name, programs: extra.programs || [], code: code,
                        termLabel: extra.termLabel || '', bucket: extra.bucket || '', custom: !!extra.custom };
      return block;
    }
    function removeBlock(code) {
      var el = document.getElementById('cs-psubj-' + domId(code));
      if (el) el.remove();
      delete pickers[code];
    }

    function renderPool(wrapId, poolKey) {
      var wrap = document.getElementById(wrapId);
      if (!wrap) return;
      var pool = ((BOOT.pools || {})[poolKey]) || [];
      wrap.innerHTML = '<div class="cs-subject-grid">' + pool.map(subjectCheckHtml).join('') + '</div>';
      addSelectAll(wrap);
      wrap.addEventListener('change', function (e) {
        if (!e.target.classList.contains('cs-subject-pick')) return;
        var code = e.target.value;
        var subj = pool.filter(function (s) { return s.code === code; })[0];
        if (e.target.checked) {
          addBlock(code, subj.name, [], { programs: subj.programs, termLabel: subj.term_label, bucket: poolKey });
        } else {
          var n = pickers[code] ? pickers[code].api.collect().length : 0;
          if (!n) { removeBlock(code); return; }
          // keep it ticked until they confirm in the pop-up
          var box = e.target;
          box.checked = true;
          askFirst('Remove ' + code + ' and its ' + n + ' skill' + (n === 1 ? '' : 's') + ' from your record?', 'Remove').then(function (yes) {
            if (!yes) return;
            box.checked = false;
            removeBlock(code);
            updatePickedCount();
            markDirty();
            form.dispatchEvent(new Event('change'));   // keep the saved draft in step
          });
        }
      });
    }

    // filter box + running count over every subject list on the page
    var filterInput = document.getElementById('professor-subject-filter');
    var pickedCount = document.getElementById('professor-picked-count');
    function updatePickedCount() {
      if (!pickedCount) return;
      var n = Object.keys(pickers).length;
      pickedCount.textContent = n ? n + ' subject' + (n === 1 ? '' : 's') + ' selected' : 'No subjects selected yet';
    }
    if (filterInput) wireSubjectFilter(form, filterInput);
    form.addEventListener('change', function (e) {
      if (e.target.classList.contains('cs-subject-pick')) updatePickedCount();
      if (e.target === filterInput || e.target.classList.contains('cs-tag-input') || e.target.closest('.cs-other') || e.target.id === 'professor-consent' || e.target.hasAttribute('data-mirror')) return;
      markDirty();
    });

    function addCustom(subj, skills) {
      var block = addBlock(subj.code, subj.name, skills, { tag: addedTag(subj.programs), removable: true, custom: true,
                                                           programs: subj.programs, termLabel: 'Added by you', bucket: 'added' });
      updatePickedCount();
      return block;
    }

    // subjects that aren't in the lists (electives and the like)
    var otherWrap = document.getElementById('professor-other-subject');
    if (otherWrap) {
      buildOtherSubjectForm(otherWrap, {
        knownCodes: BOOT.knownCodes,
        isTaken: function (code) { return !!pickers[code]; },
        onAdd: function (subj) {
          var block = addCustom(subj, []);
          markDirty();
          block.scrollIntoView({ block: 'nearest' });
          var inp = qs('.cs-tag-input', block); if (inp) inp.focus();
        }
      });
    }
    blocksWrap.addEventListener('click', function (e) {
      var btn = e.target.closest('.cs-remove-added');
      if (!btn) return;
      var block = btn.closest('.cs-subject-block');
      var code = block.getAttribute('data-code');
      var n = pickers[code] ? pickers[code].api.collect().length : 0;
      var remove = function () {
        removeBlock(code);
        updatePickedCount();
        markDirty();
        form.dispatchEvent(new Event('change'));
      };
      if (!n) { remove(); return; }
      askFirst('Remove ' + code + ' and its ' + n + ' skill' + (n === 1 ? '' : 's') + ' from your record?', 'Remove').then(function (yes) {
        if (yes) remove();
      });
    });

    renderPool('professor-current-subjects', 'current');
    renderPool('professor-previous-subjects', 'previous_semester');
    renderPool('professor-summer-subjects', 'previous_summer');

    // pre-fill the saved record (or, on a first answer, the unfinished draft)
    function fillSubjects(list, fromDraft) {
      (list || []).forEach(function (s) {
        if (s.custom) {
          addCustom({ code: s.code, name: s.name, programs: s.programs || [] }, s.skills);
        } else if (poolOf[s.code]) {
          var box = qsa('.cs-subject-pick', form).filter(function (c) { return c.value === s.code; })[0];
          if (box) box.checked = true;
          var hit = poolOf[s.code];
          addBlock(s.code, hit.subj.name, s.skills, { programs: hit.subj.programs, termLabel: hit.subj.term_label, bucket: hit.poolKey });
        } else if (!fromDraft) {
          // reported before, but not offered in this or last semester: kept until removed
          addBlock(s.code, s.name, s.skills, { tag: '<span class="cs-added-tag">From your record</span>', removable: true });
        }
      });
      updatePickedCount();
    }
    fillSubjects(BOOT.record, false);

    var draft = surveyDraft(form, function () {
      var consentBox = document.getElementById('professor-consent');
      return {
        consent: !!(consentBox && consentBox.checked),
        subjects: qsa('.cs-subject-block', blocksWrap).map(function (b) {
          var p = pickers[b.getAttribute('data-code')];
          return { code: p.code, name: p.name, custom: p.custom, programs: p.programs, skills: p.api.collect() };
        })
      };
    }, function (d) {
      if (d.consent) writeFields({ 'professor-consent': true }, ['professor-consent']);
      if (hasRecord) {
        // unsaved changes to the saved record: show them instead of the record
        qsa('.cs-subject-pick', form).forEach(function (c) { c.checked = false; });
        qsa('.cs-subject-block', blocksWrap).forEach(function (b) { b.remove(); });
        pickers = {};
        fillSubjects(d.subjects, false);
      } else {
        fillSubjects(d.subjects, true);
      }
    }, hasRecord ? {
      restoredText: 'We filled in the changes you hadn\u2019t saved yet. Press Save changes to keep them.',
      resetLabel: 'Discard changes',
      resetQuestion: 'Discard the changes you hadn\u2019t saved? Your saved subjects and skills will be shown again.',
      statusText: 'Your unsaved changes are kept on this device until you save or log out.'
    } : null);

    window.addEventListener('beforeunload', function (e) {
      if (!dirty) return;
      e.preventDefault();
      e.returnValue = '';
    });

    // Untick every subject and remove every skill block, then fill in `list` (the saved
    // record on Cancel, nothing on "Clear all answers").
    function resetTo(list) {
      qsa('.cs-subject-pick', form).forEach(function (c) { c.checked = false; });
      qsa('.cs-subject-block', blocksWrap).forEach(function (b) { b.remove(); });
      pickers = {};
      fillSubjects(list, false);
      if (CS.refreshSelectAll) CS.refreshSelectAll();
      updatePickedCount();
    }

    var editBtns = qsa('[data-ps-edit]', form);
    var cancelBtn = document.getElementById('professor-cancel');
    var clearBtn = document.getElementById('professor-clear');
    function setEditing(on) {
      editing = on;
      form.classList.toggle('is-readonly', !on);
      qsa('input, select, textarea, button', form).forEach(function (el) {
        if (el.type === 'hidden' || el.hasAttribute('data-ps-action')) return;
        el.disabled = !on;
      });
      editBtns.forEach(function (b) { b.hidden = on; });
      if (saveBtn) saveBtn.hidden = !on;
      if (cancelBtn) cancelBtn.hidden = !on;
      if (clearBtn) clearBtn.hidden = !on;
      if (on && CS.refreshSelectAll) CS.refreshSelectAll();   // a "Select all" with nothing to tick stays off
    }
    if (hasRecord) setEditing(false);
    if (hasRecord && draft.restored) {
      // they left while editing: carry on editing where they stopped
      setEditing(true);
      markDirty();
    }
    editBtns.forEach(function (b) {
      b.addEventListener('click', function () {
        setEditing(true);
        if (statusEl) statusEl.textContent = 'Editing: press Save changes when you are done.';
        var first = qs('#professor-subject-filter', form);
        if (first) { try { first.focus({ preventScroll: true }); } catch (e) { first.focus(); } }
      });
    });
    if (cancelBtn) {
      cancelBtn.addEventListener('click', function () {
        var back = function () {
          dirty = false;
          if (statusEl) { statusEl.classList.remove('is-dirty'); statusEl.textContent = savedStatus; }
          setFormError('professor-error', '');
          resetTo(savedRecord);
          draft.discard();   // the kept unsaved changes go too
          setEditing(false);
          if (editBtns.length) editBtns[editBtns.length - 1].focus();
        };
        if (!dirty) { back(); return; }
        askFirst('Discard your changes? Your saved subjects and skills will be shown again.', 'Discard changes').then(function (yes) {
          if (yes) back();
        });
      });
    }
    if (CS.wireClearAll) {
      CS.wireClearAll(clearBtn, function () {
        resetTo([]);
        setFormError('professor-error', '');
        markDirty();
        form.dispatchEvent(new Event('change'));
      }, draft, hasRecord ? 'Clear all your answers on this page? Nothing is saved until you press Save changes.' : null);
    }

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      setFormError('professor-error', '');
      var levelError = missingLevelError(form);
      if (levelError) { setFormError('professor-error', levelError); return; }

      var consentBox = qs('#professor-consent', form);
      if (consentBox && !consentBox.checked) {
        setFormError('professor-error', 'Please tick “I have read the Data Privacy Notice” just above the Submit button.');
        return;
      }
      var subjectKeys = qsa('.cs-subject-block', blocksWrap).map(function (b) { return b.getAttribute('data-code'); });
      if (!subjectKeys.length) {
        setFormError('professor-error', 'Please select at least one subject you currently teach or taught last semester.');
        return;
      }
      var skillsError = CS.missingSkillsError(blocksWrap);
      if (skillsError) { setFormError('professor-error', skillsError); return; }

      var subjects = subjectKeys.map(function (key) {
        var p = pickers[key];
        var out = { code: p.code, name: p.name, programs: p.programs, term_label: p.termLabel, term_bucket: p.bucket, skills: p.api.collect() };
        if (p.custom) out.custom = true;
        return out;
      });

      // consent is given once; later saves carry it forward
      var payload = { consent: true, subjects: subjects };
      if (saveBtn) saveBtn.textContent = 'Saving…';

      submitPayload(BOOT.submitUrl, form, payload, function (body) {
        if (saveBtn) saveBtn.textContent = hasRecord ? 'Save changes' : 'Submit survey';
        if (!body || body.ok !== true) return;   // offline fallback: nothing saved on the server
        dirty = false;
        if (body.created) {
          draft.clear();
          showToast('Thank you! Your subjects and skills were saved. You can edit them here any time.');
          setTimeout(function () { window.location.reload(); }, 1200);
          return;
        }
        savedRecord = subjects.map(function (s) {
          return { code: s.code, name: s.name, custom: !!s.custom, programs: s.programs || [], skills: s.skills };
        });
        draft.discard();   // saved: nothing unsaved to keep (later edits are kept again)
        savedStatus = 'Saved just now';
        if (statusEl) { statusEl.classList.remove('is-dirty'); statusEl.textContent = savedStatus; }
        setEditing(false);
        showToast('Your subjects and skills were saved.');
      }, function (msg) {
        if (saveBtn) saveBtn.textContent = hasRecord ? 'Save changes' : 'Submit survey';
        setFormError('professor-error', msg);
      });
    });
  })();
})();

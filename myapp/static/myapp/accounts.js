document.addEventListener('DOMContentLoaded', () => {
  const $ = id => document.getElementById(id);
  const show = id => $(id).classList.add('is-active');
  const hide = id => $(id).classList.remove('is-active');

  /* ---------- generic confirmation dialog ---------- */
  let onYes = null;
  function confirmThen(message, yesLabel, danger, callback){
    $('confirm-text').textContent = message;
    const yes = $('confirm-yes');
    yes.textContent = yesLabel;
    yes.className = 'btn ' + (danger ? 'btn-red' : 'btn-navy');
    onYes = callback;
    show('confirm-backdrop');
  }
  $('confirm-cancel').addEventListener('click', () => { onYes = null; hide('confirm-backdrop'); });
  $('confirm-yes').addEventListener('click', () => {
    const cb = onYes;
    onYes = null;
    hide('confirm-backdrop');
    if (cb) cb();
  });

  /* ---------- open / close dialogs ---------- */
  $('add-account-btn').addEventListener('click', () => { $('add-form').reset(); show('add-backdrop'); });
  document.querySelectorAll('[data-close]').forEach(btn =>
    btn.addEventListener('click', () => hide(btn.dataset.close)));

  /* ---------- row actions ---------- */
  let editingRow = null;
  const actionForm = $('action-form');

  function submitAction(url){
    actionForm.action = url;
    actionForm.submit();
  }

  $('accounts-table').addEventListener('click', e => {
    const btn = e.target.closest('button[data-action]');
    if (!btn) return;
    const row = btn.closest('tr');
    const d = row.dataset;
    const label = `${d.name} (${d.email})`;

    if (btn.dataset.action === 'edit'){
      editingRow = row;
      $('edit-form').action = d.editUrl;
      $('edit-last').value = d.last;
      $('edit-first').value = d.first;
      $('edit-middle').value = d.middle;
      $('edit-email').value = d.email;
      $('edit-type').value = d.type;
      // an administrator can't change their own role (no locking yourself out)
      $('edit-type').disabled = d.self === '1';
      $('edit-type-hint').textContent = d.self === '1'
        ? "You can't change your own role. Ask another administrator."
        : "Dummy accounts' survey answers, including ones already submitted, are kept out of the real results.";
      show('edit-backdrop');
    } else if (btn.dataset.action === 'approve'){
      confirmThen(`Approve ${label} as faculty? They'll get full access and an email saying so.`,
        'Yes, approve', false, () => submitAction(d.approveUrl));
    } else if (btn.dataset.action === 'reset'){
      confirmThen(`Reset the password for ${label}? A temporary password will be emailed to them, and they'll choose a new one when they log in.`,
        'Yes, reset', false, () => submitAction(d.resetUrl));
    } else if (btn.dataset.action === 'delete'){
      confirmThen(`Permanently remove the account for ${label}? This cannot be undone.`,
        'Yes, remove', true, () => submitAction(d.deleteUrl));
    }
  });

  // Saving an edit asks for confirmation first; native form.submit() skips this handler.
  $('edit-form').addEventListener('submit', e => {
    e.preventDefault();
    const name = editingRow ? editingRow.dataset.name : 'this account';
    const sel = $('edit-type');
    const before = editingRow ? editingRow.dataset.type : sel.value;
    const after = sel.value;
    let extra = '';
    if (!sel.disabled && after !== before) {
      const label = sel.options[sel.selectedIndex].text;
      extra = ` Their role changes from ${editingRow.dataset.typeLabel} to ${label}.`;
      // dummy types and Developer both save their survey answers as dummy (test) data
      const dummyAnswers = t => t.startsWith('dummy_') || t === 'developer';
      const wasDummy = dummyAnswers(before), isDummy = dummyAnswers(after);
      if (isDummy && !wasDummy) extra += ' Their survey answers will move to dummy (test) data and stop counting in the real results.';
      if (!isDummy && wasDummy) extra += ' Their survey answers will move back into the real results.';
      if (after === 'administrator') extra += ' Administrators can manage every account and all data.';
      if (after === 'developer') extra += ' Developers can manage every account and all data, like an administrator.';
    }
    confirmThen(`Save these changes to ${name}?${extra}`, 'Yes, save', false, () => $('edit-form').submit());
  });
});

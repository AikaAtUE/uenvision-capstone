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
      show('edit-backdrop');
    } else if (btn.dataset.action === 'reset'){
      confirmThen(`Reset the password for ${label} to the default password? They will need to log in with it again.`,
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
    confirmThen(`Save these changes to ${name}?`, 'Yes, save', false, () => $('edit-form').submit());
  });
});

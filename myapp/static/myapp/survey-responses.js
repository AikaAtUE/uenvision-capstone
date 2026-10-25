// Data > Survey Responses: select rows and delete them after a confirmation.
document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('sr-delete-form');
  if (!form) return;
  const $ = id => document.getElementById(id);
  const boxes = () => [...form.querySelectorAll('input[name="ids"]')];
  const bulkBtn = $('sr-delete-selected');
  const all = $('sr-select-all');

  function refresh() {
    const picked = boxes().filter(b => b.checked).length;
    bulkBtn.disabled = picked === 0;
    bulkBtn.textContent = picked ? `Delete selected (${picked})` : 'Delete selected';
    if (all) all.checked = picked > 0 && picked === boxes().length;
  }

  let onYes = null;
  function confirmThen(text, cb) {
    $('sr-confirm-text').textContent = text;
    onYes = cb;
    $('sr-confirm').classList.add('is-active');
  }
  $('sr-confirm-cancel').addEventListener('click', () => { onYes = null; $('sr-confirm').classList.remove('is-active'); });
  $('sr-confirm-yes').addEventListener('click', () => {
    const cb = onYes; onYes = null;
    $('sr-confirm').classList.remove('is-active');
    if (cb) cb();
  });

  if (all) all.addEventListener('change', () => { boxes().forEach(b => { b.checked = all.checked; }); refresh(); });
  form.addEventListener('change', e => { if (e.target.name === 'ids') refresh(); });

  bulkBtn.addEventListener('click', () => {
    const n = boxes().filter(b => b.checked).length;
    if (!n) return;
    confirmThen(`Permanently delete ${n} survey response${n === 1 ? '' : 's'}? This can't be undone.`, () => form.submit());
  });

  form.addEventListener('click', e => {
    const btn = e.target.closest('[data-delete-one]');
    if (!btn) return;
    const label = btn.closest('tr').dataset.label;
    confirmThen(`Permanently delete survey response ${label}? This can't be undone.`, () => {
      boxes().forEach(b => { b.checked = b.value === btn.dataset.deleteOne; });
      form.submit();
    });
  });
  refresh();
});

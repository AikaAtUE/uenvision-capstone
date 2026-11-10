/* Import Data: adapt the form to what is being imported. */
(function () {
  'use strict';
  const type = document.getElementById('import-type');
  if (!type) return;
  const files = document.getElementById('import-files');
  const hint = document.getElementById('file-hint');
  const label = document.getElementById('file-label');
  const compileRow = document.getElementById('compile-row');
  const mergeText = document.getElementById('mode-merge-text');
  const replaceText = document.getElementById('mode-replace-text');
  const datasetFields = document.getElementById('dataset-fields');
  const datasetName = document.getElementById('dataset-name');

  function apply() {
    const isJson = type.value.indexOf('json_') === 0;
    const isDataset = type.value === 'csv_dataset';
    if (datasetFields) {
      datasetFields.hidden = !isDataset;
      datasetName.required = isDataset;
    }
    files.accept = isJson ? '.json,.zip' : '.csv';
    files.multiple = isJson;
    files.value = '';
    label.textContent = isJson ? 'Files' : 'CSV file';
    hint.textContent = isJson
      ? 'Select .json files, or one .zip containing them (best for hundreds of files).'
      : isDataset
        ? 'Select one UTF-8 CSV with a header row and one job posting per row.'
        : 'Select one UTF-8 CSV with a header row. It must include a job_id column.';
    compileRow.hidden = !isJson;
    compileRow.style.display = isJson ? '' : 'none';
    mergeText.textContent = isJson
      ? 'Keep what I have and add only jobs that aren’t already there'
      : isDataset
        ? 'Merge — add only jobs that aren’t already in this dataset'
        : 'Merge — add only rows whose job_id isn’t already in the file';
    replaceText.textContent = isJson
      ? 'Overwrite existing job files with the imported version'
      : isDataset
        ? 'Replace this dataset’s file (skills already extracted from it are kept)'
        : 'Replace the whole file with the imported CSV';
  }
  type.addEventListener('change', apply);
  apply();

  document.querySelectorAll('time.js-time').forEach(t => {
    const d = new Date(t.getAttribute('datetime'));
    if (!isNaN(d)) t.textContent = d.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
  });
})();

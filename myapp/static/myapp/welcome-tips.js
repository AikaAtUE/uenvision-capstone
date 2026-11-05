/* UEnvision: first-visit introduction. The first time an account opens UEnvision in a
   browser, a card lists every menu item with what it does (taken from each item's
   data-tip, which also shows as a tooltip on hover). "Got it" hides it for good, and so does
   opening How to use; it never shows on About or How to use. */
(function () {
  'use strict';
  var box = document.getElementById('welcome-tips');
  if (!box) return;
  var key = box.getAttribute('data-key');
  var page = box.getAttribute('data-page') || '';
  // How to use is the full guide, so opening it counts as "Got it" (never shown again);
  // About is about the system, not the menu, so the card just stays out of its way there.
  if (page === 'help') { try { localStorage.setItem(key, '1'); } catch (e) {} return; }
  if (page === 'about') return;
  var seen = false;
  try { seen = !!localStorage.getItem(key); } catch (e) { seen = true; }   // no storage: don't nag every page
  if (seen) return;
  var list = document.getElementById('welcome-tips-list');
  Array.prototype.forEach.call(document.querySelectorAll('.nav .nav-item[data-tip]'), function (a) {
    var li = document.createElement('li');
    var name = document.createElement('strong');
    name.textContent = (a.textContent || '').trim();
    li.appendChild(name);
    li.appendChild(document.createTextNode(' ' + a.getAttribute('data-tip')));
    list.appendChild(li);
  });
  if (!list.children.length) return;
  box.hidden = false;
  document.getElementById('welcome-tips-ok').addEventListener('click', function () {
    try { localStorage.setItem(key, '1'); } catch (e) { /* storage blocked */ }
    box.hidden = true;
  });
})();

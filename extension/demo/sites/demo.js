// Shows the consent UI after a short delay, the way real consent tools load
// asynchronously, so a recording shows the banner before the extension acts.
window.showLater = function (ids, ms) {
  setTimeout(() => ids.forEach((id) => (document.getElementById(id).hidden = false)), ms || 1200);
};
window.__events = [];
window.log = function (e) { window.__events.push(e); };
window.toggles = function (sel) { return [...document.querySelectorAll(sel)].map((i) => (i.checked ? 1 : 0)).join(''); };
window.closeAll = function (why) {
  if (why) log(why);
  document.querySelectorAll('.cm-ui, .cm-shade').forEach((e) => e.remove());
};

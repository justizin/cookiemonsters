// Shared by fixture pages: records which buttons were clicked so tests can
// prove the engine never pressed "accept".
window.__events = [];
function record(name) { window.__events.push(name); }
function hide(sel) { document.querySelectorAll(sel).forEach((e) => e.remove()); }

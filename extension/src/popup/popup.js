'use strict';
(async function () {
  const api = globalThis.browser || globalThis.chrome;
  const L = window.CM_LABELS;
  const [tab] = await api.tabs.query({ active: true, currentWindow: true });
  const info = await api.runtime.sendMessage({ type: 'cm:popup', tabId: tab.id });
  const main = document.getElementById('main');
  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  };
  document.getElementById('site').textContent = info.site || '';
  if (!info.site) {
    main.replaceChildren(el('p', 'muted', 'cookiemonsters does not run on this kind of page.'));
    return;
  }
  const toggle = document.getElementById('toggle');
  toggle.hidden = false;
  toggle.textContent = info.disabled ? 'Run on this site' : "Don't run on this site";
  toggle.addEventListener('click', async () => {
    const r = await api.runtime.sendMessage({ type: 'cm:toggle-site', site: info.site });
    toggle.textContent = r.disabled ? 'Run on this site' : "Don't run on this site";
  });

  const e = info.entry;
  if (!e) return;
  main.replaceChildren();

  const server = e.server;
  const card = el('div', 'card');
  const row = el('div', 'row');
  const g = server ? server.grade : e.localGrade;
  row.append(el('div', 'grade ' + g, g));
  const right = el('div');
  if (server) {
    right.append(el('div', 'headline', 'Site grade ' + server.grade + ' · ' + server.score + '/100'));
    right.append(el('div', 'small muted', (L.confidence[server.confidence] || '') + ' (' + server.reports + ')'));
  } else {
    right.append(el('div', 'headline', 'This visit: grade ' + e.localGrade));
    right.append(el('div', 'small muted', info.lookups ? 'No site grade yet.' : 'Grade for this visit only. Site grades need a server (see Settings).'));
  }
  row.append(right);
  card.append(row);
  main.append(card);

  main.append(el('h2', null, 'What happened'));
  main.append(el('p', null, L.outcomes[e.result.outcome] || e.result.outcome));
  const facts = [];
  if (e.result.clicks) facts.push(e.result.clicks + (e.result.clicks === 1 ? ' click' : ' clicks'));
  if (e.result.toggles_unticked) facts.push(e.result.toggles_unticked + ' switches turned off');
  if (e.result.cmp && e.result.cmp !== 'none') facts.push('banner: ' + e.result.cmp);
  if (facts.length) main.append(el('p', 'small muted', facts.join(' · ')));
  if (e.result.flags.length) {
    const ul = el('ul');
    for (const f of e.result.flags) ul.append(el('li', null, L.flags[f] || f));
    main.append(ul);
  }
})();

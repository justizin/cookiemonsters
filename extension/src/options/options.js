'use strict';
(async function () {
  const api = globalThis.browser || globalThis.chrome;
  const DEFAULTS = { serverUrl: '', reporting: false, lookups: false, token: '', paused: false, disabledSites: [], allowReserved: false };
  const $ = (id) => document.getElementById(id);
  const status = (t) => ($('status').textContent = t);
  let s = Object.assign({}, DEFAULTS, (await api.storage.local.get('settings')).settings || {});

  function fill() {
    $('serverUrl').value = s.serverUrl;
    $('token').value = s.token;
    for (const k of ['reporting', 'lookups', 'paused', 'allowReserved']) $(k).checked = !!s[k];
    $('disabledSites').textContent = s.disabledSites.length ? 'Not running on: ' + s.disabledSites.join(', ') : '';
  }

  function origin(url) {
    try {
      const u = new URL(url);
      const local = ['127.0.0.1', 'localhost', '[::1]'].includes(u.hostname);
      if (u.protocol !== 'https:' && !(u.protocol === 'http:' && local)) return null;
      return u.origin;
    } catch (e) {
      return null;
    }
  }

  async function checkGrant() {
    const o = origin(s.serverUrl);
    if (!o || !api.permissions) return ($('grant').hidden = true);
    const has = await api.permissions.contains({ origins: [o + '/*'] });
    $('grant').hidden = has;
  }

  $('save').addEventListener('click', async () => {
    const url = $('serverUrl').value.trim();
    if (url && !origin(url)) return status('Use https://, or http:// only for 127.0.0.1 / localhost.');
    s = Object.assign(s, {
      serverUrl: url,
      token: $('token').value,
      reporting: $('reporting').checked && !!url,
      lookups: $('lookups').checked && !!url,
      paused: $('paused').checked,
      allowReserved: $('allowReserved').checked,
    });
    await api.storage.local.set({ settings: s });
    if (!s.reporting) await api.storage.local.set({ queue: {} });
    fill();
    await checkGrant();
    status('Saved.');
  });

  $('grant').addEventListener('click', async () => {
    const o = origin(s.serverUrl);
    if (o && (await api.permissions.request({ origins: [o + '/*'] }))) $('grant').hidden = true;
  });

  $('flush').addEventListener('click', async () => {
    const r = await api.runtime.sendMessage({ type: 'cm:flush-now' });
    status(r && r.sent ? 'Sent ' + r.sent + ' report(s).' : 'Nothing sent' + (r && r.status ? ' (server said ' + r.status + ')' : '') + '.');
  });

  fill();
  checkGrant();
})();

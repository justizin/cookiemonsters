/* cookiemonsters background.
 *
 * - remembers the outcome per tab (merging frames) and paints the toolbar badge;
 * - if the user configured a server and turned reporting on, queues one report
 *   per site per day and sends the queue in a batch at a random later time;
 * - if lookups are on, fetches grades by hash prefix (never by site name).
 *
 * Nothing is sent anywhere unless the user entered a server address.
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */
'use strict';

const api = globalThis.browser || globalThis.chrome;
const VERSION = api.runtime.getManifest().version;
const DEFAULTS = { serverUrl: '', reporting: false, lookups: false, token: '', paused: false, disabledSites: [], allowReserved: false };
const LOOKUP_TTL_MS = 6 * 3600 * 1000;
const META_TTL_MS = 24 * 3600 * 1000;
const NEGATIVE_TTL_MS = 30 * 60 * 1000;
const FLUSH_MIN_MIN = 5;
const FLUSH_MAX_MIN = 30;
const GRADE_COLORS = { A: '#1a7f37', B: '#4d8f1d', C: '#b08800', D: '#c25e00', F: '#cf222e', '?': '#6e7781' };

// ---- storage helpers --------------------------------------------------------

const memSession = new Map();
const session = {
  async get(k) {
    if (api.storage.session) return (await api.storage.session.get(k))[k];
    return memSession.get(k);
  },
  async set(k, v) {
    if (api.storage.session) return api.storage.session.set({ [k]: v });
    memSession.set(k, v);
  },
  async remove(k) {
    if (api.storage.session) return api.storage.session.remove(k);
    memSession.delete(k);
  },
};

async function settings() {
  const s = await api.storage.local.get('settings');
  return Object.assign({}, DEFAULTS, s.settings || {});
}

async function local(k, fallback) {
  const v = (await api.storage.local.get(k))[k];
  return v === undefined ? fallback : v;
}

function utcDay() {
  return new Date().toISOString().slice(0, 10);
}

function browserFamily() {
  const ua = navigator.userAgent;
  if (/Firefox\//.test(ua)) return 'firefox';
  if (/Edg\//.test(ua)) return 'edge';
  if (/Chrome\//.test(ua)) return 'chrome';
  if (/Safari\//.test(ua)) return 'safari';
  return 'other';
}

function siteForUrl(url, s) {
  try {
    const u = new URL(url);
    if (u.protocol !== 'http:' && u.protocol !== 'https:') return null;
    const r = CMSite.siteOf(u.hostname, s.allowReserved);
    return r ? r.site : null;
  } catch (e) {
    return null;
  }
}

function serverBase(s) {
  const raw = (s.serverUrl || '').trim().replace(/\/+$/, '');
  if (!raw) return null;
  try {
    const u = new URL(raw);
    const local = u.hostname === '127.0.0.1' || u.hostname === 'localhost' || u.hostname === '[::1]';
    if (u.protocol !== 'https:' && !(u.protocol === 'http:' && local)) return null; // never send over plain HTTP to a remote host
    return u.origin + u.pathname.replace(/\/+$/, '');
  } catch (e) {
    return null;
  }
}

// ---- badge --------------------------------------------------------------------

async function paint(tabId) {
  const t = await session.get('tab:' + tabId);
  let text = '';
  let color = GRADE_COLORS['?'];
  if (t) {
    const grade = (t.server && t.server.grade) || t.localGrade;
    if (grade) {
      text = grade;
      color = GRADE_COLORS[grade] || color;
    }
  }
  try {
    await api.action.setBadgeText({ tabId, text });
    await api.action.setBadgeBackgroundColor({ tabId, color });
  } catch (e) {
    /* tab closed */
  }
}

// ---- reports --------------------------------------------------------------------

function better(a, b) {
  // Prefer the frame that actually found a banner over one that found nothing.
  if (!a) return b;
  if (a.outcome === 'no_banner' && b.outcome !== 'no_banner') return b;
  if (b.outcome === 'no_banner' && a.outcome !== 'no_banner') return a;
  return b;
}

async function enqueue(site, result, s) {
  const day = utcDay();
  const sent = await local('sent', {});
  if (sent[site] === day) return; // at most one report per site per day
  const queue = await local('queue', {});
  const prev = queue[site] ? queue[site].result : null;
  queue[site] = { day, result: better(prev, result) };
  await api.storage.local.set({ queue });
  const alarm = await api.alarms.get('flush');
  if (!alarm) {
    const delay = FLUSH_MIN_MIN + Math.random() * (FLUSH_MAX_MIN - FLUSH_MIN_MIN);
    api.alarms.create('flush', { delayInMinutes: delay });
  }
}

function toWire(site, r) {
  return {
    site,
    outcome: r.outcome,
    clicks: Math.min(50, r.clicks | 0),
    toggles_unticked: Math.min(200, r.toggles_unticked | 0),
    flags: [...new Set(r.flags || [])].sort(),
    cmp: /^[a-z0-9][a-z0-9_-]{0,31}$/.test(r.cmp || '') ? r.cmp : 'generic',
    client: { extension_version: VERSION, rules_version: r.rules_version || '2026-01-01', browser: browserFamily() },
  };
}

async function flush() {
  const s = await settings();
  const base = serverBase(s);
  const queue = await local('queue', {});
  const sites = Object.keys(queue);
  if (!sites.length) return { sent: 0 };
  if (!base || !s.reporting) {
    await api.storage.local.set({ queue: {} }); // reporting was turned off: drop, never send later
    return { sent: 0, dropped: sites.length };
  }
  // Shuffle so the batch order says nothing about browsing order.
  for (let i = sites.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [sites[i], sites[j]] = [sites[j], sites[i]];
  }
  const batch = sites.slice(0, 25);
  const headers = { 'Content-Type': 'application/json' };
  if (s.token) headers.Authorization = 'Bearer ' + s.token;
  let status = 0;
  try {
    const resp = await fetch(base + '/v1/reports', {
      method: 'POST',
      headers,
      body: JSON.stringify({ reports: batch.map((site) => toWire(site, queue[site].result)) }),
      credentials: 'omit',
      cache: 'no-store',
      referrerPolicy: 'no-referrer',
    });
    status = resp.status;
  } catch (e) {
    status = 0;
  }
  const retry = status === 0 || status === 429 || status >= 500 || status === 401;
  if (!retry) {
    const sent = await local('sent', {});
    const today = utcDay();
    for (const k of Object.keys(sent)) if (sent[k] !== today) delete sent[k];
    for (const site of batch) {
      sent[site] = queue[site].day;
      delete queue[site];
    }
    await api.storage.local.set({ queue, sent });
    await clearLookupCache(); // grades just changed; cached buckets are stale
  }
  if (Object.keys(queue).length) {
    api.alarms.create('flush', { delayInMinutes: retry ? 30 + Math.random() * 30 : 1 + Math.random() * 4 });
  }
  return { sent: retry ? 0 : batch.length, status };
}

// ---- grade lookups ----------------------------------------------------------------

async function meta(base) {
  const cached = await local('meta', null);
  if (cached && cached.base === base && Date.now() - cached.ts < META_TTL_MS) return cached.meta;
  const resp = await fetch(base + '/v1/meta', { credentials: 'omit', referrerPolicy: 'no-referrer', cache: 'no-store' });
  if (!resp.ok) throw new Error('meta ' + resp.status);
  const m = await resp.json();
  await api.storage.local.set({ meta: { base, ts: Date.now(), meta: m } });
  return m;
}

async function lookup(site, s) {
  const base = serverBase(s);
  if (!base || !s.lookups) return null;
  const m = await meta(base);
  const len = Math.max(1, Math.min(4, m.lookup_prefix_hex | 0 || 1));
  const prefix = (await CMSite.hashHex(site)).slice(0, len);
  const key = 'lk:' + prefix;
  let entry = await local(key, null);
  const age = entry ? Date.now() - entry.ts : Infinity;
  const missing = entry && !entry.sites.some((x) => x.site === site);
  if (!entry || entry.base !== base || age > LOOKUP_TTL_MS || (missing && age > NEGATIVE_TTL_MS)) {
    const resp = await fetch(base + '/v1/lookup/' + prefix, { credentials: 'omit', referrerPolicy: 'no-referrer', cache: 'no-store' });
    if (!resp.ok) throw new Error('lookup ' + resp.status);
    const body = await resp.json();
    entry = { base, ts: Date.now(), sites: body.sites || [] };
    await api.storage.local.set({ [key]: entry });
  }
  return entry.sites.find((x) => x.site === site) || null;
}

async function clearLookupCache() {
  const all = await api.storage.local.get(null);
  const keys = Object.keys(all).filter((k) => k.startsWith('lk:'));
  if (keys.length) await api.storage.local.remove(keys);
}

async function pruneLookupCache() {
  const all = await api.storage.local.get(null);
  const stale = Object.keys(all).filter((k) => k.startsWith('lk:') && Date.now() - all[k].ts > LOOKUP_TTL_MS);
  if (stale.length) await api.storage.local.remove(stale);
}

// ---- messages ----------------------------------------------------------------------

async function onResult(msg, sender) {
  const tab = sender.tab;
  if (!tab || tab.id == null) return;
  const s = await settings();
  const site = siteForUrl(tab.url, s);
  if (!site) return;
  const key = 'tab:' + tab.id;
  const prev = await session.get(key);
  const sameSite = prev && prev.site === site;
  const result = better(sameSite ? prev.result : null, msg.result);
  const friction = CMScore.visitFriction(result);
  const entry = { site, result, friction, localGrade: CMScore.gradeFor(friction), server: sameSite ? prev.server : null };
  await session.set(key, entry);
  await paint(tab.id);
  if (s.reporting && serverBase(s)) await enqueue(site, result, s);
  if (s.lookups && !entry.server) {
    try {
      entry.server = await lookup(site, s);
      await session.set(key, entry);
      await paint(tab.id);
    } catch (e) {
      /* offline or no server: keep the local grade */
    }
  }
}

async function onConfig(sender) {
  const s = await settings();
  const site = sender.tab ? siteForUrl(sender.tab.url, s) : null;
  return { enabled: !s.paused && !(site && s.disabledSites.includes(site)) };
}

async function onPopup(tabId) {
  const s = await settings();
  const tab = await api.tabs.get(tabId);
  const site = siteForUrl(tab.url, s);
  const entry = await session.get('tab:' + tabId);
  return {
    site,
    entry: entry && entry.site === site ? entry : null,
    disabled: !!(site && s.disabledSites.includes(site)),
    paused: s.paused,
    connected: !!serverBase(s),
    reporting: s.reporting,
    lookups: s.lookups,
  };
}

async function toggleSite(site) {
  const s = await settings();
  const set = new Set(s.disabledSites);
  if (set.has(site)) set.delete(site);
  else set.add(site);
  s.disabledSites = [...set].sort();
  await api.storage.local.set({ settings: s });
  return { disabled: set.has(site) };
}

api.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg || typeof msg.type !== 'string') return false;
  // Only our own pages and content scripts can reach this listener (no externally_connectable).
  // Popup/settings messages are accepted only from our own extension pages. A settings page
  // opened in a tab has sender.tab set too, so check the sender's URL, not the tab.
  const fromOwnPage = typeof sender.url === 'string' && sender.url.startsWith(api.runtime.getURL(''));
  let p = null;
  if (msg.type === 'cm:config') p = onConfig(sender);
  else if (msg.type === 'cm:result') p = onResult(msg, sender).then(() => ({ ok: true }));
  else if (msg.type === 'cm:popup' && fromOwnPage) p = onPopup(msg.tabId);
  else if (msg.type === 'cm:toggle-site' && fromOwnPage) p = toggleSite(String(msg.site));
  else if (msg.type === 'cm:flush-now' && fromOwnPage) p = flush();
  if (!p) return false;
  p.then(sendResponse, (e) => sendResponse({ error: String(e) }));
  return true;
});

api.alarms.onAlarm.addListener((a) => {
  if (a.name === 'flush') flush();
  if (a.name === 'prune') pruneLookupCache();
});

api.tabs.onRemoved.addListener((tabId) => session.remove('tab:' + tabId));
api.tabs.onUpdated.addListener((tabId, info) => {
  if (info.status === 'loading' && info.url) session.remove('tab:' + tabId).then(() => paint(tabId));
});

api.runtime.onInstalled.addListener(async (details) => {
  api.alarms.create('prune', { periodInMinutes: 360 });
  if (details.reason === 'install') api.runtime.openOptionsPage();
});

/* Hostname -> registrable domain (eTLD+1). Same rules and algorithm as
 * api/cookiemonsters/domains.py; the PSL comes from generated_core.js.
 * SPDX-License-Identifier: AGPL-3.0-or-later */
(function (global) {
  'use strict';
  const RESERVED = new Set(['test', 'example', 'invalid', 'localhost', 'local', 'internal', 'home', 'lan', 'corp', 'onion', 'alt', 'arpa']);
  let psl = null;

  function load() {
    if (psl) return psl;
    const rules = new Set();
    const wild = new Set();
    const exc = new Set();
    for (const line of global.CM_CORE_DATA.psl.split('\n')) {
      if (!line) continue;
      if (line[0] === '!') exc.add(line.slice(1));
      else if (line.startsWith('*.')) wild.add(line.slice(2));
      else rules.add(line);
    }
    const tlds = new Set([...rules, ...wild].map((r) => r.split('.').pop()));
    psl = { rules, wild, exc, tlds };
    return psl;
  }

  function isIP(h) {
    return /^\d{1,3}(\.\d{1,3}){3}$/.test(h) || h.includes(':') || h.startsWith('[');
  }

  /** Returns {site, reserved} or null when the host is not a public site. */
  function siteOf(hostname, allowReserved) {
    let host = String(hostname || '').toLowerCase().replace(/\.$/, '');
    if (!host || isIP(host)) return null;
    try {
      host = new URL('http://' + host).hostname; // punycode for IDNs
    } catch (e) {
      return null;
    }
    const labels = host.split('.');
    if (labels.length < 2) return null;
    const tld = labels[labels.length - 1];
    if (RESERVED.has(tld)) return allowReserved ? { site: labels.slice(-2).join('.'), reserved: true } : null;
    const p = load();
    if (!p.tlds.has(tld)) return null;
    let best = 0;
    const n = labels.length;
    for (let i = 0; i < n; i++) {
      const cand = labels.slice(i).join('.');
      const k = n - i;
      if (p.exc.has(cand)) {
        best = k - 1;
        break;
      }
      if (p.rules.has(cand) && k > best) best = k;
      if (i > 0 && p.wild.has(cand) && k + 1 > best) best = k + 1;
    }
    if (best === 0) best = 1;
    if (n <= best) return null;
    return { site: labels.slice(-(best + 1)).join('.'), reserved: false };
  }

  async function hashHex(site) {
    const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(site));
    return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, '0')).join('');
  }

  global.CMSite = { siteOf, hashHex };
})(typeof window !== 'undefined' ? window : globalThis);

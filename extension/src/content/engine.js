/* cookiemonsters consent engine.
 *
 * Pure DOM: no extension APIs, so the same file runs in the content script and
 * in the Playwright tests. Finds a cookie banner (CMP rules first, multilingual
 * heuristics second), refuses everything non-essential with as few clicks as
 * possible, and measures how hard that was.
 *
 * Hard rules:
 *  - never click anything classified as "accept";
 *  - never follow a navigating link;
 *  - never hide or remove page content.
 *
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */
(function (global) {
  'use strict';

  const DATA = global.CM_RULES_DATA;
  const H = DATA.heuristics;
  const RX = {};
  for (const k of ['banner', 'acceptAll', 'reject', 'save', 'settings', 'accept', 'necessary', 'legitimateInterest', 'consentOrPay', 'trackerCookies']) {
    RX[k] = new RegExp(H[k], 'iu');
  }
  const MAX_TEXT = H.maxButtonText || 60;
  const MAX_CLICKS = 40;
  const CLICKABLE = 'button, [role=button], a, input[type=button], input[type=submit], [onclick]';
  const TOGGLE = 'input[type=checkbox], [role=switch], [role=checkbox], button[aria-pressed]';
  const BANNERISH =
    '[role=dialog], [role=alertdialog], [aria-modal=true], dialog[open], [id*=cookie i], [class*=cookie i], [id*=consent i], ' +
    '[class*=consent i], [id*=gdpr i], [class*=gdpr i], [id*=privacy i], [class*=privacy i], [id*=cmp i], [class*=cmp- i]';

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  // ---- DOM helpers (shadow-DOM aware) --------------------------------------

  function shadowRoots(root) {
    const out = [];
    const walk = (r) => {
      const all = r.querySelectorAll('*');
      for (let i = 0; i < all.length; i++) {
        const sr = all[i].shadowRoot;
        if (sr) {
          out.push(sr);
          walk(sr);
        }
      }
    };
    walk(root);
    return out;
  }

  function allRoots(doc) {
    return [doc, ...shadowRoots(doc)];
  }

  function qsa(roots, selector) {
    if (!selector) return [];
    const out = [];
    for (const r of roots) {
      try {
        r.querySelectorAll(selector).forEach((e) => out.push(e));
      } catch (e) {
        /* invalid selector for this engine: ignore */
      }
    }
    return out;
  }

  /** Every element under `el`, including inside open shadow roots below it. */
  function deepWithin(el, selector) {
    const roots = [el, ...(el.shadowRoot ? [el.shadowRoot] : []), ...shadowRoots(el)];
    const out = new Set();
    for (const r of roots) {
      try {
        if (r !== el && r.matches && r.matches(selector)) out.add(r);
        r.querySelectorAll(selector).forEach((e) => out.add(e));
      } catch (e) {
        /* ignore */
      }
    }
    return [...out];
  }

  function parentOf(e) {
    if (e.parentElement) return e.parentElement;
    const root = e.getRootNode && e.getRootNode();
    return root && root.host ? root.host : null;
  }

  function contains(outer, inner) {
    for (let e = inner; e; e = parentOf(e)) if (e === outer) return true;
    return false;
  }

  function visible(el) {
    if (!el || !el.isConnected) return false;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return false;
    for (let e = el; e; e = parentOf(e)) {
      const s = getComputedStyle(e);
      if (s.display === 'none' || s.visibility === 'hidden' || parseFloat(s.opacity) < 0.05) return false;
    }
    return true;
  }

  function firstVisible(list) {
    for (const e of list) if (visible(e)) return e;
    return null;
  }

  function norm(s) {
    return (s || '')
      .normalize('NFKC')
      .replace(/\s+/g, ' ')
      .replace(/^[\s"'“”‘’«»›‹>→✓✔×✕✗·•|-]+|[\s"'“”‘’«»›‹<←→✓✔×✕✗·•|.!:-]+$/g, '')
      .trim()
      .toLowerCase();
  }

  function textOf(el) {
    let t = el.tagName === 'INPUT' ? el.value : el.innerText || el.textContent;
    t = norm(t);
    if (!t) t = norm(el.getAttribute('aria-label') || el.getAttribute('title') || '');
    return t;
  }

  /** acceptAll | reject | save | settings | accept | null */
  function classify(el) {
    const t = textOf(el);
    if (!t || t.length > MAX_TEXT) return null;
    if (RX.acceptAll.test(t)) return 'acceptAll';
    if (RX.reject.test(t)) return 'reject';
    if (RX.save.test(t)) return 'save';
    if (RX.settings.test(t)) return 'settings';
    if (RX.accept.test(t)) return 'accept';
    return null;
  }

  function navigates(el) {
    if (el.tagName !== 'A') return false;
    const href = (el.getAttribute('href') || '').trim();
    if (!href || href.startsWith('#') || href.toLowerCase().startsWith('javascript:')) return false;
    if (el.getAttribute('role') === 'button') return false;
    try {
      const u = new URL(href, location.href);
      return !(u.origin === location.origin && u.pathname === location.pathname && u.search === location.search);
    } catch (e) {
      return true;
    }
  }

  function area(el) {
    const r = el.getBoundingClientRect();
    return r.width * r.height;
  }

  function inViewport(el) {
    const r = el.getBoundingClientRect();
    return r.bottom > 0 && r.right > 0 && r.top < innerHeight && r.left < innerWidth;
  }

  function contextText(el) {
    const parts = [];
    if (el.labels) for (const l of el.labels) parts.push(l.innerText || '');
    const lb = el.getAttribute('aria-labelledby');
    if (lb) {
      const root = el.getRootNode();
      for (const id of lb.split(/\s+/)) {
        const n = root.getElementById ? root.getElementById(id) : null;
        if (n) parts.push(n.innerText || '');
      }
    }
    parts.push(el.getAttribute('aria-label') || '', el.getAttribute('name') || '', el.id || '');
    let host = el;
    for (let i = 0; i < 4 && host; i++) {
      host = parentOf(host);
      if (!host) break;
      const t = host.innerText || '';
      if (t.length > 4 && t.length < 400) {
        parts.push(t);
        break;
      }
    }
    return norm(parts.join(' ')).slice(0, 500);
  }

  function isOn(t) {
    if (t.tagName === 'INPUT') return t.checked;
    if (t.hasAttribute('aria-checked')) return t.getAttribute('aria-checked') === 'true';
    if (t.hasAttribute('aria-pressed')) return t.getAttribute('aria-pressed') === 'true';
    return false;
  }

  function isDisabled(t) {
    return t.disabled || t.getAttribute('aria-disabled') === 'true' || t.getAttribute('aria-readonly') === 'true';
  }

  // ---- Detection ------------------------------------------------------------

  function ruleScopes(rule, doc) {
    if (!rule.shadowHost) return allRoots(doc);
    const hosts = qsa(allRoots(doc), rule.shadowHost);
    const roots = [doc];
    for (const h of hosts) if (h.shadowRoot) roots.push(h.shadowRoot, ...shadowRoots(h.shadowRoot));
    return roots;
  }

  function detectByRule(doc, only) {
    for (const rule of DATA.rules.cmps) {
      if (only && rule.id !== only) continue;
      const roots = ruleScopes(rule, doc);
      const hit = firstVisible(qsa(roots, rule.detect));
      if (!hit) continue;
      let container = hit;
      if (rule.container) {
        const c = qsa(roots, rule.container).find((e) => contains(e, hit) && visible(e));
        if (c && c.tagName !== 'BODY') container = c;
      }
      return { rule, roots, container };
    }
    return null;
  }

  function buttonsIn(el) {
    return deepWithin(el, CLICKABLE).filter(visible);
  }

  function heuristicCandidates(doc) {
    let cands = qsa(allRoots(doc), BANNERISH);
    if (!cands.length && doc.body) {
      const all = doc.body.querySelectorAll('div, section, aside, form, footer, dialog');
      const n = Math.min(all.length, 4000);
      for (let i = 0; i < n; i++) {
        const p = getComputedStyle(all[i]).position;
        if (p === 'fixed' || p === 'sticky') cands.push(all[i]);
      }
    }
    return cands.filter((c) => {
      if (c.tagName === 'BODY' || c.tagName === 'HTML') return false;
      const text = (c.innerText || '').slice(0, 6000);
      if (text.length > 5000 || !RX.banner.test(text)) return false;
      if (!visible(c)) return false;
      return buttonsIn(c).some((b) => {
        const k = classify(b);
        return k === 'reject' || k === 'accept' || k === 'acceptAll';
      });
    });
  }

  function detectHeuristic(doc) {
    const cands = heuristicCandidates(doc);
    // Outermost candidate: it holds the whole banner, not just one row of it.
    const outer = cands.filter((c) => !cands.some((o) => o !== c && contains(o, c)));
    if (!outer.length) return null;
    return { rule: null, roots: allRoots(doc), container: outer[0] };
  }

  function detect(doc) {
    return detectByRule(doc) || detectHeuristic(doc);
  }

  // ---- Layers -----------------------------------------------------------------

  function pick(rule, field, roots, scope) {
    if (!rule || !rule[field]) return null;
    const list = qsa(roots, rule[field]).filter(visible);
    return (scope && list.find((e) => contains(scope, e))) || list[0] || null;
  }

  function byText(scope, kinds) {
    const out = {};
    for (const b of buttonsIn(scope)) {
      const k = classify(b);
      if (k && kinds.includes(k) && !out[k] && !navigates(b)) out[k] = b;
      if (k === 'accept' || k === 'acceptAll') (out._accepts = out._accepts || []).push(b);
    }
    return out;
  }

  function firstLayer(found) {
    const { rule, roots, container } = found;
    const t = byText(container, ['reject', 'settings']);
    const accepts = [...(t._accepts || []), ...(rule ? qsa(roots, rule.accept).filter(visible) : [])];
    // A rule selector that lands on something labelled "accept" is a stale rule, not a reject button.
    const notAccept = (e) => e && !['accept', 'acceptAll'].includes(classify(e)) ? e : null;
    return {
      reject: notAccept(pick(rule, 'rejectAll', roots, null)) || t.reject || null,
      settings: notAccept(pick(rule, 'settings', roots, null)) || t.settings || null,
      accepts,
    };
  }

  function findPanel(found, doc) {
    const { rule, roots } = found;
    if (rule && rule.panel) {
      const p = firstVisible(qsa(ruleScopes(rule, doc), rule.panel));
      if (p) return p;
    }
    const again = detect(doc);
    if (again) return again.container;
    if (visible(found.container)) return found.container;
    return null;
  }

  // ---- Main -----------------------------------------------------------------

  function trackerCookiePresent(doc) {
    let names = [];
    try {
      names = (doc.cookie || '').split(';').map((c) => c.split('=')[0].trim()).filter(Boolean);
    } catch (e) {
      return false;
    }
    return names.some((n) => RX.trackerCookies.test(n));
  }

  async function waitFor(fn, timeoutMs, doc) {
    const first = fn();
    if (first || timeoutMs <= 0) return first;
    return new Promise((resolve) => {
      let done = false;
      let timer = null;
      const finish = (v) => {
        if (done) return;
        done = true;
        obs.disconnect();
        clearInterval(poll);
        clearTimeout(timer);
        resolve(v);
      };
      let pending = false;
      const check = () => {
        pending = false;
        const v = fn();
        if (v) finish(v);
      };
      const obs = new MutationObserver(() => {
        if (!pending) {
          pending = true;
          setTimeout(check, 120);
        }
      });
      obs.observe(doc.documentElement, { childList: true, subtree: true, attributes: true, attributeFilter: ['class', 'style', 'hidden', 'aria-hidden', 'open'] });
      const poll = setInterval(check, 500); // shadow roots and style changes the observer cannot see
      timer = setTimeout(() => finish(fn()), timeoutMs);
    });
  }

  async function run(opts) {
    opts = opts || {};
    const doc = opts.document || document;
    const isTop = opts.isTop != null ? opts.isTop : global === global.top;
    const timeoutMs = opts.timeoutMs != null ? opts.timeoutMs : 15000;
    const settleMs = opts.settleMs != null ? opts.settleMs : 400;
    const goneMs = opts.goneMs != null ? opts.goneMs : 2500;
    const reappearMs = opts.reappearMs != null ? opts.reappearMs : 4000;
    const flags = new Set();
    let clicks = 0;
    let toggles = 0;

    let cmp = 'none';
    const trackingEarly = trackerCookiePresent(doc);
    const found = await waitFor(() => detect(doc), timeoutMs, doc);
    if (trackingEarly || trackerCookiePresent(doc)) flags.add('tracking_before_choice');
    if (!found) {
      return isTop ? result('no_banner') : null;
    }
    await sleep(settleMs); // let the CMP finish rendering and wiring its handlers
    cmp = found.rule ? found.rule.id : 'generic';

    function result(outcome) {
      return { outcome, clicks, toggles_unticked: toggles, flags: [...flags].sort(), cmp, rules_version: DATA.rules.version };
    }

    async function click(el) {
      if (!el || clicks >= MAX_CLICKS) return false;
      if (navigates(el)) return false;
      const k = classify(el);
      // A selector pointed at something whose label says "accept": refuse to click it.
      if (k === 'accept' || k === 'acceptAll') return false;
      if (found.rule && found.rule.accept && qsa(found.roots, found.rule.accept).includes(el)) return false;
      if (!inViewport(el)) {
        flags.add('reject_needs_scroll');
        try {
          el.scrollIntoView({ block: 'center' });
        } catch (e) {
          /* ignore */
        }
      }
      clicks++;
      el.click();
      await sleep(150);
      return true;
    }

    function bannerVisible() {
      if (visible(found.container)) return true;
      return !!detect(doc);
    }

    async function gone() {
      const end = Date.now() + goneMs;
      while (Date.now() < end) {
        if (!bannerVisible()) return true;
        await sleep(100);
      }
      return !bannerVisible();
    }

    async function success(outcome) {
      const end = Date.now() + reappearMs;
      while (Date.now() < end) {
        await sleep(250);
        if (bannerVisible()) {
          flags.add('banner_reappeared');
          break;
        }
      }
      return result(outcome);
    }

    const L = firstLayer(found);
    if (L.reject && L.accepts.length) {
      const biggest = Math.max(...L.accepts.map(area));
      if (area(L.reject) < 0.6 * biggest) flags.add('reject_less_prominent');
    }

    if (L.reject && (await click(L.reject)) && (await gone())) return success('rejected_first_layer');

    if (L.settings && (await click(L.settings))) {
      const panel = await waitFor(() => findPanel(found, doc), 4000, doc);
      if (panel) {
        await sleep(settleMs);
        const roots = found.rule ? ruleScopes(found.rule, doc) : allRoots(doc);
        const pt = byText(panel, ['reject', 'save']);
        const panelReject = pick(found.rule, 'panelRejectAll', roots, panel) || pt.reject || null;

        const ruleToggles = found.rule ? qsa(roots, found.rule.toggles).filter((t) => contains(panel, t) || !visible(panel)) : [];
        const candidates = [...new Set([...ruleToggles, ...deepWithin(panel, TOGGLE)])];
        const optional = [];
        for (const t of candidates) {
          if (isDisabled(t)) continue;
          const ctx = contextText(t);
          if (RX.necessary.test(ctx) && !RX.legitimateInterest.test(ctx)) continue;
          const shown = visible(t) || (t.labels && [...t.labels].some(visible)) || visible(parentOf(t));
          if (!shown) continue;
          optional.push({ t, li: RX.legitimateInterest.test(ctx) });
        }
        const onAtOpen = optional.filter((o) => isOn(o.t));
        if (onAtOpen.some((o) => !o.li)) flags.add('pre_ticked');
        if (onAtOpen.some((o) => o.li)) flags.add('legitimate_interest');

        if (panelReject && panelReject !== L.reject && (await click(panelReject)) && (await gone())) return success('rejected_in_settings');

        for (const o of optional) {
          if (!isOn(o.t) || clicks >= MAX_CLICKS) continue;
          clicks++;
          o.t.click();
          await sleep(60);
          if (isOn(o.t) && o.t.labels && o.t.labels[0]) {
            o.t.labels[0].click();
            await sleep(60);
          }
          if (!isOn(o.t)) toggles++;
        }
        const save = pick(found.rule, 'save', roots, panel) || pt.save || null;
        if (save && (await click(save)) && (await gone())) return success(toggles > 0 ? 'rejected_by_toggles' : 'rejected_in_settings');
      }
    }

    if (!L.reject && !L.settings) {
      const text = (found.container.innerText || '').slice(0, 5000);
      if (RX.consentOrPay.test(text)) return result('consent_or_pay');
      if (L.accepts.length) return result('accept_only');
    }
    return result('reject_failed');
  }

  global.CMEngine = { run, classify, detect: (d) => detect(d || document), trackerCookiePresent: (d) => trackerCookiePresent(d || document), version: DATA.rules.version };
})(typeof window !== 'undefined' ? window : globalThis);

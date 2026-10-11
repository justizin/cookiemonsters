/* Content-script entry: ask the background whether to run here, run the engine
 * once per document (again after same-document navigations where supported),
 * and hand the measurement to the background. No data leaves from here.
 * SPDX-License-Identifier: AGPL-3.0-or-later */
(function () {
  'use strict';
  const api = globalThis.browser || globalThis.chrome;
  const isTop = window === window.top;
  let running = false;
  let lastRun = 0;

  async function go() {
    if (running || Date.now() - lastRun < 10000) return;
    running = true;
    lastRun = Date.now();
    try {
      const cfg = await api.runtime.sendMessage({ type: 'cm:config' });
      if (!cfg || !cfg.enabled) return;
      const result = await CMEngine.run({ isTop });
      if (result) await api.runtime.sendMessage({ type: 'cm:result', result, top: isTop });
    } catch (e) {
      /* extension reloaded or page torn down */
    } finally {
      running = false;
    }
  }

  go();
  // Single-page apps: the Navigation API (Chromium) tells us about client-side navigations.
  if (isTop && window.navigation && typeof window.navigation.addEventListener === 'function') {
    window.navigation.addEventListener('navigatesuccess', () => setTimeout(go, 500));
  }
})();

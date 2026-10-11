// Runs the extension's scorer and site logic against the same vectors as the Python tests.
// node extension/tests/scoring_parity.mjs
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '../..');
const ctx = vm.createContext({ URL, TextEncoder, crypto: globalThis.crypto });
ctx.globalThis = ctx;
for (const f of ['src/common/generated_core.js', 'src/common/score.js', 'src/common/site.js']) {
  vm.runInContext(fs.readFileSync(path.join(root, 'extension', f), 'utf8'), ctx, { filename: f });
}
const vectors = JSON.parse(fs.readFileSync(path.join(root, 'shared/scoring_vectors.json'), 'utf8'));
const domains = JSON.parse(fs.readFileSync(path.join(root, 'shared/domain_vectors.json'), 'utf8'));
let failures = 0;
const check = (ok, msg) => {
  if (!ok) {
    failures++;
    console.error('FAIL', msg);
  }
};
for (const v of vectors.reports) {
  const f = ctx.CMScore.visitFriction(v.report);
  check(f === v.friction, `${v.name}: friction ${f} != ${v.friction}`);
  check(ctx.CMScore.gradeFor(f) === v.grade, `${v.name}: grade`);
}
for (const v of vectors.sites) {
  const m = ctx.CMScore.median(v.frictions);
  check(m === v.friction, `${v.name}: median ${m} != ${v.friction}`);
}
for (const [host, want] of domains.cases) {
  const got = ctx.CMSite.siteOf(host, false);
  check((got ? got.site : null) === want, `${host}: ${got && got.site} != ${want}`);
}
check(ctx.CMSite.siteOf('shop.fixture.test', true).site === 'fixture.test', 'reserved allowed');
const h = await ctx.CMSite.hashHex('example.com');
check(h === 'a379a6f6eeafb9a55e378c118034e2751e682fab9f2d30ab13d2125586ce1947', 'sha256');
console.log(failures ? `${failures} failure(s)` : `scoring + site parity ok (${vectors.reports.length + vectors.sites.length + domains.cases.length} vectors)`);
process.exit(failures ? 1 : 0);

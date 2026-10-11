#!/usr/bin/env python3
"""Build the extension for each browser from one source tree.

  python extension/build.py                 -> dist/{chrome,firefox,safari}/ + dist/*.zip
  python extension/build.py chrome          -> just one target
  python extension/build.py --safari-xcode  -> also wrap dist/safari with Apple's converter (macOS + Xcode)

Each target is src/ plus manifest.base.json deep-merged with manifests/<browser>.json.
Generated files are checked first; run tools/sync_generated.py if they are stale.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SRC = HERE / "src"
DIST = HERE / "dist"
TARGETS = ("chrome", "firefox", "safari")
SKIP = {"options.template.html"}


def merge(a: dict, b: dict) -> dict:
    out = dict(a)
    for k, v in b.items():
        out[k] = merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def manifest_for(target: str) -> dict:
    base = json.loads((HERE / "manifest.base.json").read_text())
    overlay = json.loads((HERE / "manifests" / f"{target}.json").read_text())
    m = merge(base, overlay)
    if target != "chrome":
        m.pop("minimum_chrome_version", None)
    return m


def build(target: str) -> Path:
    out = DIST / target
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(SRC, out, ignore=lambda d, names: [n for n in names if n in SKIP or n.startswith(".")])
    m = manifest_for(target)
    if target != "chrome":
        (out / "background" / "sw.js").unlink()
    (out / "manifest.json").write_text(json.dumps(m, indent=2) + "\n")
    # every file the manifest references must exist
    refs = list(m["content_scripts"][0]["js"]) + list(m["icons"].values()) + [m["action"]["default_popup"], m["options_ui"]["page"]]
    bg = m["background"]
    refs += [bg["service_worker"]] if "service_worker" in bg else bg["scripts"]
    missing = [r for r in refs if not (out / r).exists()]
    if missing:
        raise SystemExit(f"{target}: manifest references missing files: {missing}")
    z = DIST / f"cookiemonsters-{target}-{m['version']}.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(out.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(out))
    print(f"built {out.relative_to(ROOT)}  ->  {z.relative_to(ROOT)}")
    return out


def safari_xcode(dist_safari: Path) -> None:
    if sys.platform != "darwin" or not shutil.which("xcrun"):
        raise SystemExit("--safari-xcode needs macOS with Xcode (xcrun safari-web-extension-converter)")
    subprocess.run(
        ["xcrun", "safari-web-extension-converter", str(dist_safari), "--project-location", str(DIST / "safari-xcode"),
         "--app-name", "cookiemonsters", "--bundle-identifier", "local.cookiemonsters", "--no-open", "--force"],
        check=True,
    )


def main(argv: list[str]) -> int:
    check = subprocess.run([sys.executable, str(ROOT / "tools" / "sync_generated.py"), "--check"])
    if check.returncode:
        return check.returncode
    targets = [a for a in argv if a in TARGETS] or list(TARGETS)
    DIST.mkdir(exist_ok=True)
    for t in targets:
        out = build(t)
        if t == "safari" and "--safari-xcode" in argv:
            safari_xcode(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

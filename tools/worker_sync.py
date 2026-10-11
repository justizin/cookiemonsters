#!/usr/bin/env python3
"""Copy the cookiemonsters package into api/worker/src/ so wrangler bundles it."""

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
src = ROOT / "api" / "cookiemonsters"
dst = ROOT / "api" / "worker" / "src" / "cookiemonsters"
if dst.exists():
    shutil.rmtree(dst)
shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
print("copied", src, "->", dst)

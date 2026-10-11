PY ?= python3

.PHONY: test test-api test-ext sync check build serve worker-sync

test: check test-api test-ext

check:
	$(PY) tools/sync_generated.py --check

sync:
	$(PY) tools/sync_generated.py

test-api:
	$(PY) -m pytest api/tests -q

test-ext:
	node extension/tests/scoring_parity.mjs
	$(PY) -m pytest extension/tests -q

build:
	$(PY) extension/build.py

serve:
	cd api && $(PY) -m cookiemonsters serve

worker-sync:
	$(PY) tools/worker_sync.py

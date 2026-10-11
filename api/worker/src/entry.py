"""Cloudflare Python Worker entry point.

The Worker runs the same FastAPI app as the standalone server. Cloudflare's
``asgi`` bridge passes the Worker ``env`` through as ``scope["env"]``; the app
then builds its storage around the D1 binding ``env.DB`` for that request.

Before ``wrangler dev`` / ``wrangler deploy`` copy the package next to this
file:  ``make worker-sync`` (or ``python ../../tools/worker_sync.py``).
"""

import asgi  # provided by the Python Workers runtime
from workers import WorkerEntrypoint  # provided by the Python Workers runtime

from cookiemonsters.app import create_app
from cookiemonsters.service import Service, Settings
from cookiemonsters.storage import Store
from cookiemonsters.storage.d1 import D1Executor

app = create_app()


def _settings(env) -> Settings:
    def get(name):
        v = getattr(env, name, None)
        return None if v is None else str(v)

    return Settings.from_env(get)


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        return await asgi.fetch(app, request.js_object, self.env)

    async def scheduled(self, controller, env=None, ctx=None):
        # Daily cron (wrangler.toml): delete yesterday's rate-limit salt and
        # counters, drop aggregates older than the scoring window, refresh summaries.
        svc = Service(Store(D1Executor(self.env.DB)), _settings(self.env))
        await svc.maintain()

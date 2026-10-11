# cookiemonsters (grading service)

Python package for the cookiemonsters grading service: one FastAPI app that runs standalone (`cookiemonsters serve`, SQLite) or as a Cloudflare Python Worker (D1). See the repository's top-level README.md and docs/ for the full picture.

```sh
pip install ".[standalone]"
cookiemonsters serve        # http://127.0.0.1:8787
```

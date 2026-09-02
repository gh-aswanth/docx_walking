# webapp

A FastAPI server that runs every example in [`examples/`](../../examples/) and
renders the `.docx` each one produced — insertions, deletions, moves, formatting
revisions and comments — as HTML you can read, select and link to.

```bash
pip install "docx-redline[web]"
docx-redline serve                    # http://127.0.0.1:8000
```

It ships *inside* the package: templates, stylesheet and the 26 example scripts
are all package data, so an installed wheel serves the whole demo with no
checkout. From the repository it is the same command, or:

```bash
uv sync && uv run uvicorn docx_redline.web.main:app --reload
```

## Why it renders HTML rather than images

[`scripts/screenshots.py`](../../scripts/screenshots.py) goes `.docx` → PDF → PNG
through LibreOffice. That is right for the README, and impossible here: a
serverless function has no LibreOffice, no room for one, and a picture is not
selectable, searchable or linkable.

So [`app/render.py`](render.py) walks the OOXML directly. `w:ins` becomes
`<ins>`, `w:del` becomes `<del>`, `w:moveFrom`/`w:moveTo` get their own colour,
`w:rPrChange` gets a dotted underline, and a changed paragraph gets a change bar
in the margin — the same vocabulary Word's review pane uses. No external binary,
and it works anywhere Python does.

## Why the examples are executed, not canned

Each request runs the example in a subprocess with `DOCX_REDLINE_OUT` pointed at
a scratch directory. The page therefore shows what the library does *now*. An
example that breaks shows up here exactly as it does in CI, rather than the site
quietly serving a screenshot of how things used to work.

Runs are cached per process, so a warm instance pays nothing.

## Layout

```
docx_redline/web/
  main.py          the FastAPI app: index, example page, download, /healthz
  examples.py      discovery, grouping, running, and finding what was written
  render.py        OOXML -> HTML, tracked changes and all
  templates/       Jinja2 + Tailwind (CDN, no build step)   } package data
  static/app.css   paper, change bars, revision colours     }
  examples/        force-included from the repository root at build time
api/index.py       Vercel entry point -- imports `app` from here
vercel.json        memory, duration, routing, cache headers
.vercelignore      keeps tests, docs and CI out of the function
```

`examples.py` prefers the copy inside the package and falls back to the
repository root, so the same code serves an install and a checkout.

## Deploying

[`.github/workflows/deploy.yml`](../../.github/workflows/deploy.yml) deploys on
every push to `main`, and a preview on every PR — **after** the full CI gate
passes. Vercel's own Git integration would deploy either way; driving the CLI
from the workflow means a red build never reaches production. The workflow also
curls `/healthz`, `/` and one example afterwards, because a deployment that 500s
is not a deployment.

Vercel's Python builder installs with `uv sync`, which takes the project's
default dependency groups rather than an extra — so `pyproject.toml` declares a
`deploy` group holding `docx-redline[web]` and lists it in
`[tool.uv] default-groups`. Without that the function deploys with no FastAPI
in it and 500s on the first request.

Three repository secrets are needed: `VERCEL_TOKEN`, `VERCEL_ORG_ID`,
`VERCEL_PROJECT_ID`. Run `vercel link` once locally and the last two are in
`.vercel/project.json`. The workflow fails with a clear message if any is
missing, rather than half-deploying.

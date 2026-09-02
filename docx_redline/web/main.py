"""The demo server: run each example, and show the .docx it produced.

    pip install "docx-redline[web]"
    docx-redline serve                 # or: uvicorn docx_redline.web.main:app

Templates, stylesheet and the examples themselves are package data, so an
installed wheel serves the whole demo with no checkout. Deployed to Vercel from
``api/index.py``, which imports ``app`` from here.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from docx_redline import __version__

from . import examples, render

HERE = Path(__file__).resolve().parent

app = FastAPI(
    title="docx-redline",
    description="Every example, run live, with the tracked changes it produced.",
    version=__version__,
)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")
templates.env.globals["version"] = __version__


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(
        request, "index.html", {"groups": examples.grouped(), "total": len(examples.catalogue())}
    )


@app.get("/e/{slug}", response_class=HTMLResponse)
def example(request: Request, slug: str):
    ex = examples.find(slug)
    if ex is None:
        raise HTTPException(404, f"no example named {slug!r}")

    result = examples.run(ex)
    documents = []
    for name in result.documents:
        path = examples.document(ex, name)
        if path is None:
            continue
        blocks, comments, summary = render.read(path)
        documents.append(
            {
                "name": name,
                "html": render.to_html(blocks),
                "comments": comments,
                "counts": dict(sorted(summary.counts.items())),
                "authors": dict(summary.authors),
                "total": len(summary.revisions),
            }
        )

    ordered = examples.catalogue()
    i = ordered.index(ex)
    return templates.TemplateResponse(
        request,
        "example.html",
        {
            "ex": ex,
            "run": result,
            "documents": documents,
            "prev": ordered[i - 1] if i else None,
            "next": ordered[i + 1] if i + 1 < len(ordered) else None,
        },
    )


@app.get("/e/{slug}/download/{filename}")
def download(slug: str, filename: str):
    ex = examples.find(slug)
    if ex is None:
        raise HTTPException(404)
    path = examples.document(ex, filename)
    if path is None:
        raise HTTPException(404, "no such document")
    return FileResponse(
        path,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@app.get("/healthz")
def healthz():
    return {"ok": True, "version": __version__, "examples": len(examples.catalogue())}


def serve(host: str = "127.0.0.1", port: int = 8000, reload: bool = False) -> None:
    """Run the demo with uvicorn. Both come from the ``web`` extra."""
    try:
        import uvicorn
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on the install
        raise SystemExit(
            "the demo server needs the web extra:  pip install 'docx-redline[web]'"
        ) from exc
    uvicorn.run("docx_redline.web.main:app" if reload else app, host=host, port=port, reload=reload)

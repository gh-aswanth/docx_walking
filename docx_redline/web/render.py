"""Render a redlined ``.docx`` to HTML, tracked changes and all.

The screenshot pipeline in ``scripts/screenshots.py`` goes through LibreOffice,
which cannot run on a serverless host and produces a picture besides. This walks
the OOXML directly instead: no external binary, and the result is selectable,
searchable, linkable text rather than a PNG.

Word's own review view is the target -- an insertion underlined, a deletion
struck, a move in its own colour, a change bar in the margin, comments alongside.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from pathlib import Path

from docx_redline import Redliner
from docx_redline.oxml.ns import qn

#: Wrappers that mark everything inside them as one kind of revision.
REVISION = {
    qn("w:ins"): "ins",
    qn("w:del"): "del",
    qn("w:moveFrom"): "move-from",
    qn("w:moveTo"): "move-to",
}
#: Wrappers that are transparent: recurse, but do not change the kind.
TRANSPARENT = {
    qn("w:hyperlink"),
    qn("w:smartTag"),
    qn("w:sdt"),
    qn("w:sdtContent"),
    qn("w:bdo"),
    qn("w:dir"),
    qn("w:customXml"),
}
ATOMIC = {qn("w:tab"): "\t", qn("w:br"): "\n", qn("w:cr"): "\n", qn("w:noBreakHyphen"): "-"}


@dataclass
class Piece:
    """One run of text and how it is marked."""

    kind: str  # "" | ins | del | move-from | move-to
    text: str
    bold: bool = False
    italic: bool = False
    formatted: bool = False  # carries a w:rPrChange


@dataclass
class Para:
    pieces: list[Piece] = field(default_factory=list)
    style: str | None = None
    mark: str = ""  # "" | ins | del  -- the paragraph mark itself
    ppr_change: bool = False
    comments: list[str] = field(default_factory=list)  # comment ids anchored here

    @property
    def changed(self) -> bool:
        return self.mark != "" or self.ppr_change or any(p.kind or p.formatted for p in self.pieces)

    @property
    def empty(self) -> bool:
        return not any(p.text.strip() for p in self.pieces)


@dataclass
class Row:
    cells: list[list[Para]]
    mark: str = ""  # "" | ins | del -- a tracked row


@dataclass
class Table:
    rows: list[Row] = field(default_factory=list)


@dataclass
class Comment:
    id: str
    author: str
    initials: str
    date: str
    text: str


def _pieces(el, kind: str = "") -> list[Piece]:
    out: list[Piece] = []
    for child in el:
        if child.tag in REVISION:
            out += _pieces(child, REVISION[child.tag])
        elif child.tag in TRANSPARENT:
            out += _pieces(child, kind)
        elif child.tag == qn("w:r"):
            rpr = child.find(qn("w:rPr"))
            bold = rpr is not None and rpr.find(qn("w:b")) is not None
            italic = rpr is not None and rpr.find(qn("w:i")) is not None
            changed = rpr is not None and rpr.find(qn("w:rPrChange")) is not None
            for node in child:
                if node.tag in (qn("w:t"), qn("w:delText"), qn("w:instrText")):
                    if node.text:
                        out.append(Piece(kind, node.text, bold, italic, changed))
                elif node.tag in ATOMIC:
                    out.append(Piece(kind, ATOMIC[node.tag], bold, italic, changed))
    return out


def _para(p) -> Para:
    style_el = p.find(f"{qn('w:pPr')}/{qn('w:pStyle')}")
    ppr = p.find(qn("w:pPr"))
    mark = ""
    if ppr is not None:
        rpr = ppr.find(qn("w:rPr"))
        if rpr is not None:
            if rpr.find(qn("w:ins")) is not None:
                mark = "ins"
            elif rpr.find(qn("w:del")) is not None:
                mark = "del"
    return Para(
        pieces=_pieces(p),
        style=style_el.get(qn("w:val")) if style_el is not None else None,
        mark=mark,
        ppr_change=ppr is not None and ppr.find(qn("w:pPrChange")) is not None,
        comments=[c.get(qn("w:id")) for c in p.iter(qn("w:commentRangeStart"))],
    )


def _row(tr) -> Row:
    trpr = tr.find(qn("w:trPr"))
    mark = ""
    if trpr is not None:
        if trpr.find(qn("w:ins")) is not None:
            mark = "ins"
        elif trpr.find(qn("w:del")) is not None:
            mark = "del"
    return Row(
        cells=[[_para(p) for p in tc.iter(qn("w:p"))] for tc in tr.findall(qn("w:tc"))],
        mark=mark,
    )


def read(path: str | Path):
    """(blocks, comments, summary) for a document. Blocks are Para or Table."""
    rl = Redliner(path, track_changes=False)
    body = rl.document.element.body

    blocks: list = []
    for child in body:
        if child.tag == qn("w:p"):
            blocks.append(_para(child))
        elif child.tag == qn("w:tbl"):
            blocks.append(Table(rows=[_row(tr) for tr in child.findall(qn("w:tr"))]))

    comments = []
    for c in getattr(rl.document, "comments", []) or []:
        comments.append(
            Comment(
                id=str(getattr(c, "comment_id", "")),
                author=c.author or "",
                initials=c.initials or "",
                date=str(getattr(c, "timestamp", "") or ""),
                text=c.text or "",
            )
        )

    return blocks, comments, rl.summary()


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------
def _run_html(piece: Piece) -> str:
    text = html.escape(piece.text).replace("\t", "&emsp;").replace("\n", "<br/>")
    classes = []
    if piece.kind:
        classes.append(f"rev-{piece.kind}")
    if piece.formatted:
        classes.append("rev-format")
    if piece.bold:
        classes.append("font-semibold")
    if piece.italic:
        classes.append("italic")
    if not classes:
        return text
    tag = {"ins": "ins", "del": "del"}.get(piece.kind, "span")
    title = {
        "ins": "Inserted",
        "del": "Deleted",
        "move-from": "Moved from here",
        "move-to": "Moved to here",
    }.get(piece.kind, "Formatting changed" if piece.formatted else "")
    attr = f' title="{title}"' if title else ""
    return f'<{tag} class="{" ".join(classes)}"{attr}>{text}</{tag}>'


def para_html(para: Para) -> str:
    inner = "".join(_run_html(p) for p in para.pieces) or "&nbsp;"
    classes = ["para"]
    if para.style and para.style.lower().startswith("heading"):
        classes.append(f"h-{para.style[-1] if para.style[-1].isdigit() else '2'}")
    if para.changed:
        classes.append("changed")
    if para.mark:
        classes.append(f"mark-{para.mark}")
    marks = "".join(f'<sup class="cref" data-comment="{cid}">{cid}</sup>' for cid in para.comments)
    # data-change lets the page jump between revisions instead of making the
    # reader scroll a whole contract looking for the one that moved.
    flag = ' data-change="1"' if para.changed else ""
    return f'<p class="{" ".join(classes)}"{flag}>{inner}{marks}</p>'


def table_html(table: Table) -> str:
    rows = []
    for row in table.rows:
        cells = "".join(f"<td>{''.join(para_html(p) for p in cell)}</td>" for cell in row.cells)
        cls = f' class="row-{row.mark}"' if row.mark else ""
        rows.append(f"<tr{cls}>{cells}</tr>")
    return f'<table class="doc-table">{"".join(rows)}</table>'


def to_html(blocks) -> str:
    out = []
    for block in blocks:
        if isinstance(block, Table):
            out.append(table_html(block))
        elif not block.empty or block.changed:
            out.append(para_html(block))
    return "\n".join(out)

"""Structured PDF report generation (reportlab / platypus).

Layout mirrors the web UI: a flight dashboard first (the same `summary.flight_summary`
numbers and mode timeline the browser shows), then the prioritised actions, the findings
grouped by category, and finally the diagnostic plots.
"""
import io
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as _canvas
from reportlab.platypus import (Flowable, HRFlowable, Image, KeepTogether,
                                PageBreak, Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle)

from .core import Severity
from .plots import mode_color
from .report import _grouped

SEV_COLOR = {
    Severity.CRITICAL: colors.HexColor("#c0392b"),
    Severity.WARNING: colors.HexColor("#b9770e"),
    Severity.INFO: colors.HexColor("#2471a3"),
    Severity.OK: colors.HexColor("#1e8449"),
}
ACCENT = colors.HexColor("#1a5276")
RULE = colors.HexColor("#b7c4cf")
MUTED = colors.HexColor("#5d6d7e")
PANEL = colors.HexColor("#f4f7f9")

PAGE_W, PAGE_H = A4
MARGIN = 18 * mm
CONTENT_W = PAGE_W - 2 * MARGIN


def _styles():
    ss = getSampleStyleSheet()
    ss.add(ParagraphStyle("Title2", parent=ss["Title"], fontSize=20, spaceAfter=2,
                          textColor=ACCENT, alignment=0))
    ss.add(ParagraphStyle("Meta", parent=ss["Normal"], fontSize=8.5, textColor=MUTED,
                          leading=12))
    ss.add(ParagraphStyle("Sec", parent=ss["Heading1"], fontSize=13.5, textColor=ACCENT,
                          spaceBefore=16, spaceAfter=2, keepWithNext=True))
    ss.add(ParagraphStyle("Sub", parent=ss["Heading2"], fontSize=11, textColor=ACCENT,
                          spaceBefore=10, spaceAfter=3, keepWithNext=True))
    ss.add(ParagraphStyle("FTitle", parent=ss["Normal"], fontSize=10.5,
                          fontName="Helvetica-Bold", spaceAfter=1))
    ss.add(ParagraphStyle("Detail", parent=ss["Normal"], fontSize=9, leading=12,
                          textColor=colors.HexColor("#333333")))
    ss.add(ParagraphStyle("Fix", parent=ss["Normal"], fontName="Helvetica", fontSize=8.5,
                          leading=11.5, leftIndent=9, textColor=colors.HexColor("#6c3483")))
    ss.add(ParagraphStyle("Doc", parent=ss["Normal"], fontSize=7.5, textColor=MUTED,
                          spaceBefore=2))
    ss.add(ParagraphStyle("StatL", parent=ss["Normal"], fontSize=7, leading=9,
                          textColor=MUTED))
    ss.add(ParagraphStyle("StatV", parent=ss["Normal"], fontSize=11, leading=14,
                          fontName="Helvetica-Bold", textColor=colors.HexColor("#1c2733")))
    ss.add(ParagraphStyle("StatH", parent=ss["Normal"], fontSize=6.5, leading=8.5,
                          textColor=MUTED))
    ss.add(ParagraphStyle("Legend", parent=ss["Normal"], fontSize=8, leading=10))
    return ss


def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _hex(c):
    return "#" + c.hexval()[2:]


def _chip(sev):
    return f'<font color="{_hex(SEV_COLOR[sev])}"><b>[{sev.label}]</b></font>'


class _Bookmark(Flowable):
    """Zero-height flowable that registers a PDF outline entry at its position."""

    width = height = 0

    def __init__(self, title, key, level=0):
        Flowable.__init__(self)
        self.title, self.key, self.level = title, key, level

    def draw(self):
        self.canv.bookmarkPage(self.key)
        self.canv.addOutlineEntry(self.title, self.key, level=self.level, closed=False)


class _NumberedCanvas(_canvas.Canvas):
    """Two-pass canvas so the footer can print 'page N of M'."""

    def __init__(self, *a, **kw):
        _canvas.Canvas.__init__(self, *a, **kw)
        self._saved = []

    def showPage(self):
        self._saved.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved)
        for state in self._saved:
            self.__dict__.update(state)
            self._footer(total)
            _canvas.Canvas.showPage(self)
        _canvas.Canvas.save(self)

    def _footer(self, total):
        self.saveState()
        self.setStrokeColor(RULE)
        self.setLineWidth(0.4)
        self.line(MARGIN, 12 * mm, PAGE_W - MARGIN, 12 * mm)
        self.setFont("Helvetica", 7)
        self.setFillColor(MUTED)
        self.drawString(MARGIN, 8 * mm, self._footer_left)
        self.drawRightString(PAGE_W - MARGIN, 8 * mm, f"page {self._pageNumber} of {total}")
        self.restoreState()

    _footer_left = "px4-flight-doctor"


def _section(ss, num, title, story, level=0):
    """Numbered section heading with a rule underneath it."""
    key = f"sec{num}-{title}"
    story.append(_Bookmark(f"{num}. {title}", key, level))
    story.append(Paragraph(f"{num}. {_esc(title)}", ss["Sec"]))
    story.append(HRFlowable(width="100%", thickness=1, color=ACCENT,
                            spaceBefore=1, spaceAfter=7))


def _subsection(ss, title, story):
    story.append(Paragraph(_esc(title), ss["Sub"]))
    story.append(HRFlowable(width="100%", thickness=0.5, color=RULE,
                            spaceBefore=0, spaceAfter=5))


def _counts_band(counts):
    row = [[f"{counts[Severity.CRITICAL]}  CRITICAL", f"{counts[Severity.WARNING]}  WARNING",
            f"{counts[Severity.INFO]}  INFO", f"{counts[Severity.OK]}  OK"]]
    t = Table(row, colWidths=[CONTENT_W / 4] * 4)
    style = [("ALIGN", (0, 0), (-1, -1), "CENTER"),
             ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
             ("FONTSIZE", (0, 0), (-1, -1), 9.5),
             ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
             ("TOPPADDING", (0, 0), (-1, -1), 6),
             ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
             ("INNERGRID", (0, 0), (-1, -1), 1.5, colors.white)]
    for i, sev in enumerate((Severity.CRITICAL, Severity.WARNING, Severity.INFO, Severity.OK)):
        style.append(("BACKGROUND", (i, 0), (i, 0), SEV_COLOR[sev]))
    t.setStyle(TableStyle(style))
    return t


def _stat_grid(ss, items, cols=3):
    """The dashboard tiles: label / value+unit / hint, laid out in a grid."""
    cells = []
    for it in items:
        unit = f' <font size="7" color="{_hex(MUTED)}">{_esc(it.get("unit", ""))}</font>' \
            if it.get("unit") else ""
        block = [Paragraph(_esc(it["label"]).upper(), ss["StatL"]),
                 Paragraph(f'{_esc(it["value"])}{unit}', ss["StatV"])]
        if it.get("hint"):
            block.append(Paragraph(_esc(it["hint"]), ss["StatH"]))
        cells.append(block)
    while len(cells) % cols:
        cells.append([])
    rows = [cells[i:i + cols] for i in range(0, len(cells), cols)]
    t = Table(rows, colWidths=[CONTENT_W / cols] * cols)
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, -1), PANEL),
        ("INNERGRID", (0, 0), (-1, -1), 2, colors.white),
        ("BOX", (0, 0), (-1, -1), 2, colors.white),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


def _mode_timeline(ss, modes):
    """Stacked proportional bar + legend, same colors the plots use."""
    shown = [m for m in modes if m["pct"] >= 0.5] or modes[:1]
    widths, style = [], [("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
                         ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
                         ("FONTSIZE", (0, 0), (-1, -1), 7),
                         ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                         ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                         ("TOPPADDING", (0, 0), (-1, -1), 4),
                         ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]
    total_pct = sum(m["pct"] for m in shown) or 1.0
    labels = []
    for i, m in enumerate(shown):
        w = CONTENT_W * m["pct"] / total_pct
        widths.append(w)
        labels.append(f'{m["pct"]:.0f}%' if w > 22 else "")
        style.append(("BACKGROUND", (i, 0), (i, 0), colors.HexColor(mode_color(m["name"]))))
    bar = Table([labels], colWidths=widths, rowHeights=[7 * mm])
    bar.setStyle(TableStyle(style))

    legend, lstyle = [], [("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                          ("LEFTPADDING", (0, 0), (-1, -1), 3),
                          ("TOPPADDING", (0, 0), (-1, -1), 2),
                          ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]
    per_row = 3
    for r0 in range(0, len(modes), per_row):
        row = []
        for c, m in enumerate(modes[r0:r0 + per_row]):
            col = c * 2
            row += ["", Paragraph(f'{_esc(m["name"])} &nbsp;<font color="{_hex(MUTED)}">'
                                  f'{m["seconds"]:.0f} s · {m["pct"]:.0f}%</font>', ss["Legend"])]
            lstyle.append(("BACKGROUND", (col, len(legend)), (col, len(legend)),
                           colors.HexColor(mode_color(m["name"]))))
        while len(row) < per_row * 2:
            row += ["", ""]
        legend.append(row)
    lt = Table(legend, colWidths=[4 * mm, CONTENT_W / per_row - 4 * mm] * per_row)
    lt.setStyle(TableStyle(lstyle))
    return [bar, Spacer(1, 4), lt]


def _finding_block(ss, f, prefix=""):
    """A finding rendered as a colored left rule plus its text."""
    body = [Paragraph(f"{_chip(f.severity)} {prefix}{_esc(f.title)}", ss["FTitle"])]
    if f.detail:
        for line in f.detail.splitlines():
            if line.strip():
                body.append(Paragraph(_esc(line), ss["Detail"]))
    for fix in f.fixes:
        body.append(Paragraph(f'<font color="{_hex(SEV_COLOR[Severity.WARNING])}">'
                              f"&rarr;</font> {_esc(fix)}", ss["Fix"]))
    if f.doc:
        body.append(Paragraph(f"Background: docs/{_esc(f.doc)}", ss["Doc"]))
    t = Table([["", body]], colWidths=[1.6 * mm, CONTENT_W - 1.6 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), SEV_COLOR[f.severity]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
        ("RIGHTPADDING", (0, 0), (0, 0), 0),
        ("LEFTPADDING", (1, 0), (1, 0), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return KeepTogether([t])


def build_pdf(findings, errors, meta, plots=None, summary=None):
    """Return PDF bytes. meta: dict with log, mass_kg, duration; summary: flight_summary()."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=MARGIN, rightMargin=MARGIN,
                            topMargin=16 * mm, bottomMargin=18 * mm,
                            title="PX4 Flight Analysis Report",
                            author="px4-flight-doctor")
    ss = _styles()
    summary = summary or {}
    head = summary.get("header") or {}

    story = [Paragraph("PX4 Flight Analysis Report", ss["Title2"])]
    meta_bits = [f"<b>Log:</b> {_esc(meta.get('log', '?'))}",
                 f"<b>Generated:</b> {datetime.now():%Y-%m-%d %H:%M}"]
    if meta.get("mass_kg"):
        meta_bits.append(f"<b>Takeoff mass:</b> {meta['mass_kg']:.2f} kg")
    if meta.get("duration"):
        meta_bits.append(f"<b>Airborne:</b> {meta['duration']:.0f} s")
    ident = [f"<b>Airframe:</b> {_esc(head['airframe'])}" if head.get("airframe") else "",
             f"<b>SYS_AUTOSTART:</b> {_esc(head['airframe_id'])}" if head.get("airframe_id") else "",
             f"<b>Firmware:</b> {_esc(head['firmware'])}" if head.get("firmware") else "",
             f"<b>Hardware:</b> {_esc(head['hardware'])}" if head.get("hardware") else ""]
    story.append(Paragraph(" &nbsp;|&nbsp; ".join(meta_bits), ss["Meta"]))
    ident = [x for x in ident if x]
    if ident:
        story.append(Paragraph(" &nbsp;|&nbsp; ".join(ident), ss["Meta"]))
    story.append(HRFlowable(width="100%", thickness=1.4, color=ACCENT,
                            spaceBefore=6, spaceAfter=9))

    counts = {s: sum(1 for f in findings if f.severity == s) for s in Severity}
    story += [_counts_band(counts), Spacer(1, 4)]

    n = 0
    if summary.get("items") or summary.get("modes"):
        n += 1
        _section(ss, n, "Flight summary", story)
        if summary.get("items"):
            story.append(_stat_grid(ss, summary["items"]))
        if summary.get("modes"):
            story.append(Spacer(1, 10))
            _subsection(ss, "Flight mode timeline", story)
            story += _mode_timeline(ss, summary["modes"])
        if summary.get("error"):
            story.append(Paragraph(f"(dashboard incomplete: {_esc(summary['error'])})",
                                   ss["Doc"]))

    actions = [f for f in findings if f.fixes and f.severity >= Severity.WARNING]
    if actions:
        n += 1
        _section(ss, n, "Recommended actions", story)
        story.append(Paragraph("Highest severity first — each item repeats in its category "
                               "section below with the supporting numbers.", ss["Meta"]))
        story.append(Spacer(1, 5))
        for i, f in enumerate(sorted(actions, key=lambda x: -int(x.severity)), 1):
            story.append(_finding_block(ss, f, prefix=f"{i}. "))

    groups = _grouped(findings)
    if groups:
        n += 1
        _section(ss, n, "Findings by category", story)
        for cat, items in groups.items():
            _subsection(ss, f"{cat}  ({len(items)})", story)
            for f in items:
                story.append(_finding_block(ss, f))

    if plots:
        n += 1
        story.append(PageBreak())
        _section(ss, n, "Diagnostic plots", story)
        for pl in plots:
            img = Image(io.BytesIO(pl["png"]))
            scale = min(1.0, CONTENT_W / img.imageWidth)
            img.drawWidth = img.imageWidth * scale
            img.drawHeight = img.imageHeight * scale
            story.append(KeepTogether([
                Paragraph(_esc(pl["title"]), ss["FTitle"]),
                HRFlowable(width="100%", thickness=0.5, color=RULE,
                           spaceBefore=1, spaceAfter=4),
                img,
                Spacer(1, 2),
                Paragraph(_esc(pl["caption"]), ss["Detail"]),
                Spacer(1, 12),
            ]))

    if errors:
        n += 1
        _section(ss, n, "Analyzer internal errors", story)
        story.append(Paragraph("These checks failed to run; every other result is unaffected.",
                               ss["Meta"]))
        story.append(Spacer(1, 4))
        for e in errors:
            story.append(Paragraph("• " + _esc(e), ss["Detail"]))

    _NumberedCanvas._footer_left = f"px4-flight-doctor  ·  {meta.get('log', '')}"
    doc.build(story, canvasmaker=_NumberedCanvas)
    return buf.getvalue()

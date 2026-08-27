"""Structured PDF report generation (reportlab / platypus)."""
import io
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (HRFlowable, Image, KeepTogether, PageBreak,
                                Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

from .core import Severity
from .report import _grouped

SEV_COLOR = {
    Severity.CRITICAL: colors.HexColor("#c0392b"),
    Severity.WARNING: colors.HexColor("#b9770e"),
    Severity.INFO: colors.HexColor("#2471a3"),
    Severity.OK: colors.HexColor("#1e8449"),
}
ACCENT = colors.HexColor("#1a5276")


def _styles():
    ss = getSampleStyleSheet()
    ss.add(ParagraphStyle("Title2", parent=ss["Title"], fontSize=20, spaceAfter=2))
    ss.add(ParagraphStyle("Meta", parent=ss["Normal"], fontSize=9, textColor=colors.grey))
    ss.add(ParagraphStyle("Cat", parent=ss["Heading1"], fontSize=14, textColor=ACCENT,
                          spaceBefore=14, spaceAfter=4))
    ss.add(ParagraphStyle("FTitle", parent=ss["Normal"], fontSize=10.5,
                          fontName="Helvetica-Bold", spaceBefore=6))
    ss.add(ParagraphStyle("Detail", parent=ss["Normal"], fontSize=9,
                          textColor=colors.HexColor("#333333"), leftIndent=10))
    ss.add(ParagraphStyle("Fix", parent=ss["Code"], fontSize=8.5, leftIndent=16,
                          textColor=colors.HexColor("#6c3483")))
    return ss


def _esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _chip(sev):
    hexcol = "#" + SEV_COLOR[sev].hexval()[2:]
    return f'<font color="{hexcol}"><b>[{sev.label}]</b></font>' 


def build_pdf(findings, errors, meta, plots=None):
    """Return PDF bytes. meta: dict with log, mass_kg, generated..."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm,
                            title="PX4 Flight Analysis Report")
    ss = _styles()
    story = [Paragraph("PX4 Flight Analysis Report", ss["Title2"])]
    meta_bits = [f"Log: {_esc(meta.get('log', '?'))}",
                 f"Generated: {datetime.now():%Y-%m-%d %H:%M}"]
    if meta.get("mass_kg"):
        meta_bits.append(f"Takeoff mass: {meta['mass_kg']:.2f} kg")
    if meta.get("duration"):
        meta_bits.append(f"Airborne: {meta['duration']:.0f} s")
    story.append(Paragraph(" &nbsp;|&nbsp; ".join(meta_bits), ss["Meta"]))
    story.append(Spacer(1, 6))

    counts = {s: sum(1 for f in findings if f.severity == s) for s in Severity}
    row = [[f"{counts[Severity.CRITICAL]} Critical", f"{counts[Severity.WARNING]} Warning",
            f"{counts[Severity.INFO]} Info", f"{counts[Severity.OK]} OK"]]
    t = Table(row, colWidths=[42 * mm] * 4)
    t.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 0), (0, 0), colors.white),
        ("BACKGROUND", (0, 0), (0, 0), SEV_COLOR[Severity.CRITICAL]),
        ("TEXTCOLOR", (1, 0), (1, 0), colors.white),
        ("BACKGROUND", (1, 0), (1, 0), SEV_COLOR[Severity.WARNING]),
        ("TEXTCOLOR", (2, 0), (2, 0), colors.white),
        ("BACKGROUND", (2, 0), (2, 0), SEV_COLOR[Severity.INFO]),
        ("TEXTCOLOR", (3, 0), (3, 0), colors.white),
        ("BACKGROUND", (3, 0), (3, 0), SEV_COLOR[Severity.OK]),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story += [t, Spacer(1, 10)]

    actions = [f for f in findings if f.fixes and f.severity >= Severity.WARNING]
    if actions:
        story.append(Paragraph("Recommended actions (highest priority first)", ss["Cat"]))
        for i, f in enumerate(sorted(actions, key=lambda x: -int(x.severity)), 1):
            story.append(Paragraph(f"{i}. {_chip(f.severity)} {_esc(f.title)}", ss["FTitle"]))
            for fix in f.fixes:
                story.append(Paragraph(_esc(fix), ss["Fix"]))
        story.append(Spacer(1, 6))
        story.append(HRFlowable(width="100%", color=colors.lightgrey))

    for cat, items in _grouped(findings).items():
        story.append(Paragraph(cat, ss["Cat"]))
        for f in items:
            story.append(Paragraph(f"{_chip(f.severity)} {_esc(f.title)}", ss["FTitle"]))
            if f.detail:
                for line in f.detail.splitlines():
                    story.append(Paragraph(_esc(line), ss["Detail"]))
            for fix in f.fixes:
                story.append(Paragraph("fix: " + _esc(fix), ss["Fix"]))

    if plots:
        story.append(PageBreak())
        story.append(Paragraph("Diagnostic plots", ss["Cat"]))
        maxw = A4[0] - 36 * mm
        for pl in plots:
            img = Image(io.BytesIO(pl["png"]))
            scale = min(1.0, maxw / img.imageWidth)
            img.drawWidth = img.imageWidth * scale
            img.drawHeight = img.imageHeight * scale
            story.append(KeepTogether([
                Paragraph(pl["title"], ss["FTitle"]),
                img,
                Paragraph(pl["caption"], ss["Detail"]),
                Spacer(1, 8),
            ]))

    if errors:
        story.append(Paragraph("Analyzer internal errors", ss["Cat"]))
        for e in errors:
            story.append(Paragraph(_esc(e), ss["Detail"]))

    def _footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.grey)
        canvas.drawString(18 * mm, 8 * mm, "px4-flight-doctor")
        canvas.drawRightString(A4[0] - 18 * mm, 8 * mm, f"page {doc_.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()

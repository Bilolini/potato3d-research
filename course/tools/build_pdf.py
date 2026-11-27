"""Render the editable report to a compact paginated PDF; no experiment execution."""
from html import escape
from pathlib import Path
import re

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle, Image, KeepTogether


ROOT = Path(__file__).resolve().parents[2]
COURSE = ROOT/"course"
OUTPUT = ROOT/"output/pdf/CSE527_CPU_Shape_Completion_Report.pdf"
NAVY = colors.HexColor("#17313b")
TEAL = colors.HexColor("#147879")
WIDTH = A4[0]-100


def rich(text):
    text = escape(text)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r'<link href="\2" color="#147879">\1</link>', text)
    # Local evidence links resolve in the editable report inside reproduction.zip.
    text = re.sub(r"\[([^\]]+)\]\(\.\.?/[^)]+\)", r'<i>\1</i>', text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"`(.+?)`", r'<font name="Courier" size="8.5">\1</font>', text)
    return text


def build():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    body = ParagraphStyle("body", fontName="Helvetica", fontSize=9.6, leading=12.9, textColor=NAVY, spaceAfter=7)
    styles = {
        1: ParagraphStyle("title", parent=body, fontName="Helvetica-Bold", fontSize=23, leading=27, spaceAfter=11),
        2: ParagraphStyle("section", parent=body, fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=TEAL, spaceBefore=5, spaceAfter=9),
        3: ParagraphStyle("subsection", parent=body, fontName="Helvetica-Bold", fontSize=10.4, leading=13.5, spaceBefore=4, spaceAfter=5)}
    cell = ParagraphStyle("cell", parent=body, fontSize=8.1, leading=10.4, spaceAfter=0)
    caption = ParagraphStyle("caption", parent=body, fontSize=8.2, leading=10.6, textColor=colors.HexColor("#4c626c"), spaceAfter=9)
    doc = SimpleDocTemplate(str(OUTPUT), pagesize=A4, rightMargin=50, leftMargin=50,
                            topMargin=45, bottomMargin=45, title="CPU Shape Completion from Partial Produce Scans",
                            author="CSE527 project", subject="Frozen CPU completion experiments, geometric failure modes and pin-color sensitivity")
    lines = (COURSE/"REPORT.md").read_text().splitlines()
    story = []; paragraph = []; index = 0; widths = None; max_height = 220
    def flush():
        if paragraph:
            story.append(Paragraph(rich(" ".join(paragraph)), body)); paragraph.clear()
    while index < len(lines):
        line = lines[index].strip(); index += 1
        if not line:
            flush(); continue
        if line == "<!-- page -->":
            flush(); story.append(PageBreak()); continue
        if line.startswith("<!-- widths:"):
            widths = [float(x) for x in line.split(":", 1)[1].split("-->")[0].split(",")]; continue
        if line.startswith("<!-- figure-height:"):
            max_height = float(line.split(":", 1)[1].split("-->")[0]); continue
        if line.startswith("#"):
            flush(); level = len(line)-len(line.lstrip("#"))
            story.append(Paragraph(rich(line[level:].strip()), styles[min(level, 3)])); continue
        match = re.fullmatch(r"!\[(.*)\]\(([^)]+)\)", line)
        if match:
            flush(); text, relative = match.groups(); image = Image(str(COURSE/relative))
            ratio = min(WIDTH/image.imageWidth, max_height/image.imageHeight)
            image.drawWidth = image.imageWidth*ratio; image.drawHeight = image.imageHeight*ratio
            image.hAlign = "CENTER"
            story.append(KeepTogether([Spacer(1, 4), image, Spacer(1, 5), Paragraph(rich(text), caption)])); continue
        if line.startswith("|"):
            flush(); rows = []
            while True:
                values = [x.strip() for x in line.strip("|").split("|")]
                if not all(re.fullmatch(r"[:\- ]+", x) for x in values):
                    rows.append(values)
                if index >= len(lines) or not lines[index].strip().startswith("|"):
                    break
                line = lines[index].strip(); index += 1
            if widths is None:
                widths = [1/len(rows[0])]*len(rows[0])
            if len(widths) != len(rows[0]):
                raise ValueError("Table width declaration differs from columns")
            content = [[Paragraph(rich(value), cell) for value in row] for row in rows]
            table = Table(content, colWidths=[x*WIDTH for x in widths], repeatRows=1, hAlign="LEFT")
            table.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.HexColor("#e2eeee")),
                ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#f3f6f7")]),
                ("VALIGN", (0,0), (-1,-1), "TOP"), ("LEFTPADDING", (0,0), (-1,-1), 6),
                ("RIGHTPADDING", (0,0), (-1,-1), 6), ("TOPPADDING", (0,0), (-1,-1), 5),
                ("BOTTOMPADDING", (0,0), (-1,-1), 5), ("LINEBELOW", (0,0), (-1,0), .6, TEAL)]))
            story.extend([table, Spacer(1, 9)]); widths = None; continue
        paragraph.append(line)
    flush()
    def furniture(canvas, document):
        canvas.saveState(); canvas.setStrokeColor(colors.HexColor("#d5e2e5")); canvas.setLineWidth(.5)
        canvas.line(50, A4[1]-29, A4[0]-50, A4[1]-29)
        canvas.setFont("Helvetica", 8); canvas.setFillColor(colors.HexColor("#607781"))
        canvas.drawString(50, A4[1]-22, "CPU SHAPE COMPLETION  |  CSE527")
        canvas.drawRightString(A4[0]-50, 25, str(document.page))
        canvas.drawString(50, 25, "Frozen experiments | 26 November 2026")
        canvas.restoreState()
    doc.build(story, onFirstPage=furniture, onLaterPages=furniture)
    print(OUTPUT)


if __name__ == "__main__":
    build()

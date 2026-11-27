"""Render the proposal results brief from archived findings and figures."""

from pathlib import Path
import argparse
from html import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output/pdf/potato_proposal_results.pdf"
STUDIES = ROOT / "studies"
GITHUB = "https://github.com/Bilolini/potato3d-research/blob/main/studies/"
MARGIN = 46
WIDTH = letter[0] - 2*MARGIN

INK = colors.HexColor("#192D33")
TEAL = colors.HexColor("#1A6459")
MUTED = colors.HexColor("#4B6268")
WASH = colors.HexColor("#EAF3ED")
LINE = colors.HexColor("#D6E2DF")

BODY = ParagraphStyle("body", fontName="Helvetica", fontSize=10.7, leading=15, textColor=INK, spaceAfter=10)
TITLE = ParagraphStyle("title", parent=BODY, fontName="Helvetica-Bold", fontSize=32, leading=36, spaceAfter=15)
LEDE = ParagraphStyle("lede", parent=BODY, fontSize=12, leading=17, textColor=MUTED, spaceAfter=13)
SUB = ParagraphStyle("sub", parent=BODY, fontName="Helvetica-Bold", fontSize=14, leading=17,
                     spaceBefore=12, spaceAfter=6, keepWithNext=True)
EYEBROW = ParagraphStyle("eyebrow", parent=BODY, fontName="Helvetica-Bold", textColor=TEAL,
                         fontSize=9, leading=12, spaceAfter=9)
SMALL = ParagraphStyle("small", parent=BODY, textColor=MUTED, fontSize=8.6, leading=12, spaceAfter=8)
CELL = ParagraphStyle("cell", parent=BODY, fontSize=9.3, leading=12.8, spaceAfter=0)
KPI = ParagraphStyle("kpi", parent=BODY, fontName="Helvetica-Bold", fontSize=19, leading=23, textColor=TEAL)


def table(headers, rows, widths, highlight=None):
    cells = [[Paragraph(f"<b>{escape(s)}</b>", CELL) for s in headers]]
    cells.extend([Paragraph(escape(s), CELL) for s in row] for row in rows)
    styles = [
        ("BACKGROUND", (0, 0), (-1, 0), WASH),
        ("LINEBELOW", (0, 0), (-1, 0), .7, TEAL),
        ("LINEBELOW", (0, 1), (-1, -1), .35, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]
    if highlight is not None:
        styles.append(("BACKGROUND", (0, highlight+1), (-1, highlight+1), WASH))
    return Table(cells, colWidths=[v*WIDTH for v in widths], hAlign="LEFT",
                 style=TableStyle(styles), spaceAfter=10, repeatRows=1)


def callout(text):
    box = Table([[Paragraph(text, BODY)]], colWidths=[WIDTH], hAlign="LEFT", spaceBefore=5, spaceAfter=13)
    box.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), WASH),
                            ("LINEBEFORE", (0, 0), (0, 0), 2, TEAL),
                            ("LEFTPADDING", (0, 0), (-1, -1), 12),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                            ("TOPPADDING", (0, 0), (-1, -1), 10),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 10)]))
    return box


def metrics():
    summary = [
        ("+4.50 pp", "Reference coverage gained<br/>10 development potatoes"),
        ("14.18 g", "L3 weight MAE<br/>40 development potatoes"),
        ("45/45", "Correct center masks<br/>45 held-out potatoes"),
    ]
    box = Table([[Paragraph(value, KPI) for value, _ in summary],
                 [Paragraph(label, CELL) for _, label in summary]], colWidths=[WIDTH/3]*3, spaceAfter=18)
    box.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), WASH),
                            ("TOPPADDING", (0, 0), (-1, 0), 10),
                            ("BOTTOMPADDING", (0, 1), (-1, 1), 10),
                            ("LEFTPADDING", (0, 0), (-1, -1), 10),
                            ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return box


def figure(path, caption, height):
    image = Image(str(STUDIES / path))
    scale = min(WIDTH / image.imageWidth, height / image.imageHeight)
    image.drawWidth, image.drawHeight = image.imageWidth*scale, image.imageHeight*scale
    return KeepTogether([Spacer(1, 5), image, Spacer(1, 5), Paragraph(caption, SMALL)])


def heading(section, title, description):
    return [Paragraph(section, EYEBROW), Paragraph(title, TITLE), Paragraph(description, LEDE)]


def sources(*links):
    text = " &nbsp;·&nbsp; ".join(f'<link href="{GITHUB}{path}" color="#1A6459">{escape(label)}</link>'
                                    for label, path in links)
    return Paragraph(text, SMALL)


def furniture(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8.5)
    canvas.setFillColor(MUTED)
    canvas.setStrokeColor(LINE)
    canvas.line(MARGIN, 758, letter[0]-MARGIN, 758)
    canvas.drawString(MARGIN, 768, "3DPotatoTwin  /  Proposal results")
    canvas.line(MARGIN, 37, letter[0]-MARGIN, 37)
    canvas.drawString(MARGIN, 25, "Archived studies  /  27 November 2026")
    canvas.drawRightString(letter[0]-MARGIN, 25, f"{doc.page:02}")
    canvas.restoreState()


def build(output):
    """Create the five-page brief, with a dedicated fusion closeout page."""
    p = lambda value: Paragraph(value, BODY)
    sub = lambda value: Paragraph(value, SUB)
    story = [
        *heading("3DPOTATOTWIN / RESULTS BRIEF", "Three Conveyor Views<br/>and One Peel Click",
                 "SAM 2 tracking, RAFT fusion, and center-frame weight and volume estimation."),
        metrics(),
        sub("What the experiments established"),
        p("<b>Fusion added surface.</b> Using the same peel click, three spaced RGB-D frames recovered more "
          "supported surface than the center frame. The fused cloud also contained more points farther than "
          "2 mm from the reference."),
        p("<b>The added surface gave uncertain trait gains.</b> On the separate 30-potato development subset, "
          "paired weight and volume error intervals spanned zero. Among five center-frame estimators on "
          "40 development potatoes, L3 produced the lowest error for both traits."),
        p("<b>One coached operator tracked all 45 held-out potatoes to the center frame.</b> The operator "
          "used a written peel-click instruction and an annotation-derived target arrow."),
        p("<b>Uncertain points supplied useful coverage.</b> Blanket deletion lost 27.46% of the surface "
          "originally added by fusion. Intermediate depth provided more evidence, with reliability varying by potato."),
        callout("<b>Practical decision.</b> Use the center view for weight and volume. With provided masks, use "
                "L3, which combines silhouette with camera-estimated height. Use three-view fusion when additional "
                "surface coverage matters, and retain the uncertain added points with a flag."),
        Paragraph("The 10 geometry and 30 trait potatoes partition the same 40 development potatoes. "
                  "The 45 held-out potatoes belong to the separate center-frame tracking confirmation. "
                  "MAE means mean absolute error. pp means percentage points.", SMALL),
        sources(("Integrated study report", "potato_multiframe_final_report.md")),
        PageBreak(),
        *heading("SURFACE AND TRAITS", "What three views add",
                 "The same entry-frame peel click initialized the center view and three-frame fusion."),
        table(("Geometry metric (10 paired potatoes)", "Center", "Fusion", "Change (pp) [95% interval]"), [
            ("Reference surface within 2 mm", "36.63%", "41.14%", "+4.50 [+3.71, +5.33]"),
            ("Coverage at equal point count", "36.62%", "40.61%", "+3.99 [+3.27, +4.77]"),
            ("Output centroids more than 2 mm from reference", "4.31%", "5.85%", "+1.54 [+0.92, +2.23]"),
        ], (.44, .12, .12, .32)),
        figure("raft_fusion_geometry_v1/typical_coverage.png",
                "<b>Figure 1.</b> Archived provided-mask example R1-3. Green marks newly covered reference surface, "
                "red marks coverage lost, and gray marks surface still uncovered at the 2 mm threshold. "
                "The percentages in the figure describe this example.", 218),
        sub("Weight and volume on the other 30 development potatoes"),
        table(("Trait", "Center MAE", "Fusion MAE", "Fusion minus center [paired 95% interval]"), [
            ("Weight", "14.78 g", "14.27 g", "-0.51 g [-1.52, +0.37]"),
            ("Water-displacement volume", "15.28 mL", "15.14 mL", "-0.14 mL [-1.10, +0.71]"),
        ], (.30, .14, .14, .42)),
        p("Fusion added <b>17.1 seconds per potato</b> in timed processing. Both error intervals span zero. "
          "Extra surface can leave the projected silhouette and estimated height largely unchanged."),
        sources(("Same-click fusion", "sam2_raft_end_to_end_v1/report.md"),
                ("Provided-mask geometry pilot", "raft_fusion_geometry_v1/report.md")),
        PageBreak(),
        *heading("FUSION CLOSEOUT", "Keep the added surface",
                 "The same ten geometry potatoes were used to check how uncertain points contributed to the fused surface."),
        p("We removed all <b>12,144 raw outer-view points</b> without a usable depth comparison, then rebuilt the "
          "<b>1 mm fused voxel centroids</b>. The comparison removed the same number of raw points at random."),
        table(("Reconstruction", "Centroids farther than 2 mm", "New surface lost", "Area lost per potato"), [
            ("Archived fusion", "5.85%", "0.00%", "0.00 mm²"),
            ("Zero-comparison removal", "4.82%", "27.46%", "165.20 mm²"),
            ("Count-matched random removal", "5.82%", "0.37%", "2.06 mm²"),
        ], (.34, .25, .20, .21)),
        p("Intermediate frames supplied usable depth for <b>7,816/12,144 raw points (64.36%)</b>. Those frames also "
          "helped estimate pose. Independent structure-from-motion (SfM) geometry supplied the accuracy labels. "
          "On the nine potatoes with both categories, equal-potato error rates were <b>39.44%</b> after a depth "
          "contradiction and <b>17.32%</b> after agreement."),
        figure("intermediate_depth_verification_v1/contrasting_examples.png",
                "<b>Figure 2.</b> Each pair shows the same raw points. On 2R1-9, 0/39 contradictions exceeded "
                "2 mm SfM error. On R10-10, 36/36 did. Contradictions were more error-prone on <b>6/9</b> "
                "comparable potatoes. The results support keeping uncertain points when surface coverage matters.", 252),
        sources(("Blanket deletion", "zero_comparison_fusion_v1/report.md"),
                ("Intermediate-frame diagnostic", "intermediate_depth_verification_v1/report.md")),
        PageBreak(),
        *heading("MATCHED CENTER-FRAME BENCHMARK", "Camera height was best",
                 "All five estimators scored the same 40 development potatoes for weight and water-displacement volume."),
        table(("Estimator", "Weight MAE (g)", "Volume MAE (mL)", "Weight change vs L0 (g) [paired 95% interval]"), [
            ("L0  Silhouette alone", "16.02", "16.99", "Baseline"),
            ("L1  Frozen monocular height", "23.71", "22.75", "+7.69 [+3.76, +11.55]"),
            ("L2  Learned RGB height", "15.92", "16.73", "-0.10 [-0.53, +0.29]"),
            ("L3  Silhouette + camera-estimated height", "14.18", "15.12", "-1.83 [-3.16, -0.57]"),
            ("L4  RGB-D point cloud + the L3 height", "35.46", "35.92", "+19.44 [+6.14, +34.25]"),
        ], (.40, .13, .14, .33), highlight=3),
        Paragraph("Paired intervals resample potatoes. Negative changes indicate lower absolute error. "
                  "Differences use unrounded errors.", SMALL),
        sub("What the alternatives added"),
        p("<b>Frozen monocular height (L1).</b> It overestimated the camera-height proxy on all 40 potatoes, "
          "by 30.21 mm on average. Pixels in roller gaps could inflate the estimated belt depth. "
          "Their contribution remains unmeasured."),
        p("<b>Learned RGB height (L2).</b> The 0.10 g improvement over silhouette alone was small, "
          "with a paired interval spanning zero."),
        p("<b>RGB-D point cloud (L4).</b> With the same height cue, weight MAE increased by 21.28 g [7.78, 36.49] "
          "and volume MAE by 20.80 mL [10.43, 31.51] relative to L3. All three seeds gave higher MAE for both traits. "
          "The comparison changes both the input representation and estimator."),
        callout("<b>Benchmark scope.</b> All five arms used provided masks and fixed calibration. L3 used raw "
                "depth and the nominal 350 mm belt distance. This benchmark used no measured tuber thickness. "
                "The L3 advantage still needs validation on an independent acquisition."),
        sources(("L0 and L3", "rgb_only_height_value_v1/report.md"),
                ("L1", "rgb_monocular_height_v1/report.md"), ("L2", "rgb_predicted_height_v1/report.md"),
                ("L4", "rgbd_pointcloud_l4_v1/report.md"),
                ("Independent acquisition audit", "rgb_only_height_value_v1/independent_validation_audit.md")),
        PageBreak(),
        *heading("TRACKING AND PROPOSAL STATUS", "One peel click can work",
                 "One first-time operator used the frozen written instruction and an annotation-derived target arrow."),
        callout("<b>45/45 correct held-out center masks.</b> A correct mask had intersection over union of at least "
                "0.5. The exact 95% interval was 92.1% to 100%. All weights were scorable. MAE was 12.26 g with "
                "SAM 2 and 12.36 g with provided masks, a paired change of -0.11 g (95% interval -0.85 to +0.60 g)."),
        table(("Prompt development (same 40 potatoes)", "Correct center masks"), [
            ("Simulated deepest-interior prompt", "24/40"),
            ("Controlled relocation of the 12 pin clicks onto peel", "34/40"),
            ("First human session", "1/40"),
            ("Coached human repeat", "40/40"),
        ], (.72, .28)),
        p("The registration pin often attracted the tracker in development. The coached instruction directed "
          "the click to peel, away from the pin and edge. These SAM 2 and fusion pipelines used measured tuber "
          "thickness for depth filtering. The held-out study evaluated center-frame tracking and weight."),
        sub("Proposal checklist"),
        table(("Aim", "Status", "Evidence or open comparison"), [
            ("Recover more surface", "Tested", "Same-click fusion increased 2 mm coverage."),
            ("Improve weight or volume with fusion", "Tested", "The 30-potato paired intervals spanned zero."),
            ("RAFT vs ICP registration", "Partial", "Reference results modestly favored RAFT. Independent frame poses are unavailable."),
            ("View direction and aggregation", "Partial", "Centroid rays and arithmetic averaging tested. Cloud rotation and learned weighting remain open."),
            ("One-click masks and end-to-end fusion", "Tested", "45 held-out center masks and 40 separate development fusion cases."),
            ("Matched L0 to L4", "Tested", "L3 had the lowest error for both traits."),
        ], (.31, .12, .57)),
        sources(("SAM 2 final report", "sam2_human_prompt_confirmation_v1/final_report.md"),
                ("Integrated proposal checklist", "potato_multiframe_final_report.md#proposal-checklist")),
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(output), pagesize=letter, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=51,
                            bottomMargin=45, title="Three Conveyor Views and One Peel Click",
                            subject="Potato3D proposal results and fusion closeout", author="Potato3D project")
    doc.build(story, onFirstPage=furniture, onLaterPages=furniture)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    build(parser.parse_args().output)

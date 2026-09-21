"""
report_generator.py
--------------------
Generates a digital compliance / non-compliance PDF report for a given
scan, suitable for attachment to enforcement case files.
"""

import json
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image as RLImage
)


STATUS_COLORS = {
    "COMPLIANT": colors.HexColor("#1a7f37"),
    "NON_COMPLIANT": colors.HexColor("#cf222e"),
    "NEEDS_REVIEW": colors.HexColor("#9a6700"),
}


def generate_pdf_report(scan, product, output_path, image_path=None):
    doc = SimpleDocTemplate(output_path, pagesize=A4,
                             topMargin=1.5 * cm, bottomMargin=1.5 * cm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("TitleC", parent=styles["Title"], fontSize=16)
    h2 = ParagraphStyle("H2", parent=styles["Heading2"], spaceBefore=10)
    normal = styles["Normal"]

    elements = []

    elements.append(Paragraph("Legal Metrology (Packaged Commodities) Rules, 2011", title_style))
    elements.append(Paragraph("Compliance Inspection Report", styles["Heading3"]))
    elements.append(Spacer(1, 10))

    declarations = json.loads(scan.declarations_json)
    font_analysis = json.loads(scan.font_analysis_json)
    summary = json.loads(scan.summary_json)

    status = summary.get("status", "N/A")
    status_color = STATUS_COLORS.get(status, colors.black)

    meta_table_data = [
        ["Report ID", f"SCAN-{scan.id:06d}"],
        ["Product Name", product.name],
        ["Brand", product.brand or "-"],
        ["Category", product.category or "-"],
        ["Inspection Location", scan.location or "-"],
        ["Inspector", scan.inspector.full_name or scan.inspector.username],
        ["Date of Inspection", scan.created_at.strftime("%d-%b-%Y %H:%M")],
        ["Overall Status", status],
    ]
    meta_table = Table(meta_table_data, colWidths=[5 * cm, 10 * cm])
    meta_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f0f2f5")),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (1, 7), (1, 7), status_color),
        ("FONTNAME", (1, 7), (1, 7), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    elements.append(meta_table)
    elements.append(Spacer(1, 14))

    if image_path:
        try:
            elements.append(Paragraph("Scanned Label Image", h2))
            elements.append(RLImage(image_path, width=9 * cm, height=9 * cm, kind="proportional"))
            elements.append(Spacer(1, 10))
        except Exception:
            pass

    elements.append(Paragraph("Mandatory Declaration Checklist", h2))
    decl_data = [["Declaration", "Rule Ref.", "Status", "Notes"]]
    for d in declarations:
        stat = "✔ Found" if d["found"] else ("N/A" if not d["required"] else "✘ MISSING")
        decl_data.append([
            Paragraph(d["label"], normal),
            Paragraph(d["rule_ref"], normal),
            stat,
            Paragraph(d.get("notes", "") or "-", normal),
        ])
    decl_table = Table(decl_data, colWidths=[5.0 * cm, 3.3 * cm, 2.2 * cm, 4.5 * cm])
    decl_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    elements.append(decl_table)
    elements.append(Spacer(1, 14))

    elements.append(Paragraph("Font Size / Readability Analysis", h2))
    fa_text = (
        f"Measurement basis: {font_analysis.get('measurement_basis', 'estimated')} | "
        f"Average letter height: {font_analysis.get('average_letter_height_mm', 'N/A')} mm | "
        f"Minimum required: {font_analysis.get('min_required_mm', 'N/A')} mm | "
        f"Violations: {font_analysis.get('violation_count', 0)}"
    )
    elements.append(Paragraph(fa_text, normal))
    if font_analysis.get("violations"):
        elements.append(Spacer(1, 6))
        viol_data = [["Text Segment", "Detected Height (mm)", "Min Required (mm)"]]
        for v in font_analysis["violations"][:15]:
            viol_data.append([v["text"], str(v["height_mm"]), str(v["min_required_mm"])])
        viol_table = Table(viol_data, colWidths=[6 * cm, 4.5 * cm, 4.5 * cm])
        viol_table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#7a0000")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
        ]))
        elements.append(viol_table)

    elements.append(Spacer(1, 14))
    elements.append(Paragraph("Summary", h2))
    summary_lines = [
        f"Missing mandatory declarations: {', '.join(summary.get('missing_required', [])) or 'None'}",
        f"Items needing manual review: {', '.join(summary.get('needs_review', [])) or 'None'}",
        f"Font-size violations detected: {summary.get('font_violations', 0)}",
    ]
    for line in summary_lines:
        elements.append(Paragraph(line, normal))

    if scan.remarks:
        elements.append(Spacer(1, 10))
        elements.append(Paragraph("Inspector Remarks", h2))
        elements.append(Paragraph(scan.remarks, normal))

    elements.append(Spacer(1, 20))
    elements.append(Paragraph(
        f"Generated by LMPC Compliance Scanner on {datetime.now().strftime('%d-%b-%Y %H:%M')}. "
        "This is a system-generated preliminary assessment; final determination of non-compliance "
        "rests with the competent Legal Metrology authority.",
        ParagraphStyle("Footer", parent=normal, fontSize=7, textColor=colors.grey)
    ))

    doc.build(elements)
    return output_path

from __future__ import annotations
from datetime import datetime
from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether, HRFlowable
from sqlalchemy import select
from sqlalchemy.orm import Session
from .config import REPORT_DIR
from .models import Business, Exposure, Projection, ReviewItem, Report, ReviewPacket

GREEN = colors.HexColor("#005C3E")
LIGHT = colors.HexColor("#EBF2F0")

def build_report(db: Session, business: Business, user_id: int) -> Report:
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"commercialcore_{business.id}_{stamp}.pdf"
    path = REPORT_DIR / filename
    doc = SimpleDocTemplate(str(path), pagesize=letter, rightMargin=42, leftMargin=42, topMargin=42, bottomMargin=42)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="CCHeading", parent=styles["Heading1"], textColor=GREEN, fontSize=20, leading=24))
    styles.add(ParagraphStyle(name="CCSub", parent=styles["Heading2"], textColor=GREEN, fontSize=13))
    story = [
        Paragraph("CommercialCore Review", styles["CCHeading"]),
        Paragraph(f"{business.legal_name} | Generated {datetime.utcnow():%B %d, %Y}", styles["Normal"]),
        Spacer(1, 14),
        Paragraph("Internal agency workflow — not a carrier system", styles["Italic"]),
        Spacer(1, 18),
    ]
    rows = [["Exposure", "Recorded estimate", "Projection", "Variance", "Accuracy", "Confidence", "Index"]]
    exposures = []
    for policy in business.policies:
        exposures.extend(policy.exposures)
    for exposure in exposures:
        projection = db.scalar(select(Projection).where(Projection.exposure_id == exposure.id).order_by(Projection.created_at.desc()))
        if projection:
            rows.append([
                exposure.exposure_type.replace("_", " ").title(),
                f"${float(exposure.recorded_estimate):,.0f}",
                f"${float(projection.projected_total):,.0f}",
                f"{float(projection.variance_percent):+.1f}%",
                str(projection.accuracy_score),
                str(projection.confidence_score),
                str(projection.core_index),
            ])
    table = Table(rows, repeatRows=1, colWidths=[90, 80, 80, 55, 50, 55, 40])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), GREEN),
        ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("BACKGROUND", (0,1), (-1,-1), LIGHT),
        ("GRID", (0,0), (-1,-1), 0.35, colors.HexColor("#B2CEC5")),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,-1), 8),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("LEFTPADDING", (0,0), (-1,-1), 5),
        ("RIGHTPADDING", (0,0), (-1,-1), 5),
    ]))
    story += [Paragraph("Exposure summary", styles["CCSub"]), table, Spacer(1, 18)]
    reviews = list(db.scalars(select(ReviewItem).where(ReviewItem.business_id == business.id).order_by(ReviewItem.created_at.desc())))
    story.append(Paragraph("Review items", styles["CCSub"]))
    if reviews:
        for review in reviews:
            story.append(Paragraph(f"<b>{review.priority.upper()} — {review.title}</b><br/>{review.evidence}<br/>Status: {review.status}", styles["Normal"]))
            story.append(Spacer(1, 8))
    else:
        story.append(Paragraph("No review items are currently recorded.", styles["Normal"]))
    story += [
        Spacer(1, 18),
        Paragraph("Boundary statement", styles["CCSub"]),
        Paragraph("This report summarizes client-provided business activity, transparent projections, and agency workflow observations. It does not determine coverage adequacy, calculate carrier premium, bind coverage, or direct a carrier transaction.", styles["Normal"]),
    ]
    doc.build(story)
    report = Report(business_id=business.id, status="draft", file_name=filename, generated_by=user_id)
    db.add(report)
    db.flush()
    return report


def _safe(text):
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")

def _packet_header_footer(canvas, doc):
    canvas.saveState()
    w, h = letter
    canvas.setFillColor(GREEN)
    canvas.rect(0, h-22, w, 22, fill=1, stroke=0)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#64756F"))
    canvas.drawString(42, 24, "CommercialCore | Internal agency review workflow")
    canvas.drawRightString(w-42, 24, f"Page {doc.page}")
    canvas.restoreState()

def build_review_packet_pdf(db: Session, business: Business, packet: ReviewPacket) -> str:
    import json
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"annual_review_{business.id}_{packet.id}_{stamp}.pdf"
    path = REPORT_DIR / filename
    sections = json.loads(packet.sections_json or "{}")
    doc = SimpleDocTemplate(str(path), pagesize=letter, rightMargin=42, leftMargin=42, topMargin=48, bottomMargin=42)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="PacketTitle", parent=styles["Title"], textColor=GREEN, fontSize=24, leading=28, spaceAfter=8))
    styles.add(ParagraphStyle(name="PacketH1", parent=styles["Heading1"], textColor=GREEN, fontSize=16, leading=20, spaceBefore=8, spaceAfter=8))
    styles.add(ParagraphStyle(name="PacketH2", parent=styles["Heading2"], textColor=GREEN, fontSize=12, leading=15, spaceBefore=6, spaceAfter=5))
    styles.add(ParagraphStyle(name="PacketBody", parent=styles["BodyText"], fontSize=9.5, leading=14, textColor=colors.HexColor("#24332E")))
    styles.add(ParagraphStyle(name="PacketSmall", parent=styles["BodyText"], fontSize=8, leading=11, textColor=colors.HexColor("#64756F")))
    story=[]
    story += [Spacer(1, 34), Paragraph(packet.title, styles["PacketTitle"]), Paragraph(business.legal_name, styles["PacketH1"])]
    meta=[]
    if packet.prepared_for: meta.append(["Prepared for", packet.prepared_for])
    if packet.meeting_date: meta.append(["Review date", packet.meeting_date.strftime("%B %d, %Y")])
    if business.producer: meta.append(["Agency contact", business.producer.full_name])
    if meta:
        mt=Table(meta, colWidths=[95, 330], hAlign="LEFT")
        mt.setStyle(TableStyle([("TEXTCOLOR",(0,0),(0,-1),GREEN),("FONTNAME",(0,0),(0,-1),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),9),("BOTTOMPADDING",(0,0),(-1,-1),6)]))
        story += [Spacer(1,8), mt]
    story += [Spacer(1,24), HRFlowable(width="100%", thickness=1, color=colors.HexColor("#BFD3CC")), Spacer(1,16)]
    if packet.executive_summary:
        story += [Paragraph("Executive summary", styles["PacketH1"]), Paragraph(_safe(packet.executive_summary), styles["PacketBody"]), Spacer(1,12)]
    exposures=[]
    for policy in business.policies: exposures.extend(policy.exposures)
    latest={}
    for exposure in exposures:
        latest[exposure.id]=db.scalar(select(Projection).where(Projection.exposure_id==exposure.id).order_by(Projection.created_at.desc()))
    scored=[x for x in latest.values() if x]
    if sections.get("account_snapshot", True):
        story.append(Paragraph("Account snapshot", styles["PacketH1"]))
        next_policy=min((p for p in business.policies if p.expiration_date >= datetime.utcnow().date()), key=lambda p:p.expiration_date, default=None)
        core=round(sum(x.core_index for x in scored)/len(scored)) if scored else None
        accuracy=round(sum(x.accuracy_score for x in scored)/len(scored)) if scored else None
        confidence=round(sum(x.confidence_score for x in scored)/len(scored)) if scored else None
        data=[["CommercialCore Index", str(core) if core is not None else "Not scored", "Exposure Accuracy", str(accuracy) if accuracy is not None else "Not scored"],
              ["Reporting Confidence", str(confidence) if confidence is not None else "Not scored", "Next renewal", next_policy.expiration_date.strftime("%b %d, %Y") if next_policy else "Not entered"]]
        t=Table(data, colWidths=[105,95,115,115])
        t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),LIGHT),("BOX",(0,0),(-1,-1),.5,colors.HexColor("#B2CEC5")),("INNERGRID",(0,0),(-1,-1),.35,colors.HexColor("#D3E2DD")),("FONTNAME",(0,0),(-1,-1),"Helvetica-Bold"),("TEXTCOLOR",(0,0),(-1,-1),GREEN),("FONTSIZE",(0,0),(-1,-1),9),("VALIGN",(0,0),(-1,-1),"MIDDLE"),("TOPPADDING",(0,0),(-1,-1),10),("BOTTOMPADDING",(0,0),(-1,-1),10)]))
        story += [t, Spacer(1,14)]
    if sections.get("policy_summary", True):
        story.append(Paragraph("Policy and renewal summary", styles["PacketH1"]))
        rows=[["Line", "Carrier", "Policy reference", "Effective", "Expiration"]]
        for p in sorted(business.policies, key=lambda x:x.expiration_date):
            rows.append([p.line, p.carrier_reference.carrier_name if p.carrier_reference else "Not entered", p.policy_number_ref or "-", p.effective_date.strftime("%m/%d/%Y"), p.expiration_date.strftime("%m/%d/%Y")])
        if len(rows)==1: rows.append(["No policies entered", "", "", "", ""])
        t=Table(rows, repeatRows=1, colWidths=[110,105,100,72,72])
        t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),GREEN),("TEXTCOLOR",(0,0),(-1,0),colors.white),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),8),("GRID",(0,0),(-1,-1),.35,colors.HexColor("#C8DAD4")),("BACKGROUND",(0,1),(-1,-1),colors.white),("VALIGN",(0,0),(-1,-1),"MIDDLE"),("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6)]))
        story += [t, Spacer(1,14)]
    if sections.get("exposure_analysis", True):
        story.append(Paragraph("Exposure analysis", styles["PacketH1"]))
        rows=[["Exposure", "Estimate", "Projection", "Variance", "Accuracy", "Confidence", "Index"]]
        for e in exposures:
            pr=latest[e.id]
            rows.append([e.exposure_type.replace("_"," ").title(), f"${float(e.recorded_estimate):,.0f}", f"${float(pr.projected_total):,.0f}" if pr else "Not scored", f"{float(pr.variance_percent):+.1f}%" if pr else "-", str(pr.accuracy_score) if pr else "-", str(pr.confidence_score) if pr else "-", str(pr.core_index) if pr else "-"])
        if len(rows)==1: rows.append(["No monitored exposures", "", "", "", "", "", ""])
        t=Table(rows, repeatRows=1, colWidths=[92,70,70,50,48,52,35])
        t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),GREEN),("TEXTCOLOR",(0,0),(-1,0),colors.white),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),7.5),("GRID",(0,0),(-1,-1),.35,colors.HexColor("#C8DAD4")),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,LIGHT]),("VALIGN",(0,0),(-1,-1),"MIDDLE"),("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6)]))
        story += [t, Spacer(1,14)]
    if sections.get("review_items", True):
        story.append(Paragraph("Items for discussion", styles["PacketH1"]))
        reviews=list(db.scalars(select(ReviewItem).where(ReviewItem.business_id==business.id, ReviewItem.status!="closed").order_by(ReviewItem.priority, ReviewItem.created_at.desc())))
        if reviews:
            for r in reviews:
                story += [KeepTogether([Paragraph(f"<b>{r.priority.upper()} - {_safe(r.title)}</b>", styles["PacketBody"]), Paragraph(_safe(r.evidence), styles["PacketSmall"]), Spacer(1,7)])]
        else: story.append(Paragraph("No open review items are currently recorded.", styles["PacketBody"]))
        story.append(Spacer(1,8))
    for heading, value in [("Discussion points", packet.discussion_points),("Agency recommendations", packet.recommendations),("Agreed next steps", packet.next_steps)]:
        if value:
            story += [Paragraph(heading, styles["PacketH1"]), Paragraph(_safe(value), styles["PacketBody"]), Spacer(1,12)]
    if sections.get("contact_summary", True):
        story.append(Paragraph("Account contacts", styles["PacketH1"]))
        rows=[["Name", "Role", "Email", "Phone"]]
        for c in business.contacts: rows.append([c.name,c.title or "-",c.email or "-",c.phone or "-"])
        if len(rows)==1: rows.append(["No contacts entered", "", "", ""])
        t=Table(rows, repeatRows=1, colWidths=[120,100,170,90])
        t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),GREEN),("TEXTCOLOR",(0,0),(-1,0),colors.white),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),8),("GRID",(0,0),(-1,-1),.35,colors.HexColor("#C8DAD4")),("VALIGN",(0,0),(-1,-1),"MIDDLE"),("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6)]))
        story += [t, Spacer(1,14)]
    story += [Spacer(1,10), Paragraph("Important boundary", styles["PacketH2"]), Paragraph("This packet summarizes client-provided business activity, transparent projections, and agency workflow observations. It does not determine coverage adequacy, calculate carrier premium, bind coverage, or direct a carrier transaction. Coverage recommendations remain subject to licensed review, carrier underwriting, policy terms, conditions, and exclusions.", styles["PacketSmall"])]
    doc.build(story, onFirstPage=_packet_header_footer, onLaterPages=_packet_header_footer)
    packet.file_name=filename
    packet.status="generated"
    return filename


def build_executive_management_pdf(db: Session, generated_by: str, as_of=None) -> str:
    """Create the Phase 7.4.4 monthly executive management report."""
    from datetime import date
    from .insights import executive_analytics, staff_analytics, portfolio_analytics, portfolio_intelligence

    as_of = as_of or date.today()
    analytics = executive_analytics(db, as_of)
    staff = staff_analytics(db, as_of)
    portfolio = portfolio_analytics(db, as_of)
    intelligence = portfolio_intelligence(db, as_of)
    filename = f"executive_management_{as_of.isoformat()}.pdf"
    path = REPORT_DIR / filename

    doc = SimpleDocTemplate(str(path), pagesize=letter, rightMargin=36, leftMargin=36, topMargin=38, bottomMargin=38)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="ExecTitle", parent=styles["Title"], textColor=GREEN, fontSize=22, leading=27, spaceAfter=8))
    styles.add(ParagraphStyle(name="ExecH2", parent=styles["Heading2"], textColor=GREEN, fontSize=14, leading=18, spaceBefore=8, spaceAfter=7))
    styles.add(ParagraphStyle(name="ExecSmall", parent=styles["BodyText"], fontSize=8.5, leading=11, textColor=colors.HexColor("#52635A")))
    story = [
        Paragraph("CommercialCore Executive Management Report", styles["ExecTitle"]),
        Paragraph(f"Reporting date: {as_of.strftime('%B %d, %Y')} &nbsp;&nbsp; Generated by: {generated_by}", styles["ExecSmall"]),
        Spacer(1, 14),
    ]

    kpis = [
        ["Tracked annual premium", f"${analytics['active_premium']:,.0f}"],
        ["Average CommercialCore Index", str(analytics['average_core']) if analytics['average_core'] is not None else "Not scored"],
        ["Businesses requiring focus", str(intelligence['accounts_requiring_focus'])],
        ["Overdue reporting accounts", str(analytics['overdue_account_count'])],
        ["Open tasks", str(staff['open_tasks'])],
        ["Overdue tasks", str(staff['overdue_tasks'])],
    ]
    kpi_table = Table(kpis, colWidths=[225, 225])
    kpi_table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), LIGHT), ("BOX", (0,0), (-1,-1), 0.6, colors.HexColor("#C9D8D1")),
        ("INNERGRID", (0,0), (-1,-1), 0.4, colors.HexColor("#D9E4DF")), ("TEXTCOLOR", (0,0), (0,-1), GREEN),
        ("FONTNAME", (0,0), (0,-1), "Helvetica-Bold"), ("FONTNAME", (1,0), (1,-1), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,-1), 10), ("VALIGN", (0,0), (-1,-1), "MIDDLE"), ("PADDING", (0,0), (-1,-1), 8),
    ]))
    story += [kpi_table, Spacer(1, 14), Paragraph("Portfolio scorecard", styles["ExecH2"])]

    health_rows = [["Health", "Accounts", "Share"]] + [[r["label"], str(r["count"]), f"{r['percent']}%"] for r in analytics["health_distribution"]]
    health_table = Table(health_rows, colWidths=[240, 100, 100])
    health_table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), GREEN), ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"), ("GRID", (0,0), (-1,-1), 0.4, colors.HexColor("#D3DED8")),
        ("FONTSIZE", (0,0), (-1,-1), 9), ("PADDING", (0,0), (-1,-1), 6),
    ]))
    story += [health_table, Spacer(1, 12), Paragraph("Six-month renewal pipeline", styles["ExecH2"])]

    renewal_rows = [["Month", "Policies", "Premium"]] + [[r["label"], str(r["count"]), f"${r['premium']:,.0f}"] for r in analytics["renewal_pipeline"]]
    renewal_table = Table(renewal_rows, colWidths=[200, 100, 140])
    renewal_table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), GREEN), ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"), ("GRID", (0,0), (-1,-1), 0.4, colors.HexColor("#D3DED8")),
        ("FONTSIZE", (0,0), (-1,-1), 9), ("PADDING", (0,0), (-1,-1), 6),
    ]))
    story += [renewal_table, PageBreak(), Paragraph("Portfolio composition", styles["ExecH2"])]

    composition_rows = [["Category", "Leading segment", "Premium", "Share"]]
    for title, rows in [("Carrier", portfolio["premium_by_carrier"]), ("Industry", portfolio["premium_by_industry"]), ("Policy line", portfolio["premium_by_line"])]:
        if rows:
            top = rows[0]
            composition_rows.append([title, top["label"], f"${top['premium']:,.0f}", f"{top['percent']}%"])
        else:
            composition_rows.append([title, "No tracked data", "$0", "0%"])
    composition = Table(composition_rows, colWidths=[100, 180, 100, 70])
    composition.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), GREEN), ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"), ("GRID", (0,0), (-1,-1), 0.4, colors.HexColor("#D3DED8")),
        ("FONTSIZE", (0,0), (-1,-1), 9), ("PADDING", (0,0), (-1,-1), 6),
    ]))
    story += [composition, Spacer(1, 12), Paragraph("Largest tracked accounts", styles["ExecH2"])]

    largest_rows = [["Account", "Policies", "Premium", "Portfolio share"]]
    for row in portfolio["largest_accounts"][:8]:
        largest_rows.append([row["business"].legal_name, str(row["policy_count"]), f"${row['premium']:,.0f}", f"{row['percent']}%"])
    if len(largest_rows) == 1:
        largest_rows.append(["No tracked accounts", "0", "$0", "0%"])
    largest = Table(largest_rows, colWidths=[210, 70, 100, 90])
    largest.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), GREEN), ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"), ("GRID", (0,0), (-1,-1), 0.4, colors.HexColor("#D3DED8")),
        ("FONTSIZE", (0,0), (-1,-1), 8.5), ("PADDING", (0,0), (-1,-1), 5),
    ]))
    story += [largest, Spacer(1, 12), Paragraph("Staff scorecard", styles["ExecH2"])]

    staff_rows = [["Staff member", "Open", "Overdue", "Completed 30d", "Activities 30d"]]
    for row in staff["rows"]:
        staff_rows.append([row["user"].full_name, str(row["open_tasks"]), str(row["overdue_tasks"]), str(row["completed_30"]), str(row["activities_30"])])
    staff_table = Table(staff_rows, colWidths=[180, 60, 65, 90, 90])
    staff_table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), GREEN), ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"), ("GRID", (0,0), (-1,-1), 0.4, colors.HexColor("#D3DED8")),
        ("FONTSIZE", (0,0), (-1,-1), 8), ("PADDING", (0,0), (-1,-1), 5),
    ]))
    story += [staff_table, Spacer(1, 12), Paragraph("Management notes", styles["ExecH2"]),
              Paragraph("Metrics are calculated from stored CommercialCore records as of the reporting date. Premium totals include active policies with annual premium entered. Projection movement requires at least two stored projections.", styles["ExecSmall"])]
    doc.build(story)
    return str(path)

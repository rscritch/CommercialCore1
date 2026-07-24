from __future__ import annotations
from datetime import date, datetime, timedelta
import json
import uuid
from pathlib import Path
from fastapi import FastAPI, Request, Form, Depends, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import select, func, text
from sqlalchemy.orm import Session, selectinload

from .config import SECRET_KEY, REPORT_DIR, UPLOAD_DIR, ADMIN_USERNAME, ADMIN_PASSWORD, ADMIN_FULL_NAME
from .db import Base, engine, get_db, SessionLocal
from .models import (
    User, Business, Contact, Location, Policy, Exposure, ReportingEntry,
    Projection, ReviewItem, AgencyNote, Report, AuditEvent, AccountNote, PolicyCarrier, ReviewPacket, Task, Activity, Document, Recommendation
)
from .security import hash_password, verify_password, current_user, require_user, require_role
from .services import audit, overlap_exists, calculate_projection, store_import
from .insights import reporting_insights, portfolio_insights, executive_dashboard_insights, business_detail_insights, portfolio_intelligence, executive_analytics, staff_analytics, portfolio_analytics, historical_analytics
from .recommendations import sync_recommendations, actions as recommendation_actions
from .reports import build_report, build_review_packet_pdf, build_executive_management_pdf

app = FastAPI(title="CommercialCore")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, same_site="lax")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

def initialize():
    Base.metadata.create_all(engine)
    # Lightweight SQLite upgrade for installations created before v1.2.
    with engine.begin() as connection:
        if engine.dialect.name == "sqlite":
            policy_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(policies)"))}
            if "annual_premium" not in policy_columns:
                connection.execute(text("ALTER TABLE policies ADD COLUMN annual_premium NUMERIC(14, 2)"))
            projection_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(projections)"))}
            if "scoring_version" not in projection_columns:
                connection.execute(text("ALTER TABLE projections ADD COLUMN scoring_version VARCHAR(20)"))
            if "score_details" not in projection_columns:
                connection.execute(text("ALTER TABLE projections ADD COLUMN score_details TEXT"))
    with SessionLocal() as db:
        if not db.scalar(select(User).where(User.username == ADMIN_USERNAME)):
            db.add(User(
                username=ADMIN_USERNAME,
                full_name=ADMIN_FULL_NAME,
                password_hash=hash_password(ADMIN_PASSWORD),
                role="administrator",
                active=True,
            ))
            db.commit()

@app.on_event("startup")
def startup():
    initialize()

def render(request, template, context, db):
    context = dict(context)
    context["request"] = request
    context["user"] = current_user(request, db)
    return templates.TemplateResponse(request, template, context)


@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    if not current_user(request, db):
        return RedirectResponse("/login", 303)
    return RedirectResponse("/dashboard", 303)

@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request, db: Session = Depends(get_db)):
    return render(request, "login.html", {}, db)

@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == username))
    if not user or not user.active or not verify_password(password, user.password_hash):
        return render(request, "login.html", {"error": "Invalid username or password."}, db)
    request.session["user_id"] = user.id
    return RedirectResponse("/dashboard", 303)

@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", 303)

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    businesses = db.scalar(select(func.count()).select_from(Business)) or 0
    open_reviews = db.scalar(select(func.count()).select_from(ReviewItem).where(ReviewItem.status != "closed")) or 0
    high_reviews = db.scalar(select(func.count()).select_from(ReviewItem).where(ReviewItem.status != "closed", ReviewItem.priority == "high")) or 0
    latest = list(db.scalars(select(ReviewItem).options(selectinload(ReviewItem.business), selectinload(ReviewItem.assignee)).where(ReviewItem.status != "closed").order_by(ReviewItem.priority, ReviewItem.created_at.desc()).limit(10)))
    portfolio = portfolio_insights(db)
    executive = executive_dashboard_insights(db)
    intelligence = portfolio_intelligence(db)
    analytics = executive_analytics(db)
    staff = staff_analytics(db)
    portfolio_analytics_data = portfolio_analytics(db)
    history = historical_analytics(db)
    for business in db.scalars(select(Business)):
        sync_recommendations(db, business)
    db.commit()
    recommendations = list(db.scalars(select(Recommendation).options(selectinload(Recommendation.business)).where(
        Recommendation.status.in_(["open", "task_created", "packet_added"])
    ).order_by(Recommendation.priority, Recommendation.created_at.desc()).limit(8)))
    recommendation_action_map = {r.id: recommendation_actions(r) for r in recommendations}
    today = date.today()
    task_stmt = select(Task).options(selectinload(Task.business), selectinload(Task.assignee)).where(Task.status != "completed")
    if user.role != "administrator": task_stmt = task_stmt.where(Task.assigned_to == user.id)
    crm_tasks = list(db.scalars(task_stmt.order_by(Task.due_date.is_(None), Task.due_date).limit(12)))
    crm_overdue = sum(1 for t in crm_tasks if t.due_date and t.due_date < today)
    crm_due_week = sum(1 for t in crm_tasks if t.due_date and today <= t.due_date <= today + timedelta(days=7))
    team_open_tasks = db.scalar(select(func.count()).select_from(Task).where(Task.status != "completed")) or 0
    return render(request, "dashboard.html", {
        "business_count": businesses,
        "open_reviews": open_reviews,
        "high_reviews": high_reviews,
        "latest_reviews": latest,
        "portfolio": portfolio,
        "executive": executive, "intelligence": intelligence, "analytics": analytics, "staff": staff, "portfolio_analytics": portfolio_analytics_data, "history": history, "crm_tasks": crm_tasks, "crm_overdue": crm_overdue, "crm_due_week": crm_due_week, "team_open_tasks": team_open_tasks,
        "recommendations": recommendations, "recommendation_action_map": recommendation_action_map,
    }, db)


@app.get("/executive-reports", response_class=HTMLResponse)
def executive_reports_page(request: Request, db: Session = Depends(get_db)):
    require_user(request, db)
    return render(request, "executive_reports.html", {
        "analytics": executive_analytics(db),
        "staff": staff_analytics(db),
        "portfolio": portfolio_analytics(db),
        "intelligence": portfolio_intelligence(db),
    }, db)

@app.get("/executive-reports/management.pdf")
def executive_management_pdf(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    path = build_executive_management_pdf(db, user.full_name)
    audit(db, user.id, "executive_report", date.today().isoformat(), "generated", {"format": "pdf"})
    db.commit()
    return FileResponse(path, media_type="application/pdf", filename=Path(path).name)

def _csv_response(filename: str, headers: list[str], rows: list[list]):
    import csv, io
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    writer.writerows(rows)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{filename}"'})

@app.get("/executive-reports/portfolio.csv")
def executive_portfolio_csv(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    data = portfolio_analytics(db)
    rows=[]
    for row in data["largest_accounts"]:
        business=row["business"]
        state=""
        if business.locations:
            state=business.locations[0].state or ""
        rows.append([business.legal_name, business.industry or "", business.producer.full_name if business.producer else "", state, row["policy_count"], f"{row['premium']:.2f}", row["percent"]])
    audit(db, user.id, "executive_report", date.today().isoformat(), "exported", {"format":"portfolio_csv"}); db.commit()
    return _csv_response("commercialcore_portfolio.csv", ["Business","Industry","Producer","Primary state","Active policies","Annual premium","Portfolio percent"], rows)

@app.get("/executive-reports/staff.csv")
def executive_staff_csv(request: Request, db: Session = Depends(get_db)):
    user=require_user(request, db); data=staff_analytics(db)
    rows=[[r["user"].full_name,r["user"].role,r["open_tasks"],r["overdue_tasks"],r["due_week"],r["completed_30"],r["average_completion_days"] or "",r["activities_30"],r["open_reviews"],r["produced_accounts"]] for r in data["rows"]]
    audit(db,user.id,"executive_report",date.today().isoformat(),"exported",{"format":"staff_csv"}); db.commit()
    return _csv_response("commercialcore_staff_scorecard.csv", ["Staff member","Role","Open tasks","Overdue tasks","Due in 7 days","Completed 30 days","Average completion days","Activities 30 days","Open reviews","Producer accounts"], rows)

@app.get("/executive-reports/trends.csv")
def executive_trends_csv(request: Request, db: Session = Depends(get_db)):
    user=require_user(request, db); data=executive_analytics(db)
    rows=[["Premium effective date",r["label"],r["value"],""] for r in data["premium_trend"]]
    rows += [["Renewal pipeline",r["label"],r["premium"],r["count"]] for r in data["renewal_pipeline"]]
    audit(db,user.id,"executive_report",date.today().isoformat(),"exported",{"format":"trends_csv"}); db.commit()
    return _csv_response("commercialcore_trends.csv", ["Series","Period","Premium","Policy count"], rows)

@app.get("/businesses", response_class=HTMLResponse)
def businesses(request: Request, q: str = "", db: Session = Depends(get_db)):
    require_user(request, db)
    stmt = select(Business).order_by(Business.legal_name)
    if q:
        stmt = stmt.where(Business.legal_name.ilike(f"%{q}%"))
    rows = list(db.scalars(stmt))
    return render(request, "businesses.html", {"businesses": rows, "q": q}, db)

@app.get("/businesses/new", response_class=HTMLResponse)
def business_new(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    require_role(user, "administrator", "producer", "account_manager")
    users = list(db.scalars(select(User).where(User.active.is_(True)).order_by(User.full_name)))
    return render(request, "business_form.html", {"users": users}, db)

@app.post("/businesses/new")
def business_create(
    request: Request,
    legal_name: str = Form(...),
    dba_name: str = Form(""),
    industry: str = Form(""),
    renewal_month: str = Form(""),
    producer_id: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    require_role(user, "administrator", "producer", "account_manager")
    business = Business(
        legal_name=legal_name.strip(),
        dba_name=dba_name.strip() or None,
        industry=industry.strip() or None,
        renewal_month=int(renewal_month) if renewal_month else None,
        producer_id=int(producer_id) if producer_id else None,
    )
    db.add(business)
    db.flush()
    audit(db, user.id, "business", business.id, "created", {"legal_name": business.legal_name})
    db.commit()
    return RedirectResponse(f"/businesses/{business.id}", 303)

def load_business(db, business_id):
    stmt = select(Business).options(
        selectinload(Business.contacts),
        selectinload(Business.locations),
        selectinload(Business.producer),
        selectinload(Business.policies).selectinload(Policy.carrier_reference),
        selectinload(Business.policies).selectinload(Policy.exposures).selectinload(Exposure.entries),
        selectinload(Business.reviews).selectinload(ReviewItem.notes).selectinload(AgencyNote.author),
        selectinload(Business.account_notes).selectinload(AccountNote.author),
        selectinload(Business.review_packets).selectinload(ReviewPacket.creator),
        selectinload(Business.tasks).selectinload(Task.assignee),
        selectinload(Business.tasks).selectinload(Task.creator),
        selectinload(Business.activities).selectinload(Activity.owner),
        selectinload(Business.documents).selectinload(Document.uploader),
        selectinload(Business.recommendations).selectinload(Recommendation.linked_task),
        selectinload(Business.recommendations).selectinload(Recommendation.linked_packet),
    ).where(Business.id == business_id)
    business = db.scalar(stmt)
    if not business:
        raise HTTPException(404)
    return business

@app.get("/businesses/{business_id}", response_class=HTMLResponse)
def business_detail(request: Request, business_id: int, db: Session = Depends(get_db)):
    require_user(request, db)
    business = load_business(db, business_id)
    sync_recommendations(db, business)
    db.commit()
    business = load_business(db, business_id)
    active_recommendations = [r for r in business.recommendations if r.status in ["open", "task_created", "packet_added"]]
    priority_rank = {"high": 0, "medium": 1, "low": 2}
    active_recommendations.sort(key=lambda r: (priority_rank.get(r.priority, 9), r.created_at))
    recommendation_action_map = {r.id: recommendation_actions(r) for r in active_recommendations}
    latest_projections = {}
    for policy in business.policies:
        for exposure in policy.exposures:
            latest_projections[exposure.id] = db.scalar(select(Projection).where(Projection.exposure_id == exposure.id).order_by(Projection.created_at.desc()))
    reports = list(db.scalars(select(Report).where(Report.business_id == business_id).order_by(Report.generated_at.desc())))
    review_packets = list(db.scalars(select(ReviewPacket).options(selectinload(ReviewPacket.creator)).where(ReviewPacket.business_id == business_id).order_by(ReviewPacket.created_at.desc())))
    staff_users = list(db.scalars(select(User).where(User.active.is_(True)).order_by(User.full_name)))
    insights = business_detail_insights(db, business)
    audit_events = list(db.scalars(select(AuditEvent).where(
        ((AuditEvent.entity_type == "business") & (AuditEvent.entity_id == str(business_id))) |
        ((AuditEvent.entity_type == "report") & (AuditEvent.entity_id.in_([str(r.id) for r in reports] or ["-1"])))
    ).order_by(AuditEvent.created_at.desc()).limit(30)))
    timeline = []
    for activity in business.activities:
        timeline.append({"at": activity.occurred_at, "type": "activity", "title": activity.activity_type.title()+": "+activity.subject, "detail": activity.body or "", "by": activity.owner.full_name})
    for task in business.tasks:
        timeline.append({"at": task.created_at, "type": "task", "title": "Task: "+task.title, "detail": task.status.replace("_"," ").title()+" · "+task.assignee.full_name, "by": task.creator.full_name})
    for document in business.documents:
        timeline.append({"at": document.created_at, "type": "document", "title": "Document: "+document.title, "detail": document.original_name, "by": document.uploader.full_name})
    for note in business.account_notes:
        timeline.append({"at": note.created_at, "type": "note", "title": note.category.replace("_", " ").title(), "detail": note.body, "by": note.author.full_name})
    for review in business.reviews:
        timeline.append({"at": review.created_at, "type": "review", "title": review.title, "detail": review.evidence, "by": review.assignee.full_name if review.assignee else "Unassigned"})
    for report in reports:
        timeline.append({"at": report.generated_at, "type": "report", "title": "Report generated", "detail": report.status.title(), "by": "CommercialCore"})
    for event in audit_events:
        timeline.append({"at": event.created_at, "type": "activity", "title": event.action.replace("_", " ").title(), "detail": event.details, "by": event.actor.full_name if event.actor else "System"})
    timeline.sort(key=lambda x: x["at"], reverse=True)
    return render(request, "business_detail.html", {
        "business": business, "latest_projections": latest_projections, "reports": reports,
        "insights": insights, "timeline": timeline[:60], "review_packets": review_packets, "staff_users": staff_users,
        "recommendations": active_recommendations, "recommendation_action_map": recommendation_action_map,
    }, db)

@app.post("/businesses/{business_id}/contacts")
def add_contact(request: Request, business_id: int, name: str = Form(...), title: str = Form(""), email: str = Form(""), phone: str = Form(""), db: Session = Depends(get_db)):
    user = require_user(request, db)
    db.add(Contact(business_id=business_id, name=name, title=title or None, email=email or None, phone=phone or None))
    audit(db, user.id, "business", business_id, "contact_added", {"name": name})
    db.commit()
    return RedirectResponse(f"/businesses/{business_id}", 303)

@app.post("/businesses/{business_id}/notes")
def add_account_note(request: Request, business_id: int, body: str = Form(...), category: str = Form("general"), db: Session = Depends(get_db)):
    user = require_user(request, db)
    note = AccountNote(business_id=business_id, author_id=user.id, body=body.strip(), category=category)
    db.add(note)
    db.flush()
    audit(db, user.id, "business", business_id, "account_note_added", {"category": category})
    db.commit()
    return RedirectResponse(f"/businesses/{business_id}#timeline", 303)

@app.post("/policies/{policy_id}/carrier")
def save_policy_carrier(request: Request, policy_id: int, carrier_name: str = Form(...), contact_name: str = Form(""), contact_email: str = Form(""), contact_phone: str = Form(""), notes: str = Form(""), db: Session = Depends(get_db)):
    user = require_user(request, db)
    policy = db.get(Policy, policy_id)
    if not policy:
        raise HTTPException(404)
    carrier = db.scalar(select(PolicyCarrier).where(PolicyCarrier.policy_id == policy_id))
    if not carrier:
        carrier = PolicyCarrier(policy_id=policy_id, carrier_name=carrier_name.strip())
        db.add(carrier)
    carrier.carrier_name = carrier_name.strip()
    carrier.contact_name = contact_name.strip() or None
    carrier.contact_email = contact_email.strip() or None
    carrier.contact_phone = contact_phone.strip() or None
    carrier.notes = notes.strip() or None
    audit(db, user.id, "business", policy.business_id, "carrier_reference_updated", {"policy_id": policy_id, "carrier": carrier_name})
    db.commit()
    return RedirectResponse(f"/businesses/{policy.business_id}#policies", 303)

@app.post("/businesses/{business_id}/locations")
def add_location(request: Request, business_id: int, label: str = Form("Primary"), address1: str = Form(...), city: str = Form(...), state: str = Form(...), postal_code: str = Form(...), db: Session = Depends(get_db)):
    user = require_user(request, db)
    db.add(Location(business_id=business_id, label=label, address1=address1, city=city, state=state.upper(), postal_code=postal_code))
    audit(db, user.id, "business", business_id, "location_added", {"city": city, "state": state})
    db.commit()
    return RedirectResponse(f"/businesses/{business_id}", 303)

@app.post("/businesses/{business_id}/policies")
def add_policy(request: Request, business_id: int, line: str = Form(...), policy_number_ref: str = Form(""), effective_date: date = Form(...), expiration_date: date = Form(...), annual_premium: str = Form(""), notes: str = Form(""), db: Session = Depends(get_db)):
    user = require_user(request, db)
    if expiration_date <= effective_date:
        raise HTTPException(400, "Expiration must follow effective date.")
    policy = Policy(business_id=business_id, line=line, policy_number_ref=policy_number_ref or None, effective_date=effective_date, expiration_date=expiration_date, annual_premium=float(annual_premium) if annual_premium else None, notes=notes or None)
    db.add(policy)
    db.flush()
    audit(db, user.id, "policy", policy.id, "created", {"line": line})
    db.commit()
    return RedirectResponse(f"/businesses/{business_id}", 303)

@app.post("/policies/{policy_id}/exposures")
def add_exposure(request: Request, policy_id: int, exposure_type: str = Form(...), recorded_estimate: float = Form(...), cadence: str = Form(...), db: Session = Depends(get_db)):
    user = require_user(request, db)
    policy = db.get(Policy, policy_id)
    if not policy:
        raise HTTPException(404)
    exposure = Exposure(policy_id=policy_id, exposure_type=exposure_type, recorded_estimate=recorded_estimate, cadence=cadence)
    db.add(exposure)
    db.flush()
    audit(db, user.id, "exposure", exposure.id, "created", {"type": exposure_type, "cadence": cadence})
    db.commit()
    return RedirectResponse(f"/exposures/{exposure.id}", 303)

@app.get("/exposures/{exposure_id}", response_class=HTMLResponse)
def exposure_detail(request: Request, exposure_id: int, db: Session = Depends(get_db)):
    require_user(request, db)
    exposure = db.scalar(select(Exposure).options(
        selectinload(Exposure.policy).selectinload(Policy.business),
        selectinload(Exposure.entries).selectinload(ReportingEntry.creator),
        selectinload(Exposure.projections),
    ).where(Exposure.id == exposure_id))
    if not exposure:
        raise HTTPException(404)
    latest = db.scalar(select(Projection).where(Projection.exposure_id == exposure_id).order_by(Projection.created_at.desc()))
    insights = reporting_insights(db, exposure, latest)
    return render(request, "exposure_detail.html", {"exposure": exposure, "latest": latest, "insights": insights}, db)

@app.post("/exposures/{exposure_id}/entries")
def add_entry(request: Request, exposure_id: int, period_start: date = Form(...), period_end: date = Form(...), actual_value: float = Form(...), note: str = Form(""), db: Session = Depends(get_db)):
    user = require_user(request, db)
    exposure = db.get(Exposure, exposure_id)
    if not exposure:
        raise HTTPException(404)
    if period_end < period_start or actual_value < 0:
        raise HTTPException(400, "Invalid reporting period.")
    if overlap_exists(db, exposure_id, period_start, period_end):
        raise HTTPException(400, "This period overlaps an existing accepted entry.")
    entry = ReportingEntry(exposure_id=exposure_id, period_start=period_start, period_end=period_end, actual_value=actual_value, source="manual", note=note or None, created_by=user.id)
    db.add(entry)
    db.flush()
    audit(db, user.id, "reporting_entry", entry.id, "created", {"value": actual_value})
    calculate_projection(db, exposure)
    db.commit()
    return RedirectResponse(f"/exposures/{exposure_id}", 303)

@app.post("/exposures/{exposure_id}/import")
async def import_entries(request: Request, exposure_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    user = require_user(request, db)
    exposure = db.get(Exposure, exposure_id)
    if not exposure:
        raise HTTPException(404)
    content = await file.read()
    try:
        record = store_import(db, exposure, user.id, file.filename or "upload.csv", content)
        audit(db, user.id, "import_file", record.id, "processed", {"status": record.status, "rows": record.row_count})
        if record.row_count:
            calculate_projection(db, exposure)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc))
    return RedirectResponse(f"/exposures/{exposure_id}", 303)

@app.post("/exposures/{exposure_id}/recalculate")
def recalculate(request: Request, exposure_id: int, db: Session = Depends(get_db)):
    user = require_user(request, db)
    exposure = db.get(Exposure, exposure_id)
    if not exposure:
        raise HTTPException(404)
    projection = calculate_projection(db, exposure)
    audit(db, user.id, "projection", projection.id, "calculated", {"method": projection.method})
    db.commit()
    return RedirectResponse(f"/exposures/{exposure_id}", 303)

@app.get("/reviews", response_class=HTMLResponse)
def reviews(request: Request, status: str = "active", priority: str = "", owner: str = "", db: Session = Depends(get_db)):
    require_user(request, db)
    stmt = select(ReviewItem).options(selectinload(ReviewItem.business), selectinload(ReviewItem.assignee))
    if status == "active":
        stmt = stmt.where(ReviewItem.status != "closed")
    elif status in {"open", "in_progress", "closed"}:
        stmt = stmt.where(ReviewItem.status == status)
    if priority in {"high", "medium", "low"}:
        stmt = stmt.where(ReviewItem.priority == priority)
    if owner == "unassigned":
        stmt = stmt.where(ReviewItem.assigned_to.is_(None))
    elif owner.isdigit():
        stmt = stmt.where(ReviewItem.assigned_to == int(owner))
    rows = list(db.scalars(stmt.order_by(ReviewItem.status, ReviewItem.priority, ReviewItem.created_at.desc())))
    users = list(db.scalars(select(User).where(User.active.is_(True)).order_by(User.full_name)))
    summary = {
        "total": len(rows),
        "high": sum(1 for r in rows if r.priority == "high"),
        "unassigned": sum(1 for r in rows if r.assigned_to is None),
        "in_progress": sum(1 for r in rows if r.status == "in_progress"),
    }
    return render(request, "reviews.html", {"reviews": rows, "users": users, "filters": {"status": status, "priority": priority, "owner": owner}, "summary": summary}, db)

@app.get("/reviews/{review_id}", response_class=HTMLResponse)
def review_detail(request: Request, review_id: int, db: Session = Depends(get_db)):
    require_user(request, db)
    review = db.scalar(select(ReviewItem).options(
        selectinload(ReviewItem.business),
        selectinload(ReviewItem.exposure),
        selectinload(ReviewItem.notes).selectinload(AgencyNote.author),
        selectinload(ReviewItem.assignee),
    ).where(ReviewItem.id == review_id))
    users = list(db.scalars(select(User).where(User.active.is_(True)).order_by(User.full_name)))
    if not review:
        raise HTTPException(404)
    return render(request, "review_detail.html", {"review": review, "users": users}, db)

@app.post("/reviews/{review_id}/update")
def update_review(request: Request, review_id: int, status: str = Form(...), assigned_to: str = Form(""), disposition: str = Form(""), db: Session = Depends(get_db)):
    user = require_user(request, db)
    review = db.get(ReviewItem, review_id)
    if not review:
        raise HTTPException(404)
    if status == "closed" and not disposition:
        raise HTTPException(400, "A disposition is required to close a review.")
    review.status = status
    review.assigned_to = int(assigned_to) if assigned_to else None
    review.disposition = disposition or None
    review.closed_at = datetime.utcnow() if status == "closed" else None
    audit(db, user.id, "review_item", review.id, "updated", {"status": status, "disposition": disposition})
    db.commit()
    return RedirectResponse(f"/reviews/{review_id}", 303)

@app.post("/reviews/{review_id}/notes")
def add_note(request: Request, review_id: int, body: str = Form(...), db: Session = Depends(get_db)):
    user = require_user(request, db)
    note = AgencyNote(review_id=review_id, author_id=user.id, body=body.strip())
    db.add(note)
    db.flush()
    audit(db, user.id, "agency_note", note.id, "created", {"review_id": review_id})
    db.commit()
    return RedirectResponse(f"/reviews/{review_id}", 303)

@app.post("/businesses/{business_id}/reports")
def generate_report(request: Request, business_id: int, db: Session = Depends(get_db)):
    user = require_user(request, db)
    business = load_business(db, business_id)
    report = build_report(db, business, user.id)
    audit(db, user.id, "report", report.id, "generated", {"file": report.file_name})
    db.commit()
    return RedirectResponse(f"/businesses/{business_id}", 303)

@app.post("/reports/{report_id}/approve")
def approve_report(request: Request, report_id: int, db: Session = Depends(get_db)):
    user = require_user(request, db)
    require_role(user, "administrator", "producer")
    report = db.get(Report, report_id)
    if not report:
        raise HTTPException(404)
    report.status = "approved"
    report.approved_by = user.id
    report.approved_at = datetime.utcnow()
    audit(db, user.id, "report", report.id, "approved", {})
    db.commit()
    return RedirectResponse(f"/businesses/{report.business_id}", 303)

@app.get("/reports/{report_id}/download")
def download_report(request: Request, report_id: int, db: Session = Depends(get_db)):
    require_user(request, db)
    report = db.get(Report, report_id)
    if not report:
        raise HTTPException(404)
    path = REPORT_DIR / report.file_name
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="application/pdf", filename=report.file_name)


@app.get("/review-packets", response_class=HTMLResponse)
def review_packets_list(request: Request, db: Session = Depends(get_db)):
    require_user(request, db)
    packets = list(db.scalars(select(ReviewPacket).options(selectinload(ReviewPacket.business), selectinload(ReviewPacket.creator)).order_by(ReviewPacket.created_at.desc())))
    return render(request, "review_packets.html", {"packets": packets}, db)

@app.get("/businesses/{business_id}/review-builder", response_class=HTMLResponse)
def review_builder(request: Request, business_id: int, db: Session = Depends(get_db)):
    require_user(request, db)
    business = load_business(db, business_id)
    latest = db.scalar(select(ReviewPacket).where(ReviewPacket.business_id == business_id).order_by(ReviewPacket.created_at.desc()))
    defaults = {
        "title": "Annual Commercial Insurance Review",
        "prepared_for": next((c.name for c in business.contacts if c.is_primary), business.contacts[0].name if business.contacts else ""),
        "executive_summary": f"This review summarizes the current commercial insurance program and monitored business exposures for {business.legal_name}.",
        "discussion_points": "",
        "recommendations": "",
        "next_steps": "",
    }
    return render(request, "review_builder.html", {"business": business, "latest_packet": latest, "defaults": defaults}, db)

@app.post("/businesses/{business_id}/review-builder")
def create_review_packet(request: Request, business_id: int, title: str = Form(...), meeting_date: str = Form(""), prepared_for: str = Form(""), executive_summary: str = Form(""), discussion_points: str = Form(""), recommendations: str = Form(""), next_steps: str = Form(""), account_snapshot: str = Form(""), policy_summary: str = Form(""), exposure_analysis: str = Form(""), review_items: str = Form(""), contact_summary: str = Form(""), db: Session = Depends(get_db)):
    user = require_user(request, db)
    business = load_business(db, business_id)
    sections = {"account_snapshot": bool(account_snapshot), "policy_summary": bool(policy_summary), "exposure_analysis": bool(exposure_analysis), "review_items": bool(review_items), "contact_summary": bool(contact_summary)}
    packet = ReviewPacket(business_id=business_id, title=title.strip(), meeting_date=date.fromisoformat(meeting_date) if meeting_date else None, prepared_for=prepared_for.strip() or None, executive_summary=executive_summary.strip() or None, discussion_points=discussion_points.strip() or None, recommendations=recommendations.strip() or None, next_steps=next_steps.strip() or None, sections_json=json.dumps(sections), created_by=user.id)
    db.add(packet); db.flush()
    build_review_packet_pdf(db, business, packet)
    audit(db, user.id, "review_packet", packet.id, "generated", {"business_id": business_id, "sections": sections})
    db.commit()
    return RedirectResponse(f"/review-packets/{packet.id}", 303)

@app.get("/review-packets/{packet_id}", response_class=HTMLResponse)
def review_packet_detail(request: Request, packet_id: int, db: Session = Depends(get_db)):
    require_user(request, db)
    packet = db.scalar(select(ReviewPacket).options(selectinload(ReviewPacket.business), selectinload(ReviewPacket.creator), selectinload(ReviewPacket.approver)).where(ReviewPacket.id == packet_id))
    if not packet: raise HTTPException(404)
    return render(request, "review_packet_detail.html", {"packet": packet, "sections": json.loads(packet.sections_json or "{}")}, db)

@app.post("/review-packets/{packet_id}/approve")
def approve_review_packet(request: Request, packet_id: int, db: Session = Depends(get_db)):
    user = require_user(request, db); require_role(user, "administrator", "producer")
    packet = db.get(ReviewPacket, packet_id)
    if not packet: raise HTTPException(404)
    packet.status="approved"; packet.approved_by=user.id; packet.approved_at=datetime.utcnow()
    audit(db, user.id, "review_packet", packet.id, "approved", {})
    db.commit()
    return RedirectResponse(f"/review-packets/{packet.id}", 303)

@app.get("/review-packets/{packet_id}/download")
def download_review_packet(request: Request, packet_id: int, db: Session = Depends(get_db)):
    require_user(request, db)
    packet=db.get(ReviewPacket, packet_id)
    if not packet or not packet.file_name: raise HTTPException(404)
    path=REPORT_DIR / packet.file_name
    if not path.exists(): raise HTTPException(404)
    return FileResponse(path, media_type="application/pdf", filename=packet.file_name)



@app.get("/recommendations", response_class=HTMLResponse)
def recommendations_page(request: Request, status: str = "active", priority: str = "", db: Session = Depends(get_db)):
    require_user(request, db)
    for business in db.scalars(select(Business)):
        sync_recommendations(db, business)
    db.commit()
    stmt = select(Recommendation).options(
        selectinload(Recommendation.business), selectinload(Recommendation.linked_task), selectinload(Recommendation.linked_packet)
    )
    if status == "active":
        stmt = stmt.where(Recommendation.status.in_(["open", "task_created", "packet_added"]))
    elif status:
        stmt = stmt.where(Recommendation.status == status)
    if priority:
        stmt = stmt.where(Recommendation.priority == priority)
    rows = list(db.scalars(stmt.order_by(Recommendation.created_at.desc())))
    rank = {"high": 0, "medium": 1, "low": 2}
    rows.sort(key=lambda r: (rank.get(r.priority, 9), -r.created_at.timestamp()))
    return render(request, "recommendations.html", {
        "recommendations": rows,
        "action_map": {r.id: recommendation_actions(r) for r in rows},
        "filters": {"status": status, "priority": priority},
    }, db)

@app.post("/recommendations/{recommendation_id}/task")
def recommendation_create_task(request: Request, recommendation_id: int, assigned_to: str = Form(""), due_date: str = Form(""), db: Session = Depends(get_db)):
    user = require_user(request, db)
    rec = db.get(Recommendation, recommendation_id)
    if not rec: raise HTTPException(404)
    assignee = int(assigned_to) if assigned_to else (rec.business.producer_id or user.id)
    task = Task(
        business_id=rec.business_id, title=rec.title, description=rec.reason + "\n\nSuggested actions:\n- " + "\n- ".join(recommendation_actions(rec)),
        task_type="recommendation", priority=rec.priority, due_date=date.fromisoformat(due_date) if due_date else date.today() + timedelta(days=7),
        assigned_to=assignee, created_by=user.id,
    )
    db.add(task); db.flush()
    rec.linked_task_id = task.id; rec.status = "task_created"
    audit(db, user.id, "recommendation", rec.id, "task_created", {"task_id": task.id})
    db.commit()
    return RedirectResponse(request.headers.get("referer") or f"/businesses/{rec.business_id}", 303)

@app.post("/recommendations/{recommendation_id}/packet")
def recommendation_add_packet(request: Request, recommendation_id: int, db: Session = Depends(get_db)):
    user = require_user(request, db)
    rec = db.get(Recommendation, recommendation_id)
    if not rec: raise HTTPException(404)
    packet = db.scalar(select(ReviewPacket).where(
        ReviewPacket.business_id == rec.business_id, ReviewPacket.status == "draft"
    ).order_by(ReviewPacket.created_at.desc()))
    if packet is None:
        packet = ReviewPacket(business_id=rec.business_id, title="Annual Commercial Insurance Review", created_by=user.id)
        db.add(packet); db.flush()
    entry = f"{rec.title}: {rec.reason}"
    current = (packet.recommendations or "").strip()
    if entry not in current:
        packet.recommendations = (current + ("\n\n" if current else "") + entry).strip()
    rec.linked_packet_id = packet.id; rec.status = "packet_added"
    audit(db, user.id, "recommendation", rec.id, "added_to_packet", {"packet_id": packet.id})
    db.commit()
    return RedirectResponse(request.headers.get("referer") or f"/review-packets/{packet.id}", 303)

@app.post("/recommendations/{recommendation_id}/resolve")
def recommendation_resolve(request: Request, recommendation_id: int, action: str = Form(...), note: str = Form(""), db: Session = Depends(get_db)):
    user = require_user(request, db)
    rec = db.get(Recommendation, recommendation_id)
    if not rec: raise HTTPException(404)
    if action not in {"dismissed", "completed", "reopen"}: raise HTTPException(400)
    if action == "reopen":
        rec.status = "open"; rec.resolved_at = None; rec.resolved_by = None
    else:
        rec.status = action; rec.resolved_at = datetime.utcnow(); rec.resolved_by = user.id
    rec.resolution_note = note.strip() or None
    audit(db, user.id, "recommendation", rec.id, action, {"note": note.strip()})
    db.commit()
    return RedirectResponse(request.headers.get("referer") or "/recommendations", 303)

@app.get("/tasks", response_class=HTMLResponse)
def tasks_page(request: Request, status: str="active", priority: str="", owner: str="mine", db: Session=Depends(get_db)):
    user=require_user(request,db); stmt=select(Task).options(selectinload(Task.business),selectinload(Task.assignee),selectinload(Task.creator))
    if status=="active": stmt=stmt.where(Task.status!="completed")
    elif status: stmt=stmt.where(Task.status==status)
    if priority: stmt=stmt.where(Task.priority==priority)
    if owner=="mine": stmt=stmt.where(Task.assigned_to==user.id)
    elif owner.isdigit(): stmt=stmt.where(Task.assigned_to==int(owner))
    rows=list(db.scalars(stmt.order_by(Task.due_date.is_(None),Task.due_date,Task.created_at.desc())))
    users=list(db.scalars(select(User).where(User.active.is_(True)).order_by(User.full_name)))
    return render(request,"tasks.html",{"tasks":rows,"users":users,"filters":{"status":status,"priority":priority,"owner":owner},"today":date.today()},db)

@app.post("/tasks")
def task_create(request: Request,title:str=Form(...),description:str=Form(""),task_type:str=Form("follow_up"),priority:str=Form("medium"),due_date:str=Form(""),assigned_to:str=Form(""),business_id:str=Form(""),db:Session=Depends(get_db)):
    user=require_user(request,db); aid=int(assigned_to) if assigned_to else user.id
    if user.role not in ("administrator","producer","account_manager"): aid=user.id
    if not db.get(User,aid): raise HTTPException(400,"Invalid assignee")
    task=Task(title=title.strip(),description=description.strip() or None,task_type=task_type,priority=priority,due_date=date.fromisoformat(due_date) if due_date else None,assigned_to=aid,created_by=user.id,business_id=int(business_id) if business_id else None)
    db.add(task);db.flush();audit(db,user.id,"task",task.id,"created",{"assigned_to":aid});db.commit()
    return RedirectResponse(f"/businesses/{task.business_id}#crm" if task.business_id else "/tasks",303)

@app.post("/tasks/{task_id}/status")
def task_status(request:Request,task_id:int,status:str=Form(...),db:Session=Depends(get_db)):
    user=require_user(request,db);task=db.get(Task,task_id)
    if not task: raise HTTPException(404)
    if user.role not in ("administrator","producer","account_manager") and task.assigned_to!=user.id: raise HTTPException(403)
    if status not in ("open","in_progress","waiting","completed"): raise HTTPException(400)
    task.status=status;task.completed_at=datetime.utcnow() if status=="completed" else None;audit(db,user.id,"task",task.id,"status_changed",{"status":status});db.commit()
    return RedirectResponse(request.headers.get("referer") or "/tasks",303)

@app.get("/activities",response_class=HTMLResponse)
def activities_page(request:Request,activity_type:str="",owner:str="",db:Session=Depends(get_db)):
    require_user(request,db);stmt=select(Activity).options(selectinload(Activity.business),selectinload(Activity.owner)).order_by(Activity.occurred_at.desc())
    if activity_type: stmt=stmt.where(Activity.activity_type==activity_type)
    if owner.isdigit(): stmt=stmt.where(Activity.owner_id==int(owner))
    users=list(db.scalars(select(User).where(User.active.is_(True)).order_by(User.full_name)))
    return render(request,"activities.html",{"activities":list(db.scalars(stmt.limit(250))),"users":users,"activity_type":activity_type,"owner":owner},db)

@app.post("/activities")
def activity_create(request:Request,business_id:int=Form(...),activity_type:str=Form(...),subject:str=Form(...),body:str=Form(""),owner_id:str=Form(""),db:Session=Depends(get_db)):
    user=require_user(request,db);oid=int(owner_id) if owner_id and user.role in ("administrator","producer","account_manager") else user.id
    a=Activity(business_id=business_id,activity_type=activity_type,subject=subject.strip(),body=body.strip() or None,owner_id=oid,created_by=user.id)
    db.add(a);db.flush();audit(db,user.id,"activity",a.id,"created",{"business_id":business_id});db.commit();return RedirectResponse(f"/businesses/{business_id}#crm",303)

@app.post("/businesses/{business_id}/documents")
async def document_upload(request:Request,business_id:int,title:str=Form(...),category:str=Form("other"),upload:UploadFile=File(...),db:Session=Depends(get_db)):
    user=require_user(request,db);original=Path(upload.filename or "document").name;suffix=Path(original).suffix.lower()
    if suffix not in {".pdf",".doc",".docx",".xls",".xlsx",".csv",".jpg",".jpeg",".png",".txt"}: raise HTTPException(400,"Unsupported file type")
    content=await upload.read()
    if len(content)>15*1024*1024: raise HTTPException(400,"File exceeds 15 MB")
    stored=uuid.uuid4().hex+suffix;(UPLOAD_DIR/stored).write_bytes(content)
    doc=Document(business_id=business_id,title=title.strip(),category=category,original_name=original,stored_name=stored,content_type=upload.content_type,size_bytes=len(content),uploaded_by=user.id)
    db.add(doc);db.flush();audit(db,user.id,"document",doc.id,"uploaded",{"business_id":business_id});db.commit();return RedirectResponse(f"/businesses/{business_id}#documents",303)

@app.get("/documents/{document_id}/download")
def document_download(request:Request,document_id:int,db:Session=Depends(get_db)):
    require_user(request,db);doc=db.get(Document,document_id)
    if not doc or not (UPLOAD_DIR/doc.stored_name).exists(): raise HTTPException(404)
    return FileResponse(UPLOAD_DIR/doc.stored_name,media_type=doc.content_type or "application/octet-stream",filename=doc.original_name)

@app.post("/admin/users/{user_id}/toggle")
def toggle_user(request:Request,user_id:int,db:Session=Depends(get_db)):
    actor=require_user(request,db);require_role(actor,"administrator");target=db.get(User,user_id)
    if not target: raise HTTPException(404)
    if target.id==actor.id and target.active: raise HTTPException(400,"Cannot deactivate your own login")
    target.active=not target.active;audit(db,actor.id,"user",target.id,"activation_changed",{"active":target.active});db.commit();return RedirectResponse("/admin/users",303)

@app.post("/admin/users/{user_id}/password")
def reset_password(request:Request,user_id:int,password:str=Form(...),db:Session=Depends(get_db)):
    actor=require_user(request,db);require_role(actor,"administrator");target=db.get(User,user_id)
    if not target: raise HTTPException(404)
    if len(password)<8: raise HTTPException(400,"Password must be at least 8 characters")
    target.password_hash=hash_password(password);audit(db,actor.id,"user",target.id,"password_reset",{});db.commit();return RedirectResponse("/admin/users",303)

@app.get("/admin/users", response_class=HTMLResponse)
def admin_users(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    require_role(user, "administrator")
    users = list(db.scalars(select(User).order_by(User.full_name)))
    return render(request, "admin_users.html", {"users": users}, db)

@app.post("/admin/users")
def create_user(request: Request, username: str = Form(...), full_name: str = Form(...), password: str = Form(...), role: str = Form(...), db: Session = Depends(get_db)):
    actor = require_user(request, db)
    require_role(actor, "administrator")
    if db.scalar(select(User).where(User.username == username)):
        raise HTTPException(400, "Username already exists.")
    user = User(username=username.strip(), full_name=full_name.strip(), password_hash=hash_password(password), role=role)
    db.add(user)
    db.flush()
    audit(db, actor.id, "user", user.id, "created", {"username": username, "role": role})
    db.commit()
    return RedirectResponse("/admin/users", 303)

@app.get("/audit", response_class=HTMLResponse)
def audit_history(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    require_role(user, "administrator", "producer", "account_manager")
    events = list(db.scalars(select(AuditEvent).options(selectinload(AuditEvent.actor)).order_by(AuditEvent.created_at.desc()).limit(500)))
    return render(request, "audit.html", {"events": events}, db)

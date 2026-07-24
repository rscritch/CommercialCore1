from __future__ import annotations
from datetime import date, datetime
from pathlib import Path
from fastapi import FastAPI, Request, Form, Depends, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import select, func
from sqlalchemy.orm import Session, selectinload

from .config import SECRET_KEY, REPORT_DIR
from .db import Base, engine, get_db, SessionLocal
from .models import (
    User, Business, Contact, Location, Policy, Exposure, ReportingEntry,
    Projection, ReviewItem, AgencyNote, Report, AuditEvent
)
from .security import hash_password, verify_password, current_user, require_user, require_role
from .services import audit, overlap_exists, calculate_projection, store_import
from .reports import build_report

app = FastAPI(title="CommercialCore")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, same_site="lax")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

def initialize():
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if not db.scalar(select(User).where(User.username == "admin")):
            db.add(User(
                username="admin",
                full_name="Administrator",
                password_hash=hash_password("admin123"),
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
    return render(request, "dashboard.html", {
        "business_count": businesses,
        "open_reviews": open_reviews,
        "high_reviews": high_reviews,
        "latest_reviews": latest,
    }, db)

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
        selectinload(Business.policies).selectinload(Policy.exposures).selectinload(Exposure.entries),
        selectinload(Business.reviews).selectinload(ReviewItem.notes).selectinload(AgencyNote.author),
    ).where(Business.id == business_id)
    business = db.scalar(stmt)
    if not business:
        raise HTTPException(404)
    return business

@app.get("/businesses/{business_id}", response_class=HTMLResponse)
def business_detail(request: Request, business_id: int, db: Session = Depends(get_db)):
    require_user(request, db)
    business = load_business(db, business_id)
    latest_projections = {}
    for policy in business.policies:
        for exposure in policy.exposures:
            latest_projections[exposure.id] = db.scalar(select(Projection).where(Projection.exposure_id == exposure.id).order_by(Projection.created_at.desc()))
    reports = list(db.scalars(select(Report).where(Report.business_id == business_id).order_by(Report.generated_at.desc())))
    return render(request, "business_detail.html", {
        "business": business,
        "latest_projections": latest_projections,
        "reports": reports,
    }, db)

@app.post("/businesses/{business_id}/contacts")
def add_contact(request: Request, business_id: int, name: str = Form(...), title: str = Form(""), email: str = Form(""), phone: str = Form(""), db: Session = Depends(get_db)):
    user = require_user(request, db)
    db.add(Contact(business_id=business_id, name=name, title=title or None, email=email or None, phone=phone or None))
    audit(db, user.id, "business", business_id, "contact_added", {"name": name})
    db.commit()
    return RedirectResponse(f"/businesses/{business_id}", 303)

@app.post("/businesses/{business_id}/locations")
def add_location(request: Request, business_id: int, label: str = Form("Primary"), address1: str = Form(...), city: str = Form(...), state: str = Form(...), postal_code: str = Form(...), db: Session = Depends(get_db)):
    user = require_user(request, db)
    db.add(Location(business_id=business_id, label=label, address1=address1, city=city, state=state.upper(), postal_code=postal_code))
    audit(db, user.id, "business", business_id, "location_added", {"city": city, "state": state})
    db.commit()
    return RedirectResponse(f"/businesses/{business_id}", 303)

@app.post("/businesses/{business_id}/policies")
def add_policy(request: Request, business_id: int, line: str = Form(...), policy_number_ref: str = Form(""), effective_date: date = Form(...), expiration_date: date = Form(...), notes: str = Form(""), db: Session = Depends(get_db)):
    user = require_user(request, db)
    if expiration_date <= effective_date:
        raise HTTPException(400, "Expiration must follow effective date.")
    policy = Policy(business_id=business_id, line=line, policy_number_ref=policy_number_ref or None, effective_date=effective_date, expiration_date=expiration_date, notes=notes or None)
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
    return render(request, "exposure_detail.html", {"exposure": exposure, "latest": latest}, db)

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
def reviews(request: Request, db: Session = Depends(get_db)):
    require_user(request, db)
    rows = list(db.scalars(select(ReviewItem).options(selectinload(ReviewItem.business), selectinload(ReviewItem.assignee)).order_by(ReviewItem.status, ReviewItem.priority, ReviewItem.created_at.desc())))
    return render(request, "reviews.html", {"reviews": rows}, db)

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

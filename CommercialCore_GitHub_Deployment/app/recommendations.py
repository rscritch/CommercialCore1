from __future__ import annotations
from datetime import date, datetime, timedelta
import json
from sqlalchemy import select
from sqlalchemy.orm import Session
from .models import Business, Exposure, Policy, Projection, ReportingEntry, ReviewItem, Recommendation


def _latest_projection(db: Session, exposure_id: int):
    return db.scalar(select(Projection).where(Projection.exposure_id == exposure_id).order_by(Projection.created_at.desc()))


def recommendation_candidates(db: Session, business: Business, as_of: date | None = None) -> list[dict]:
    """Return explainable, rule-based recommended actions for one account."""
    as_of = as_of or date.today()
    rows: list[dict] = []

    open_reviews = list(db.scalars(select(ReviewItem).where(
        ReviewItem.business_id == business.id, ReviewItem.status != "closed"
    ).order_by(ReviewItem.priority, ReviewItem.created_at)))
    high_reviews = [r for r in open_reviews if r.priority == "high"]
    if high_reviews:
        rows.append({
            "code": "resolve_high_priority_reviews",
            "title": "Address high-priority review items",
            "reason": f"{len(high_reviews)} high-priority review item{'s are' if len(high_reviews) != 1 else ' is'} still open.",
            "priority": "high", "confidence": "high",
            "actions": ["Review the supporting evidence", "Assign an accountable staff member", "Document the disposition"],
            "source_type": "review", "source_id": high_reviews[0].id,
        })

    policies = list(db.scalars(select(Policy).where(Policy.business_id == business.id).order_by(Policy.expiration_date)))
    future = [p for p in policies if p.expiration_date >= as_of]
    if future:
        next_policy = min(future, key=lambda p: p.expiration_date)
        days = (next_policy.expiration_date - as_of).days
        if days <= 60:
            rows.append({
                "code": f"prepare_renewal_{next_policy.id}",
                "title": f"Prepare for the {next_policy.line} renewal",
                "reason": f"The policy expires in {days} days on {next_policy.expiration_date.strftime('%B %d, %Y')}.",
                "priority": "high" if days <= 30 else "medium", "confidence": "high",
                "actions": ["Confirm current exposures", "Resolve open review items", "Schedule the renewal discussion"],
                "source_type": "policy", "source_id": next_policy.id,
            })

    exposures = list(db.scalars(select(Exposure).join(Policy).where(
        Policy.business_id == business.id, Exposure.active.is_(True)
    )))
    overdue_count = 0
    material = []
    unscored = []
    for exposure in exposures:
        latest_entry = db.scalar(select(ReportingEntry).where(
            ReportingEntry.exposure_id == exposure.id, ReportingEntry.accepted.is_(True)
        ).order_by(ReportingEntry.period_end.desc()))
        grace = exposure.reporting_due_days or 7
        cadence_days = {"weekly": 7, "monthly": 31, "quarterly": 92}.get(exposure.cadence, 31)
        if latest_entry is None or (as_of - latest_entry.period_end).days > cadence_days + grace:
            overdue_count += 1
        projection = _latest_projection(db, exposure.id)
        if projection is None:
            unscored.append(exposure)
        elif abs(float(projection.variance_percent)) >= 10:
            material.append((exposure, projection))

    if overdue_count:
        rows.append({
            "code": "request_overdue_reporting",
            "title": "Request overdue exposure reporting",
            "reason": f"{overdue_count} monitored exposure{'s are' if overdue_count != 1 else ' is'} missing current reporting.",
            "priority": "high" if overdue_count >= 2 else "medium", "confidence": "high",
            "actions": ["Contact the client", "Request the missing reporting periods", "Recalculate projections after receipt"],
            "source_type": "business", "source_id": business.id,
        })

    if material:
        exposure, projection = max(material, key=lambda item: abs(float(item[1].variance_percent)))
        variance = float(projection.variance_percent)
        rows.append({
            "code": f"review_material_variance_{exposure.id}",
            "title": f"Review the {exposure.exposure_type.replace('_', ' ')} estimate",
            "reason": f"The current projection is {abs(variance):.1f}% {'above' if variance > 0 else 'below'} the recorded estimate.",
            "priority": "high" if abs(variance) >= 20 else "medium", "confidence": "high" if projection.confidence_score >= 75 else "medium",
            "actions": ["Verify the latest reported values", "Discuss expected year-end activity", "Update the insured estimate when appropriate"],
            "source_type": "exposure", "source_id": exposure.id,
        })

    if unscored:
        rows.append({
            "code": "complete_exposure_scoring",
            "title": "Complete exposure scoring",
            "reason": f"{len(unscored)} active exposure{'s do' if len(unscored) != 1 else ' does'} not yet have a calculated projection.",
            "priority": "medium", "confidence": "high",
            "actions": ["Enter or import reporting", "Calculate the projection", "Review the resulting score drivers"],
            "source_type": "business", "source_id": business.id,
        })

    if open_reviews and not high_reviews:
        rows.append({
            "code": "resolve_open_reviews",
            "title": "Resolve open review items",
            "reason": f"{len(open_reviews)} review item{'s remain' if len(open_reviews) != 1 else ' remains'} open.",
            "priority": "medium", "confidence": "high",
            "actions": ["Review the evidence", "Record the client discussion", "Close or escalate each item"],
            "source_type": "review", "source_id": open_reviews[0].id,
        })

    if not rows and exposures:
        rows.append({
            "code": "continue_monitoring",
            "title": "Continue routine monitoring",
            "reason": "No material reporting, variance, renewal, or review issue is currently detected.",
            "priority": "low", "confidence": "high",
            "actions": ["Collect the next scheduled report", "Watch for material changes", "Prepare for the next renewal milestone"],
            "source_type": "business", "source_id": business.id,
        })
    elif not rows:
        rows.append({
            "code": "complete_account_setup",
            "title": "Complete the account setup",
            "reason": "The business does not yet have an active monitored exposure.",
            "priority": "medium", "confidence": "high",
            "actions": ["Add policy information", "Add monitored exposures", "Enter initial reporting"],
            "source_type": "business", "source_id": business.id,
        })
    return rows


def sync_recommendations(db: Session, business: Business, as_of: date | None = None) -> list[Recommendation]:
    candidates = recommendation_candidates(db, business, as_of)
    existing = {r.code: r for r in db.scalars(select(Recommendation).where(
        Recommendation.business_id == business.id
    ))}
    active = {code: rec for code, rec in existing.items() if rec.status in ["open", "task_created", "packet_added"]}
    detected_codes = set()
    for candidate in candidates:
        detected_codes.add(candidate["code"])
        rec = existing.get(candidate["code"])
        if rec is None:
            rec = Recommendation(business_id=business.id, code=candidate["code"], status="open")
            db.add(rec)
            existing[candidate["code"]] = rec
        rec.title = candidate["title"]
        rec.reason = candidate["reason"]
        rec.priority = candidate["priority"]
        rec.confidence = candidate["confidence"]
        rec.suggested_actions_json = json.dumps(candidate["actions"])
        rec.source_type = candidate["source_type"]
        rec.source_id = candidate["source_id"]
        rec.last_detected_at = datetime.utcnow()
    for code, rec in active.items():
        if code not in detected_codes and rec.status == "open":
            rec.status = "completed"
            rec.resolved_at = datetime.utcnow()
            rec.resolution_note = "Condition no longer detected during recommendation refresh."
    db.flush()
    return list(db.scalars(select(Recommendation).where(
        Recommendation.business_id == business.id,
        Recommendation.status.in_(["open", "task_created", "packet_added"]),
    ).order_by(Recommendation.priority, Recommendation.created_at)))


def actions(rec: Recommendation) -> list[str]:
    try:
        return json.loads(rec.suggested_actions_json or "[]")
    except json.JSONDecodeError:
        return []

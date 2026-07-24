from datetime import date
import json

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from .models import Exposure, ReportingEntry, Projection, ReviewItem, Business, Policy
from .services import accepted_entries, policy_days, elapsed_days
from .intelligence import score_band, WEIGHTS, SCORING_VERSION
import re

# Transparent cumulative payroll curves used only as a fourth reporting comparison.
WC_CLASS_CURVES = {
    "8810": [0.083, 0.166, 0.249, 0.332, 0.415, 0.498, 0.581, 0.664, 0.747, 0.830, 0.915, 1.000],
    "0042": [0.045, 0.095, 0.165, 0.260, 0.380, 0.505, 0.630, 0.750, 0.850, 0.925, 0.975, 1.000],
    "5645": [0.060, 0.150, 0.205, 0.325, 0.400, 0.510, 0.575, 0.705, 0.785, 0.880, 0.935, 1.000],
    "7219": [0.090, 0.175, 0.260, 0.342, 0.424, 0.504, 0.584, 0.664, 0.743, 0.822, 0.901, 1.000],
}
DEFAULT_WC_CURVE = [0.083, 0.166, 0.249, 0.332, 0.415, 0.498, 0.581, 0.664, 0.747, 0.830, 0.915, 1.000]

def _wc_class_code(exposure: Exposure) -> str | None:
    match = re.search(r"(?:class\s*)?(\d{4})", exposure.exposure_type or "", re.IGNORECASE)
    if match:
        return match.group(1)
    match = re.search(r"(?:class(?:\s*code)?\s*)?(\d{4})", exposure.policy.notes or "", re.IGNORECASE)
    return match.group(1) if match else None

def _class_code_projection(exposure: Exposure, current_total: float, current_rows: list[ReportingEntry]) -> tuple[float | None, str | None]:
    if not current_total or not current_rows:
        return None, None
    class_code = _wc_class_code(exposure)
    curve = WC_CLASS_CURVES.get(class_code, DEFAULT_WC_CURVE)
    latest_month = max(row.period_end.month for row in current_rows)
    cumulative_share = curve[max(0, min(latest_month, 12) - 1)]
    return (current_total / cumulative_share if cumulative_share else None), class_code


def reporting_insights(db: Session, exposure: Exposure, projection: Projection | None, as_of: date | None = None) -> dict:
    """Build transparent score explanations and graph-ready reporting data."""
    as_of = as_of or date.today()
    entries = accepted_entries(db, exposure.id)
    policy_start = exposure.policy.effective_date
    policy_end = exposure.policy.expiration_date
    current_end = min(as_of, policy_end)
    current = [
        e for e in entries
        if e.period_start >= policy_start and e.period_end <= current_end
    ]
    total_days = policy_days(exposure)
    elapsed = max(elapsed_days(exposure, as_of), 1)
    current_total = sum(float(e.actual_value) for e in current)
    estimate = float(exposure.recorded_estimate)

    expected_annual = {"weekly": 52, "monthly": 12, "quarterly": 4}.get(exposure.cadence, 12)
    elapsed_share = min(elapsed / total_days, 1)
    expected_to_date = max(round(expected_annual * elapsed_share), 1)
    received = len(current)
    completeness_ratio = min(received / expected_to_date, 1)
    completeness_score = round(completeness_ratio * 100)

    latest_period_end = max((e.period_end for e in current), default=None)
    days_late = 0
    if latest_period_end:
        days_late = max((as_of - latest_period_end).days - exposure.reporting_due_days, 0)
    freshness_ratio = max(0, 1 - days_late / 30)
    freshness_score = round(freshness_ratio * 100)

    history_by_year: dict[int, list[ReportingEntry]] = {}
    for entry in entries:
        history_by_year.setdefault(entry.period_end.year, []).append(entry)
    minimum_complete = {"weekly": 45, "monthly": 10, "quarterly": 3}.get(exposure.cadence, 10)
    complete_years = sorted([year for year, rows in history_by_year.items() if year < policy_start.year and len(rows) >= minimum_complete])
    history_score = 100 if len(complete_years) >= 2 else 80 if len(complete_years) == 1 else 55

    straight_line = current_total / elapsed * total_days if current_total else estimate
    prior_year_pace = None
    seasonal = None
    if complete_years and current:
        year = complete_years[-1]
        rows = sorted(history_by_year[year], key=lambda e: e.period_start)
        total = sum(float(r.actual_value) for r in rows)
        comparable = sum(float(r.actual_value) for r in rows[:min(len(current), len(rows))])
        if comparable > 0:
            prior_year_pace = current_total * (total / comparable)
    if len(complete_years) >= 2 and current:
        ratios = []
        for year in complete_years[-3:]:
            rows = sorted(history_by_year[year], key=lambda e: e.period_start)
            total = sum(float(r.actual_value) for r in rows)
            comparable = sum(float(r.actual_value) for r in rows[:min(len(current), len(rows))])
            if comparable > 0:
                ratios.append(total / comparable)
        if ratios:
            seasonal = current_total * (sum(ratios) / len(ratios))

    class_code_projection, class_code = _class_code_projection(exposure, current_total, current)

    method_values = [
        {"method": "Straight line", "value": round(straight_line, 2), "selected": bool(projection and projection.method == "straight_line")},
    ]
    if prior_year_pace is not None:
        method_values.append({"method": "Prior-year pace", "value": round(prior_year_pace, 2), "selected": bool(projection and projection.method == "prior_year_pace")})
    if seasonal is not None:
        method_values.append({"method": "Seasonal", "value": round(seasonal, 2), "selected": bool(projection and projection.method == "seasonal")})
    if class_code_projection is not None:
        method_values.append({
            "method": f"Class-code benchmark ({class_code})" if class_code else "Class-code benchmark",
            "value": round(class_code_projection, 2),
            "selected": False,
            "benchmark": True,
        })

    cumulative = []
    running = 0.0
    for entry in sorted(current, key=lambda e: e.period_end):
        running += float(entry.actual_value)
        days = max((entry.period_end - policy_start).days + 1, 1)
        estimate_pace = estimate * min(days / total_days, 1)
        cumulative.append({
            "label": entry.period_end.strftime("%b %Y") if exposure.cadence != "weekly" else entry.period_end.strftime("%b %d"),
            "actual": round(running, 2),
            "estimatePace": round(estimate_pace, 2),
        })

    annual_totals = []
    for year in sorted(history_by_year):
        rows = history_by_year[year]
        total = sum(float(r.actual_value) for r in rows)
        if year == policy_start.year and projection:
            annual_totals.append({"year": f"{year} projected", "value": round(float(projection.projected_total), 2), "projected": True})
        elif year < policy_start.year:
            annual_totals.append({"year": str(year), "value": round(total, 2), "projected": False})
    if projection and not any(row["projected"] for row in annual_totals):
        annual_totals.append({"year": f"{policy_start.year} projected", "value": round(float(projection.projected_total), 2), "projected": True})
    annual_totals = annual_totals[-4:]

    accuracy = projection.accuracy_score if projection else None
    confidence = projection.confidence_score if projection else None
    core_index = projection.core_index if projection else None
    variance = float(projection.variance_percent) if projection else None
    score_details = {}
    if projection and projection.score_details:
        try:
            score_details = json.loads(projection.score_details)
        except (TypeError, ValueError):
            score_details = {}
    components = score_details.get("components", [])
    scoring_version = projection.scoring_version if projection and projection.scoring_version else "1.0"

    accuracy_reasons = []
    if projection:
        accuracy_reasons.append(f"Recorded estimate is ${estimate:,.0f} and the selected projection is ${float(projection.projected_total):,.0f}.")
        accuracy_reasons.append(f"The projected variance is {variance:+.1f}% from the recorded estimate.")
        if abs(variance) < 5:
            accuracy_reasons.append("The projection remains closely aligned with the recorded estimate.")
        elif abs(variance) < 10:
            accuracy_reasons.append("The difference is large enough to monitor before renewal.")
        else:
            accuracy_reasons.append("The difference exceeds the material review threshold used by CommercialCore.")

    confidence_reasons = [
        f"{received} of approximately {expected_to_date} expected {exposure.cadence} reports have been received to date.",
        "Reporting is current." if days_late == 0 else f"The latest accepted period is approximately {days_late} days beyond the reporting grace period.",
        f"Historical support score is {history_score}/100 based on {len(complete_years)} complete comparable prior year(s).",
    ]

    return {
        "current_total": round(current_total, 2),
        "received": received,
        "expected_to_date": expected_to_date,
        "completeness_score": completeness_score,
        "freshness_score": freshness_score,
        "history_score": history_score,
        "days_late": days_late,
        "accuracy": accuracy,
        "confidence": confidence,
        "core_index": core_index,
        "accuracy_band": score_band(accuracy),
        "confidence_band": score_band(confidence),
        "core_band": score_band(core_index),
        "accuracy_reasons": accuracy_reasons,
        "confidence_reasons": confidence_reasons,
        "core_formula": score_details.get("formula", "Exposure Accuracy × 60% + Reporting Confidence × 40%"),
        "score_components": components,
        "scoring_version": scoring_version,
        "score_strengths": score_details.get("strengths", []),
        "score_concerns": score_details.get("concerns", []),
        "cumulative": cumulative,
        "annual_totals": annual_totals,
        "projection_methods": method_values,
    }

def portfolio_insights(db: Session) -> dict:
    """Build a transparent, business-level health summary without storing derived values."""
    businesses = list(db.scalars(select(Business).order_by(Business.legal_name)))
    rows = []
    index_values = []
    confidence_values = []
    accuracy_values = []

    for business in businesses:
        exposures = list(db.scalars(
            select(Exposure)
            .join(Policy, Exposure.policy_id == Policy.id)
            .where(Policy.business_id == business.id, Exposure.active.is_(True))
        ))
        projections = []
        missing_exposures = 0
        for exposure in exposures:
            latest = db.scalar(
                select(Projection)
                .where(Projection.exposure_id == exposure.id)
                .order_by(Projection.created_at.desc())
            )
            if latest:
                projections.append(latest)
            else:
                missing_exposures += 1

        open_reviews = db.scalar(
            select(func.count()).select_from(ReviewItem).where(
                ReviewItem.business_id == business.id,
                ReviewItem.status != "closed",
            )
        ) or 0
        high_reviews = db.scalar(
            select(func.count()).select_from(ReviewItem).where(
                ReviewItem.business_id == business.id,
                ReviewItem.status != "closed",
                ReviewItem.priority == "high",
            )
        ) or 0

        if projections:
            avg_index = round(sum(p.core_index for p in projections) / len(projections))
            avg_accuracy = round(sum(p.accuracy_score for p in projections) / len(projections))
            avg_confidence = round(sum(p.confidence_score for p in projections) / len(projections))
            index_values.append(avg_index)
            accuracy_values.append(avg_accuracy)
            confidence_values.append(avg_confidence)
        else:
            avg_index = avg_accuracy = avg_confidence = None

        if high_reviews:
            health = "review"
            next_action = "Address high-priority review"
        elif open_reviews:
            health = "watch"
            next_action = "Work open review items"
        elif missing_exposures:
            health = "watch"
            next_action = "Add reporting or calculate projections"
        elif avg_index is None:
            health = "unscored"
            next_action = "Set up monitored exposures"
        elif avg_index >= 85:
            health = "healthy"
            next_action = "Continue monitoring"
        elif avg_index >= 70:
            health = "watch"
            next_action = "Review score drivers"
        else:
            health = "review"
            next_action = "Review exposure estimates"

        rows.append({
            "business": business,
            "exposure_count": len(exposures),
            "missing_exposures": missing_exposures,
            "open_reviews": open_reviews,
            "high_reviews": high_reviews,
            "core_index": avg_index,
            "accuracy": avg_accuracy,
            "confidence": avg_confidence,
            "health": health,
            "next_action": next_action,
        })

    rank = {"review": 0, "watch": 1, "unscored": 2, "healthy": 3}
    rows.sort(key=lambda row: (rank[row["health"]], -(row["high_reviews"] or 0), row["business"].legal_name.lower()))

    return {
        "rows": rows,
        "portfolio_index": round(sum(index_values) / len(index_values)) if index_values else None,
        "portfolio_accuracy": round(sum(accuracy_values) / len(accuracy_values)) if accuracy_values else None,
        "portfolio_confidence": round(sum(confidence_values) / len(confidence_values)) if confidence_values else None,
        "healthy_count": sum(1 for row in rows if row["health"] == "healthy"),
        "watch_count": sum(1 for row in rows if row["health"] == "watch"),
        "review_count": sum(1 for row in rows if row["health"] == "review"),
        "unscored_count": sum(1 for row in rows if row["health"] == "unscored"),
    }

def executive_dashboard_insights(db: Session, as_of: date | None = None) -> dict:
    """Portfolio operations layer for renewals, reporting due dates, and exposure movement."""
    from datetime import timedelta

    as_of = as_of or date.today()
    businesses = list(db.scalars(select(Business).order_by(Business.legal_name)))
    policies = list(db.scalars(
        select(Policy)
        .where(Policy.expiration_date >= as_of)
        .order_by(Policy.expiration_date, Policy.business_id)
    ))

    renewal_rows = []
    renewal_buckets = {"0_30": 0, "31_60": 0, "61_90": 0, "over_90": 0}
    for policy in policies:
        days = (policy.expiration_date - as_of).days
        if days <= 30:
            bucket = "0_30"
        elif days <= 60:
            bucket = "31_60"
        elif days <= 90:
            bucket = "61_90"
        else:
            bucket = "over_90"
        renewal_buckets[bucket] += 1
        if days <= 120:
            renewal_rows.append({
                "policy": policy,
                "business": policy.business,
                "days": days,
                "bucket": bucket,
                "urgency": "critical" if days <= 30 else "watch" if days <= 60 else "normal",
            })

    cadence_days = {"weekly": 7, "monthly": 30, "quarterly": 91}
    reporting_rows = []
    reporting_summary = {"overdue": 0, "due_soon": 0, "current": 0, "not_started": 0}
    exposures = list(db.scalars(
        select(Exposure)
        .join(Policy, Exposure.policy_id == Policy.id)
        .where(Exposure.active.is_(True), Policy.expiration_date >= as_of)
        .order_by(Policy.business_id, Exposure.exposure_type)
    ))
    for exposure in exposures:
        latest_entry = db.scalar(
            select(ReportingEntry)
            .where(ReportingEntry.exposure_id == exposure.id, ReportingEntry.accepted.is_(True))
            .order_by(ReportingEntry.period_end.desc())
        )
        cadence = cadence_days.get(exposure.cadence, 30)
        if latest_entry:
            next_period_end = latest_entry.period_end + timedelta(days=cadence)
            due_date = next_period_end + timedelta(days=exposure.reporting_due_days)
            days_until_due = (due_date - as_of).days
            if days_until_due < 0:
                status = "overdue"
            elif days_until_due <= 7:
                status = "due_soon"
            else:
                status = "current"
        else:
            due_date = exposure.policy.effective_date + timedelta(days=cadence + exposure.reporting_due_days)
            days_until_due = (due_date - as_of).days
            status = "not_started" if days_until_due >= 0 else "overdue"
        reporting_summary[status] += 1
        if status in {"overdue", "due_soon", "not_started"}:
            reporting_rows.append({
                "exposure": exposure,
                "business": exposure.policy.business,
                "policy": exposure.policy,
                "latest_entry": latest_entry,
                "due_date": due_date,
                "days_until_due": days_until_due,
                "status": status,
            })

    reporting_rank = {"overdue": 0, "due_soon": 1, "not_started": 2}
    reporting_rows.sort(key=lambda row: (reporting_rank[row["status"]], row["due_date"], row["business"].legal_name.lower()))

    change_rows = []
    material_changes = 0
    for exposure in exposures:
        projections = list(db.scalars(
            select(Projection)
            .where(Projection.exposure_id == exposure.id)
            .order_by(Projection.created_at.desc())
            .limit(2)
        ))
        if not projections:
            continue
        latest = projections[0]
        estimate = float(exposure.recorded_estimate)
        current_value = float(latest.projected_total)
        current_variance = float(latest.variance_percent)
        previous_value = float(projections[1].projected_total) if len(projections) > 1 else None
        movement = ((current_value - previous_value) / previous_value * 100) if previous_value else None
        material = abs(current_variance) >= 10 or (movement is not None and abs(movement) >= 5)
        if material:
            material_changes += 1
        if material or abs(current_variance) >= 5:
            change_rows.append({
                "exposure": exposure,
                "business": exposure.policy.business,
                "latest": latest,
                "estimate": estimate,
                "projected": current_value,
                "variance": current_variance,
                "movement": movement,
                "material": material,
                "direction": "up" if current_variance > 0 else "down" if current_variance < 0 else "flat",
            })
    change_rows.sort(key=lambda row: (not row["material"], -abs(row["variance"]), row["business"].legal_name.lower()))

    review_counts = {
        "high": db.scalar(select(func.count()).select_from(ReviewItem).where(ReviewItem.status != "closed", ReviewItem.priority == "high")) or 0,
        "medium": db.scalar(select(func.count()).select_from(ReviewItem).where(ReviewItem.status != "closed", ReviewItem.priority == "medium")) or 0,
        "low": db.scalar(select(func.count()).select_from(ReviewItem).where(ReviewItem.status != "closed", ReviewItem.priority == "low")) or 0,
        "unassigned": db.scalar(select(func.count()).select_from(ReviewItem).where(ReviewItem.status != "closed", ReviewItem.assigned_to.is_(None))) or 0,
    }

    action_count = review_counts["high"] + reporting_summary["overdue"] + renewal_buckets["0_30"] + material_changes
    return {
        "as_of": as_of,
        "business_count": len(businesses),
        "active_policy_count": len(policies),
        "monitored_exposure_count": len(exposures),
        "renewal_buckets": renewal_buckets,
        "renewals": renewal_rows[:12],
        "reporting_summary": reporting_summary,
        "reporting_due": reporting_rows[:12],
        "exposure_changes": change_rows[:12],
        "material_changes": material_changes,
        "review_counts": review_counts,
        "action_count": action_count,
    }


def business_detail_insights(db: Session, business: Business, as_of: date | None = None) -> dict:
    """Build the account-level dashboard without changing historical records."""
    as_of = as_of or date.today()
    exposure_rows = []
    projections = []
    overdue = 0
    due_soon = 0
    for policy in business.policies:
        for exposure in policy.exposures:
            projection = db.scalar(select(Projection).where(Projection.exposure_id == exposure.id).order_by(Projection.created_at.desc()))
            entries = accepted_entries(db, exposure.id)
            latest_end = max((entry.period_end for entry in entries), default=None)
            days_since = (as_of - latest_end).days if latest_end else None
            cadence_days = {"weekly": 7, "monthly": 31, "quarterly": 92}.get(exposure.cadence, 31)
            status = "current"
            if latest_end is None:
                status = "missing"
                overdue += 1
            elif days_since > cadence_days + exposure.reporting_due_days:
                status = "overdue"
                overdue += 1
            elif days_since > cadence_days:
                status = "due_soon"
                due_soon += 1
            if projection:
                projections.append(projection)
            exposure_rows.append({
                "policy": policy, "exposure": exposure, "projection": projection,
                "latest_end": latest_end, "reporting_status": status,
                "days_since": days_since,
            })

    avg_index = round(sum(p.core_index for p in projections) / len(projections)) if projections else None
    avg_accuracy = round(sum(p.accuracy_score for p in projections) / len(projections)) if projections else None
    avg_confidence = round(sum(p.confidence_score for p in projections) / len(projections)) if projections else None
    open_reviews = [r for r in business.reviews if r.status != "closed"]
    high_reviews = [r for r in open_reviews if r.priority == "high"]
    future_policies = [p for p in business.policies if p.expiration_date >= as_of]
    next_policy = min(future_policies, key=lambda p: p.expiration_date, default=None)
    days_to_renewal = (next_policy.expiration_date - as_of).days if next_policy else None
    if high_reviews or (avg_index is not None and avg_index < 70):
        health = "review"
    elif open_reviews or overdue or (avg_index is not None and avg_index < 85):
        health = "watch"
    elif avg_index is None:
        health = "unscored"
    else:
        health = "healthy"

    estimate_projection = []
    score_chart = []
    for row in exposure_rows:
        e, pr = row["exposure"], row["projection"]
        label = f"{row['policy'].line}: {e.exposure_type.replace('_', ' ').title()}"
        estimate_projection.append({"label": label, "estimate": float(e.recorded_estimate), "projection": float(pr.projected_total) if pr else 0})
        if pr:
            score_chart.append({"label": label, "index": pr.core_index, "accuracy": pr.accuracy_score, "confidence": pr.confidence_score})

    renewal_rows = []
    for policy in sorted(business.policies, key=lambda p: p.expiration_date):
        days = (policy.expiration_date - as_of).days
        renewal_rows.append({"policy": policy, "days": days, "status": "expired" if days < 0 else "critical" if days <= 30 else "watch" if days <= 90 else "normal"})

    # Phase 7.1: transparent business intelligence narrative and score drivers.
    drivers = []
    strengths = []
    concerns = []

    if avg_index is None:
        concerns.append("No calculated exposure projections are available yet, so the account cannot be fully scored.")
        drivers.append({"label": "Scoring readiness", "value": "Not ready", "tone": "neutral", "detail": "Add reporting and calculate at least one exposure projection."})
    else:
        drivers.append({"label": "CommercialCore Index", "value": str(avg_index), "tone": "healthy" if avg_index >= 85 else "watch" if avg_index >= 70 else "review", "detail": "Average index across the account's active calculated exposures."})
        if avg_index >= 85:
            strengths.append(f"The account's CommercialCore Index is {avg_index}, indicating generally strong account health.")
        elif avg_index >= 70:
            concerns.append(f"The CommercialCore Index is {avg_index}, which places the account in the watch range.")
        else:
            concerns.append(f"The CommercialCore Index is {avg_index}, which is below the review threshold.")

    if avg_accuracy is not None:
        drivers.append({"label": "Exposure accuracy", "value": str(avg_accuracy), "tone": "healthy" if avg_accuracy >= 90 else "watch" if avg_accuracy >= 75 else "review", "detail": "Measures how closely projected exposures align with recorded policy estimates."})
        if avg_accuracy >= 90:
            strengths.append("Current exposure projections remain closely aligned with recorded estimates.")
        elif avg_accuracy < 75:
            concerns.append("One or more exposure projections differ materially from recorded estimates.")

    if avg_confidence is not None:
        drivers.append({"label": "Reporting confidence", "value": str(avg_confidence), "tone": "healthy" if avg_confidence >= 90 else "watch" if avg_confidence >= 75 else "review", "detail": "Reflects reporting completeness, freshness, and historical support."})
        if avg_confidence >= 90:
            strengths.append("Reporting is complete and current enough to support a high-confidence projection.")
        elif avg_confidence < 75:
            concerns.append("Reporting quality or timeliness is reducing confidence in the account projection.")

    if overdue:
        concerns.append(f"{overdue} monitored exposure{' is' if overdue == 1 else 's are'} overdue for reporting.")
        drivers.append({"label": "Overdue reporting", "value": str(overdue), "tone": "review", "detail": "Reporting follow-up is required before the account can be considered current."})
    elif due_soon:
        drivers.append({"label": "Reporting due soon", "value": str(due_soon), "tone": "watch", "detail": "Upcoming reporting should be collected to keep projections current."})
    elif exposure_rows:
        strengths.append("No monitored exposure is currently overdue for reporting.")

    if high_reviews:
        concerns.append(f"{len(high_reviews)} high-priority review item{' requires' if len(high_reviews) == 1 else 's require'} attention.")
        drivers.append({"label": "High-priority reviews", "value": str(len(high_reviews)), "tone": "review", "detail": "Open high-priority items are the strongest negative account-health driver."})
    elif open_reviews:
        concerns.append(f"{len(open_reviews)} open review item{' remains' if len(open_reviews) == 1 else 's remain'} to be resolved.")
        drivers.append({"label": "Open reviews", "value": str(len(open_reviews)), "tone": "watch", "detail": "Open review items should be resolved or documented."})
    else:
        strengths.append("There are no open review items on the account.")

    if days_to_renewal is not None:
        tone = "review" if days_to_renewal <= 30 else "watch" if days_to_renewal <= 90 else "healthy"
        drivers.append({"label": "Renewal readiness", "value": f"{days_to_renewal} days", "tone": tone, "detail": f"The next policy renewal is {next_policy.expiration_date:%B %d, %Y}."})
        if days_to_renewal <= 30:
            concerns.append("The next renewal is within 30 days and should be treated as time-sensitive.")

    material_rows = []
    for row in exposure_rows:
        pr = row["projection"]
        if not pr:
            continue
        variance = float(pr.variance_percent)
        if abs(variance) >= 10:
            material_rows.append((row, variance))
    material_rows.sort(key=lambda item: abs(item[1]), reverse=True)
    if material_rows:
        row, variance = material_rows[0]
        label = row["exposure"].exposure_type.replace("_", " ").title()
        direction = "above" if variance > 0 else "below"
        concerns.append(f"{label} is projected {abs(variance):.1f}% {direction} the recorded estimate.")

    if high_reviews:
        recommendation = "Address the high-priority review item before completing other routine account work."
        recommendation_code = "review_high_priority"
    elif overdue:
        recommendation = "Request the overdue exposure reporting and recalculate the affected projection."
        recommendation_code = "collect_reporting"
    elif material_rows:
        row, variance = material_rows[0]
        label = row["exposure"].exposure_type.replace("_", " ").title()
        recommendation = f"Review the {label.lower()} estimate with the client because the current projection differs by {abs(variance):.1f}%."
        recommendation_code = "review_estimate"
    elif days_to_renewal is not None and days_to_renewal <= 60:
        recommendation = "Schedule the renewal discussion and confirm exposures, carrier information, and open recommendations."
        recommendation_code = "prepare_renewal"
    elif open_reviews:
        recommendation = "Resolve or document the remaining open review items."
        recommendation_code = "close_reviews"
    elif avg_index is None:
        recommendation = "Complete exposure setup, enter reporting, and calculate the first projection."
        recommendation_code = "complete_setup"
    else:
        recommendation = "Continue routine monitoring and collect the next scheduled exposure report."
        recommendation_code = "continue_monitoring"

    if health == "healthy":
        narrative_intro = "The account is in good condition based on the information currently available."
    elif health == "watch":
        narrative_intro = "The account is generally stable, but one or more items should be monitored or resolved."
    elif health == "review":
        narrative_intro = "The account requires attention because material score, reporting, renewal, or review issues are present."
    else:
        narrative_intro = "The account does not yet have enough calculated information for a complete health assessment."

    narrative_points = strengths[:2] + concerns[:3]

    component_totals = {}
    component_counts = {}
    component_meta = {}
    for projection in projections:
        if not projection.score_details:
            continue
        try:
            detail = json.loads(projection.score_details)
        except (TypeError, ValueError):
            continue
        for component in detail.get("components", []):
            key = component.get("key")
            if not key:
                continue
            component_totals[key] = component_totals.get(key, 0) + float(component.get("score", 0))
            component_counts[key] = component_counts.get(key, 0) + 1
            component_meta[key] = component
    account_components = []
    for key in WEIGHTS:
        if key not in component_counts:
            continue
        meta = component_meta[key]
        score = round(component_totals[key] / component_counts[key])
        account_components.append({
            "key": key, "label": meta.get("label", key.replace("_", " ").title()),
            "score": score, "weight": WEIGHTS[key], "band": score_band(score),
            "exposure_count": component_counts[key],
        })

    return {
        "core_index": avg_index, "accuracy": avg_accuracy, "confidence": avg_confidence,
        "health": health, "open_reviews": len(open_reviews), "high_reviews": len(high_reviews),
        "overdue_reporting": overdue, "due_soon_reporting": due_soon,
        "next_policy": next_policy, "days_to_renewal": days_to_renewal,
        "exposure_rows": exposure_rows, "renewal_rows": renewal_rows,
        "estimate_projection": estimate_projection, "score_chart": score_chart,
        "intelligence": {
            "headline": narrative_intro,
            "points": narrative_points,
            "strengths": strengths,
            "concerns": concerns,
            "drivers": drivers,
            "recommendation": recommendation,
            "recommendation_code": recommendation_code,
            "material_exposure_count": len(material_rows),
            "components": account_components,
            "scoring_version": SCORING_VERSION if account_components else None,
        },
    }


def portfolio_intelligence(db: Session, as_of: date | None = None) -> dict:
    """Agency-wide focus layer built from live account, reporting, renewal, and workload data."""
    from collections import defaultdict
    from datetime import timedelta
    from .models import Task, User

    as_of = as_of or date.today()
    base = portfolio_insights(db)
    executive = executive_dashboard_insights(db, as_of)
    business_rows = {row["business"].id: dict(row) for row in base["rows"]}

    # Accumulate operational pressure by business.
    overdue_by_business = defaultdict(int)
    due_soon_by_business = defaultdict(int)
    for row in executive["reporting_due"]:
        if row["status"] == "overdue":
            overdue_by_business[row["business"].id] += 1
        elif row["status"] == "due_soon":
            due_soon_by_business[row["business"].id] += 1

    renewal_days = {}
    for row in executive["renewals"]:
        bid = row["business"].id
        renewal_days[bid] = min(renewal_days.get(bid, 99999), row["days"])

    material_by_business = defaultdict(int)
    variance_by_business = defaultdict(list)
    for row in executive["exposure_changes"]:
        bid = row["business"].id
        if row["material"]:
            material_by_business[bid] += 1
        variance_by_business[bid].append(abs(row["variance"]))

    # Measure whether account scores are improving or deteriorating using the two latest projections.
    score_movements = defaultdict(list)
    exposures = list(db.scalars(select(Exposure).join(Policy).where(Exposure.active.is_(True))))
    for exposure in exposures:
        projections = list(db.scalars(
            select(Projection).where(Projection.exposure_id == exposure.id)
            .order_by(Projection.created_at.desc()).limit(2)
        ))
        if len(projections) == 2:
            score_movements[exposure.policy.business_id].append(
                projections[0].core_index - projections[1].core_index
            )

    priority_accounts = []
    worsening_accounts = []
    for bid, row in business_rows.items():
        core = row["core_index"]
        overdue = overdue_by_business[bid]
        due_soon = due_soon_by_business[bid]
        renewal = renewal_days.get(bid)
        material = material_by_business[bid]
        movements = score_movements.get(bid, [])
        avg_movement = round(sum(movements) / len(movements), 1) if movements else None

        score = 0
        reasons = []
        if row["high_reviews"]:
            score += row["high_reviews"] * 40
            reasons.append(f"{row['high_reviews']} high-priority review{'s' if row['high_reviews'] != 1 else ''}")
        if overdue:
            score += overdue * 25
            reasons.append(f"{overdue} overdue report{'s' if overdue != 1 else ''}")
        if renewal is not None and renewal <= 30:
            score += 20
            reasons.append(f"renewal in {renewal} days")
        elif renewal is not None and renewal <= 60:
            score += 10
            reasons.append(f"renewal in {renewal} days")
        if material:
            score += material * 15
            reasons.append(f"{material} material exposure change{'s' if material != 1 else ''}")
        if core is not None and core < 70:
            score += 25
            reasons.append(f"core index {core}")
        elif core is not None and core < 85:
            score += 10
            reasons.append(f"core index {core}")
        if due_soon:
            score += due_soon * 5
            reasons.append(f"{due_soon} report{'s' if due_soon != 1 else ''} due soon")
        if row["missing_exposures"]:
            score += row["missing_exposures"] * 4
            reasons.append("incomplete exposure scoring")

        if score or row["health"] != "healthy":
            priority_accounts.append({
                **row,
                "priority_score": score,
                "reasons": reasons[:3] or [row["next_action"]],
                "renewal_days": renewal,
                "overdue_reporting": overdue,
                "material_changes": material,
                "score_movement": avg_movement,
            })
        if avg_movement is not None and avg_movement < 0:
            worsening_accounts.append({
                **row,
                "score_movement": avg_movement,
                "reason": "Average CommercialCore Index declined across recently recalculated exposures.",
            })

    priority_accounts.sort(key=lambda r: (-r["priority_score"], r["business"].legal_name.lower()))
    worsening_accounts.sort(key=lambda r: (r["score_movement"], r["business"].legal_name.lower()))

    # Six-month renewal pressure view.
    renewal_months = []
    for offset in range(6):
        month_index = (as_of.month - 1 + offset) % 12 + 1
        year = as_of.year + (as_of.month - 1 + offset) // 12
        count = db.scalar(select(func.count()).select_from(Policy).where(
            func.strftime('%m', Policy.expiration_date) == f"{month_index:02d}",
            func.strftime('%Y', Policy.expiration_date) == str(year),
        )) or 0
        renewal_months.append({
            "label": date(year, month_index, 1).strftime("%b %Y"),
            "count": count,
        })
    max_renewals = max((row["count"] for row in renewal_months), default=0) or 1
    for row in renewal_months:
        row["percent"] = round(row["count"] / max_renewals * 100)

    # Workload concentration across active staff.
    users = list(db.scalars(select(User).where(User.active.is_(True)).order_by(User.full_name)))
    workload = []
    for user in users:
        tasks = db.scalar(select(func.count()).select_from(Task).where(
            Task.assigned_to == user.id, Task.status != "completed"
        )) or 0
        overdue_tasks = db.scalar(select(func.count()).select_from(Task).where(
            Task.assigned_to == user.id, Task.status != "completed",
            Task.due_date.is_not(None), Task.due_date < as_of,
        )) or 0
        reviews = db.scalar(select(func.count()).select_from(ReviewItem).where(
            ReviewItem.assigned_to == user.id, ReviewItem.status != "closed"
        )) or 0
        total = tasks + reviews
        workload.append({"user": user, "tasks": tasks, "overdue": overdue_tasks, "reviews": reviews, "total": total})
    workload.sort(key=lambda r: (-r["total"], -r["overdue"], r["user"].full_name.lower()))
    max_workload = max((row["total"] for row in workload), default=0) or 1
    for row in workload:
        row["percent"] = round(row["total"] / max_workload * 100)

    health_distribution = [
        {"label": "Healthy", "count": base["healthy_count"], "class": "healthy"},
        {"label": "Watch", "count": base["watch_count"], "class": "watch"},
        {"label": "Review", "count": base["review_count"], "class": "review"},
        {"label": "Unscored", "count": base["unscored_count"], "class": "unscored"},
    ]
    total_businesses = max(len(base["rows"]), 1)
    for item in health_distribution:
        item["percent"] = round(item["count"] / total_businesses * 100)

    reporting_problems = [row for row in executive["reporting_due"] if row["status"] == "overdue"]

    return {
        "as_of": as_of,
        "health_distribution": health_distribution,
        "priority_accounts": priority_accounts[:10],
        "worsening_accounts": worsening_accounts[:8],
        "renewal_months": renewal_months,
        "reporting_problems": reporting_problems[:8],
        "workload": workload,
        "accounts_requiring_focus": len(priority_accounts),
        "worsening_count": len(worsening_accounts),
        "overdue_reporting_count": len(reporting_problems),
        "unassigned_reviews": executive["review_counts"]["unassigned"],
    }


def executive_analytics(db: Session, as_of: date | None = None) -> dict:
    """Executive analytics for the agency dashboard using only auditable stored data."""
    from calendar import month_abbr
    from datetime import timedelta

    as_of = as_of or date.today()
    policies = list(db.scalars(select(Policy).where(Policy.expiration_date >= as_of)))
    active_premium = sum(float(p.annual_premium or 0) for p in policies)
    premium_policies = sum(1 for p in policies if p.annual_premium is not None)

    projections = list(db.scalars(select(Projection)))
    latest_by_exposure = {}
    for projection in sorted(projections, key=lambda p: p.created_at):
        latest_by_exposure[projection.exposure_id] = projection
    latest = list(latest_by_exposure.values())
    average_core = round(sum(p.core_index for p in latest) / len(latest)) if latest else None

    portfolio = portfolio_insights(db)
    health_counts = {"healthy": 0, "watch": 0, "review": 0, "unscored": 0}
    for row in portfolio["rows"]:
        health_counts[row["health"]] = health_counts.get(row["health"], 0) + 1
    total_businesses = max(sum(health_counts.values()), 1)
    health_distribution = [
        {"label": name.title(), "key": name, "count": count, "percent": round(count / total_businesses * 100)}
        for name, count in health_counts.items()
    ]

    # Active premium grouped by policy effective month for the trailing 12 months.
    months = []
    year, month = as_of.year, as_of.month
    for offset in range(11, -1, -1):
        raw = year * 12 + month - 1 - offset
        y, m0 = divmod(raw, 12)
        m = m0 + 1
        months.append((y, m))
    premium_trend = []
    for y, m in months:
        value = sum(float(p.annual_premium or 0) for p in policies if p.effective_date.year == y and p.effective_date.month == m)
        premium_trend.append({"label": f"{month_abbr[m]} {str(y)[2:]}", "value": round(value, 2)})

    # Renewal premium pipeline for the next six calendar months.
    renewal_pipeline = []
    for offset in range(6):
        raw = year * 12 + month - 1 + offset
        y, m0 = divmod(raw, 12)
        m = m0 + 1
        month_policies = [p for p in policies if p.expiration_date.year == y and p.expiration_date.month == m]
        renewal_pipeline.append({
            "label": f"{month_abbr[m]} {str(y)[2:]}",
            "count": len(month_policies),
            "premium": round(sum(float(p.annual_premium or 0) for p in month_policies), 2),
        })

    cadence_days = {"weekly": 7, "monthly": 30, "quarterly": 91}
    reporting = {"overdue": 0, "due_soon": 0, "current": 0, "not_started": 0}
    overdue_accounts = set()
    exposures = list(db.scalars(select(Exposure).join(Policy).where(Exposure.active.is_(True), Policy.expiration_date >= as_of)))
    for exposure in exposures:
        entry = db.scalar(select(ReportingEntry).where(ReportingEntry.exposure_id == exposure.id, ReportingEntry.accepted.is_(True)).order_by(ReportingEntry.period_end.desc()))
        cadence = cadence_days.get(exposure.cadence, 30)
        if entry:
            due = entry.period_end + timedelta(days=cadence + exposure.reporting_due_days)
            days = (due - as_of).days
            status = "overdue" if days < 0 else "due_soon" if days <= 7 else "current"
        else:
            due = exposure.policy.effective_date + timedelta(days=cadence + exposure.reporting_due_days)
            status = "overdue" if due < as_of else "not_started"
        reporting[status] += 1
        if status == "overdue":
            overdue_accounts.add(exposure.policy.business_id)

    return {
        "active_premium": round(active_premium, 2),
        "premium_policy_count": premium_policies,
        "average_core": average_core,
        "scored_exposure_count": len(latest),
        "health_distribution": health_distribution,
        "premium_trend": premium_trend,
        "renewal_pipeline": renewal_pipeline,
        "reporting": reporting,
        "overdue_account_count": len(overdue_accounts),
    }


def staff_analytics(db: Session, as_of: date | None = None) -> dict:
    """Auditable staff workload and activity metrics for Phase 7.4.2."""
    from datetime import datetime, time, timedelta
    from .models import User, Task, Activity, ReviewItem, Business

    as_of = as_of or date.today()
    start_30 = datetime.combine(as_of - timedelta(days=29), time.min)
    end_day = datetime.combine(as_of + timedelta(days=1), time.min)
    active_users = list(db.scalars(select(User).where(User.active.is_(True)).order_by(User.full_name)))
    tasks = list(db.scalars(select(Task)))
    activities = list(db.scalars(select(Activity).where(Activity.occurred_at >= start_30, Activity.occurred_at < end_day)))
    reviews = list(db.scalars(select(ReviewItem).where(ReviewItem.status != "closed")))
    businesses = list(db.scalars(select(Business)))

    rows = []
    completion_durations = []
    for user in active_users:
        assigned = [t for t in tasks if t.assigned_to == user.id]
        open_tasks = [t for t in assigned if t.status != "completed"]
        overdue = [t for t in open_tasks if t.due_date and t.due_date < as_of]
        due_week = [t for t in open_tasks if t.due_date and as_of <= t.due_date <= as_of + timedelta(days=7)]
        completed_30 = [t for t in assigned if t.status == "completed" and t.completed_at and start_30 <= t.completed_at < end_day]
        durations = [max((t.completed_at - t.created_at).total_seconds() / 86400, 0) for t in completed_30]
        completion_durations.extend(durations)
        user_activities = [a for a in activities if a.owner_id == user.id]
        open_reviews = [r for r in reviews if r.assigned_to == user.id]
        produced_accounts = [b for b in businesses if b.producer_id == user.id]
        rows.append({
            "user": user, "open_tasks": len(open_tasks), "overdue_tasks": len(overdue),
            "due_week": len(due_week), "completed_30": len(completed_30),
            "average_completion_days": round(sum(durations)/len(durations), 1) if durations else None,
            "activities_30": len(user_activities), "open_reviews": len(open_reviews),
            "produced_accounts": len(produced_accounts),
        })
    rows.sort(key=lambda r: (-r["overdue_tasks"], -r["open_tasks"], r["user"].full_name.lower()))
    open_all = [t for t in tasks if t.status != "completed"]
    completed_all_30 = [t for t in tasks if t.status == "completed" and t.completed_at and start_30 <= t.completed_at < end_day]
    return {
        "as_of": as_of, "active_staff": len(active_users), "rows": rows,
        "open_tasks": len(open_all),
        "overdue_tasks": sum(1 for t in open_all if t.due_date and t.due_date < as_of),
        "completed_30": len(completed_all_30), "activities_30": len(activities),
        "open_reviews": len(reviews),
        "average_completion_days": round(sum(completion_durations)/len(completion_durations), 1) if completion_durations else None,
        "workload_chart": [{"label": r["user"].full_name, "open": r["open_tasks"], "overdue": r["overdue_tasks"]} for r in rows],
        "activity_chart": [{"label": r["user"].full_name, "activities": r["activities_30"], "completed": r["completed_30"]} for r in rows],
    }


def portfolio_analytics(db: Session, as_of: date | None = None) -> dict:
    """Phase 7.4.3 portfolio composition and concentration analytics."""
    from collections import defaultdict
    from .models import Location, PolicyCarrier

    as_of = as_of or date.today()
    businesses = list(db.scalars(select(Business).where(Business.status == "active").order_by(Business.legal_name)))
    policies = list(db.scalars(select(Policy).where(Policy.expiration_date >= as_of)))

    premium_by_business = defaultdict(float)
    premium_by_industry = defaultdict(float)
    premium_by_line = defaultdict(float)
    premium_by_carrier = defaultdict(float)
    policy_count_by_carrier = defaultdict(int)
    policy_count_by_line = defaultdict(int)

    for policy in policies:
        premium = float(policy.annual_premium or 0)
        premium_by_business[policy.business_id] += premium
        premium_by_industry[(policy.business.industry or "Unspecified").strip() or "Unspecified"] += premium
        premium_by_line[(policy.line or "Unspecified").strip() or "Unspecified"] += premium
        policy_count_by_line[(policy.line or "Unspecified").strip() or "Unspecified"] += 1
        carrier = policy.carrier_reference.carrier_name.strip() if policy.carrier_reference and policy.carrier_reference.carrier_name else "Unspecified"
        premium_by_carrier[carrier] += premium
        policy_count_by_carrier[carrier] += 1

    total_premium = sum(premium_by_business.values())

    def breakdown(values, counts=None, limit=8):
        rows=[]
        for label, value in sorted(values.items(), key=lambda item: (-item[1], item[0].lower()))[:limit]:
            rows.append({
                "label": label, "premium": round(value, 2),
                "percent": round(value / total_premium * 100, 1) if total_premium else 0,
                "count": counts.get(label, 0) if counts else None,
            })
        return rows

    largest_accounts=[]
    for business in businesses:
        premium=premium_by_business.get(business.id, 0.0)
        largest_accounts.append({
            "business": business, "premium": round(premium, 2),
            "percent": round(premium / total_premium * 100, 1) if total_premium else 0,
            "policy_count": sum(1 for p in policies if p.business_id == business.id),
        })
    largest_accounts.sort(key=lambda row: (-row["premium"], row["business"].legal_name.lower()))

    # Geographic distribution uses each account's active primary location once.
    states=defaultdict(lambda: {"accounts": 0, "premium": 0.0})
    for business in businesses:
        active_locations=[loc for loc in business.locations if loc.active]
        location=active_locations[0] if active_locations else None
        state=location.state.upper() if location and location.state else "Unspecified"
        states[state]["accounts"] += 1
        states[state]["premium"] += premium_by_business.get(business.id, 0.0)
    geographic=[]
    for state, values in sorted(states.items(), key=lambda item: (-item[1]["premium"], -item[1]["accounts"], item[0])):
        geographic.append({
            "state": state, "accounts": values["accounts"], "premium": round(values["premium"], 2),
            "percent": round(values["premium"] / total_premium * 100, 1) if total_premium else 0,
        })

    # Growth is based on the two latest stored projections per exposure.
    growth_by_business=defaultdict(list)
    decline_by_business=defaultdict(list)
    for exposure in db.scalars(select(Exposure).join(Policy).where(Exposure.active.is_(True))):
        recent=list(db.scalars(select(Projection).where(Projection.exposure_id == exposure.id).order_by(Projection.created_at.desc()).limit(2)))
        if len(recent) != 2:
            continue
        previous=float(recent[1].projected_total)
        current=float(recent[0].projected_total)
        if previous <= 0:
            continue
        movement=(current-previous)/previous*100
        target=growth_by_business if movement >= 0 else decline_by_business
        target[exposure.policy.business_id].append(movement)

    def movement_rows(source, reverse):
        rows=[]
        business_map={b.id:b for b in businesses}
        for bid, movements in source.items():
            business=business_map.get(bid)
            if not business:
                continue
            rows.append({"business": business, "movement": round(sum(movements)/len(movements), 1), "exposure_count": len(movements)})
        rows.sort(key=lambda row: row["movement"], reverse=reverse)
        return rows[:8]

    carrier_rows=breakdown(premium_by_carrier, policy_count_by_carrier)
    industry_rows=breakdown(premium_by_industry)
    line_rows=breakdown(premium_by_line, policy_count_by_line)
    top_five_premium=sum(row["premium"] for row in largest_accounts[:5])

    return {
        "as_of": as_of, "total_premium": round(total_premium, 2),
        "tracked_business_count": sum(1 for value in premium_by_business.values() if value > 0),
        "carrier_count": len([key for key in premium_by_carrier if key != "Unspecified"]),
        "industry_count": len([key for key in premium_by_industry if key != "Unspecified"]),
        "line_count": len([key for key in premium_by_line if key != "Unspecified"]),
        "top_five_concentration": round(top_five_premium / total_premium * 100, 1) if total_premium else 0,
        "premium_by_carrier": carrier_rows, "premium_by_industry": industry_rows,
        "premium_by_line": line_rows, "largest_accounts": largest_accounts[:10],
        "geographic": geographic[:10], "growing_accounts": movement_rows(growth_by_business, True),
        "declining_accounts": movement_rows(decline_by_business, False),
        "carrier_chart": [{"label": row["label"], "value": row["premium"]} for row in carrier_rows],
        "industry_chart": [{"label": row["label"], "value": row["premium"]} for row in industry_rows],
        "line_chart": [{"label": row["label"], "value": row["premium"]} for row in line_rows],
    }


def historical_analytics(db: Session, as_of: date | None = None, months: int = 12) -> dict:
    """Phase 7.4.5 historical trends derived from dated application records."""
    from calendar import month_abbr
    from collections import defaultdict
    from datetime import datetime, time
    from .models import Task, Activity, Recommendation

    as_of = as_of or date.today()
    month_keys = []
    raw = as_of.year * 12 + as_of.month - 1
    for offset in range(months - 1, -1, -1):
        y, m0 = divmod(raw - offset, 12)
        month_keys.append((y, m0 + 1))

    def label(key):
        y, m = key
        return f"{month_abbr[m]} {str(y)[2:]}"

    def month_of(value):
        if not value:
            return None
        return (value.year, value.month)

    tasks = list(db.scalars(select(Task)))
    activities = list(db.scalars(select(Activity)))
    recommendations = list(db.scalars(select(Recommendation)))
    projections = list(db.scalars(select(Projection)))

    created_tasks = defaultdict(int)
    completed_tasks = defaultdict(int)
    activity_counts = defaultdict(int)
    created_recommendations = defaultdict(int)
    resolved_recommendations = defaultdict(int)
    monthly_scores = defaultdict(list)

    for task in tasks:
        created_tasks[month_of(task.created_at)] += 1
        if task.completed_at:
            completed_tasks[month_of(task.completed_at)] += 1
    for activity in activities:
        activity_counts[month_of(activity.occurred_at)] += 1
    for recommendation in recommendations:
        created_recommendations[month_of(recommendation.created_at)] += 1
        if recommendation.resolved_at:
            resolved_recommendations[month_of(recommendation.resolved_at)] += 1
    for projection in projections:
        monthly_scores[month_of(projection.created_at)].append(float(projection.core_index))

    operations = []
    recommendation_trend = []
    score_trend = []
    for key in month_keys:
        scores = monthly_scores.get(key, [])
        operations.append({
            "label": label(key),
            "tasks_created": created_tasks[key],
            "tasks_completed": completed_tasks[key],
            "activities": activity_counts[key],
        })
        recommendation_trend.append({
            "label": label(key),
            "created": created_recommendations[key],
            "resolved": resolved_recommendations[key],
        })
        score_trend.append({
            "label": label(key),
            "average_core": round(sum(scores) / len(scores), 1) if scores else None,
            "calculations": len(scores),
        })

    current_key = month_keys[-1]
    prior_key = month_keys[-2] if len(month_keys) > 1 else None
    current_scores = monthly_scores.get(current_key, [])
    prior_scores = monthly_scores.get(prior_key, []) if prior_key else []
    current_average = round(sum(current_scores) / len(current_scores), 1) if current_scores else None
    prior_average = round(sum(prior_scores) / len(prior_scores), 1) if prior_scores else None
    score_change = round(current_average - prior_average, 1) if current_average is not None and prior_average is not None else None

    total_created = sum(created_recommendations[k] for k in month_keys)
    total_resolved = sum(resolved_recommendations[k] for k in month_keys)
    recommendation_resolution_rate = round(total_resolved / total_created * 100, 1) if total_created else None
    total_task_created = sum(created_tasks[k] for k in month_keys)
    total_task_completed = sum(completed_tasks[k] for k in month_keys)
    task_completion_rate = round(total_task_completed / total_task_created * 100, 1) if total_task_created else None

    return {
        "as_of": as_of,
        "months": months,
        "operations": operations,
        "recommendations": recommendation_trend,
        "score_trend": score_trend,
        "current_average_core": current_average,
        "score_change": score_change,
        "task_completion_rate": task_completion_rate,
        "recommendation_resolution_rate": recommendation_resolution_rate,
        "activities_total": sum(activity_counts[k] for k in month_keys),
        "tasks_completed_total": total_task_completed,
        "recommendations_resolved_total": total_resolved,
    }

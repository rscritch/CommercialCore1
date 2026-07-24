from __future__ import annotations

from datetime import date
from typing import Any

SCORING_VERSION = "2.0"
WEIGHTS = {
    "exposure_accuracy": 30,
    "reporting_completeness": 20,
    "reporting_freshness": 15,
    "historical_support": 10,
    "renewal_readiness": 10,
    "review_risk": 10,
    "data_readiness": 5,
}


def clamp(value: float, low: int = 0, high: int = 100) -> int:
    return max(low, min(high, round(value)))


def score_band(score: int | None) -> dict[str, str]:
    if score is None:
        return {"label": "Not calculated", "class": "neutral"}
    if score >= 85:
        return {"label": "Healthy", "class": "healthy"}
    if score >= 70:
        return {"label": "Watch", "class": "watch"}
    return {"label": "Review suggested", "class": "review"}


def build_intelligence_score(
    *,
    variance_percent: float,
    received: int,
    expected_to_date: int,
    days_late: int,
    complete_years: int,
    days_to_renewal: int | None,
    open_reviews: int,
    high_reviews: int,
    has_estimate: bool,
    has_current_reporting: bool,
    projection_method: str,
) -> dict[str, Any]:
    """Return a deterministic, explainable CommercialCore Intelligence score.

    Every component is scored from 0–100 and then multiplied by a visible weight.
    Missing data reduces only the components it affects; it is never treated as healthy.
    """
    accuracy = clamp(100 - abs(variance_percent)) if has_estimate else 0
    completeness = clamp((received / max(expected_to_date, 1)) * 100)
    freshness = clamp(100 - (days_late / 30 * 100)) if has_current_reporting else 0
    historical = 100 if complete_years >= 2 else 75 if complete_years == 1 else 40

    if days_to_renewal is None:
        renewal = 60
        renewal_reason = "No active renewal date is available; a neutral readiness score is used."
    elif days_to_renewal < 0:
        renewal = 15
        renewal_reason = f"The policy expiration date passed {abs(days_to_renewal)} days ago."
    elif days_to_renewal <= 30:
        renewal = 45
        renewal_reason = f"Only {days_to_renewal} days remain before renewal."
    elif days_to_renewal <= 90:
        renewal = 75
        renewal_reason = f"The renewal is {days_to_renewal} days away and requires active preparation."
    else:
        renewal = 100
        renewal_reason = f"The renewal is {days_to_renewal} days away."

    review = clamp(100 - high_reviews * 35 - max(open_reviews - high_reviews, 0) * 12)
    readiness_points = 0
    readiness_points += 35 if has_estimate else 0
    readiness_points += 35 if has_current_reporting else 0
    readiness_points += 20 if projection_method in {"seasonal", "prior_year_pace"} else 10
    readiness_points += 10 if expected_to_date > 0 else 0
    data_readiness = clamp(readiness_points)

    components = [
        {
            "key": "exposure_accuracy", "label": "Exposure accuracy", "score": accuracy,
            "weight": WEIGHTS["exposure_accuracy"],
            "reason": f"The projection is {variance_percent:+.1f}% from the recorded estimate." if has_estimate else "No recorded estimate is available.",
        },
        {
            "key": "reporting_completeness", "label": "Reporting completeness", "score": completeness,
            "weight": WEIGHTS["reporting_completeness"],
            "reason": f"{received} of approximately {max(expected_to_date, 1)} expected reports have been received.",
        },
        {
            "key": "reporting_freshness", "label": "Reporting freshness", "score": freshness,
            "weight": WEIGHTS["reporting_freshness"],
            "reason": "Reporting is current." if has_current_reporting and days_late == 0 else (f"Reporting is approximately {days_late} days beyond the grace period." if has_current_reporting else "No current accepted reporting is available."),
        },
        {
            "key": "historical_support", "label": "Historical support", "score": historical,
            "weight": WEIGHTS["historical_support"],
            "reason": f"{complete_years} complete comparable prior year(s) support the projection.",
        },
        {
            "key": "renewal_readiness", "label": "Renewal readiness", "score": renewal,
            "weight": WEIGHTS["renewal_readiness"], "reason": renewal_reason,
        },
        {
            "key": "review_risk", "label": "Open-review risk", "score": review,
            "weight": WEIGHTS["review_risk"],
            "reason": f"{high_reviews} high-priority and {max(open_reviews-high_reviews, 0)} other open review item(s) are active.",
        },
        {
            "key": "data_readiness", "label": "Data readiness", "score": data_readiness,
            "weight": WEIGHTS["data_readiness"],
            "reason": f"The {projection_method.replace('_', ' ')} method is supported by the available estimate, reporting, and history.",
        },
    ]
    for component in components:
        component["weighted_points"] = round(component["score"] * component["weight"] / 100, 1)
        component["band"] = score_band(component["score"])

    core_index = clamp(sum(item["weighted_points"] for item in components))
    confidence = clamp(
        completeness * 0.45 + freshness * 0.30 + historical * 0.15 + data_readiness * 0.10
    )
    strengths = [c["label"] for c in components if c["score"] >= 85]
    concerns = [c["label"] for c in components if c["score"] < 70]
    return {
        "version": SCORING_VERSION,
        "as_of": date.today().isoformat(),
        "core_index": core_index,
        "accuracy_score": accuracy,
        "confidence_score": confidence,
        "components": components,
        "strengths": strengths,
        "concerns": concerns,
        "formula": " + ".join(f"{item['label']} × {item['weight']}%" for item in components),
        "band": score_band(core_index),
    }

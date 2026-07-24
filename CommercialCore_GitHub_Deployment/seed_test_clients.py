from __future__ import annotations

from calendar import monthrange
from datetime import date
from decimal import Decimal
from sqlalchemy import select

from app.main import initialize
from app.db import SessionLocal
from app.models import (
    User, Business, Contact, Location, Policy, Exposure,
    ReportingEntry, ReviewItem
)
from app.services import calculate_projection

TEST_PREFIX = "[TEST] "

CLIENTS = [
    {
        "name": "[TEST] Prairie Office Solutions",
        "industry": "Professional services",
        "renewal_month": 1,
        "class_code": "8810",
        "class_description": "Clerical Office Employees",
        "annual_premium": 7800,
        "estimate_2026": 425000,
        "history": {
            2021: 310000, 2022: 327000, 2023: 345000, 2024: 365000, 2025: 389000
        },
        "current_total": 206000,
        "pattern": "stable",
        "review": None,
        "contact": ("Emily Carter", "Controller", "emily.carter@example.test"),
        "city": "Normal",
    },
    {
        "name": "[TEST] GreenLine Landscape Group",
        "industry": "Landscape construction and maintenance",
        "renewal_month": 1,
        "class_code": "0042",
        "class_description": "Landscape Gardening",
        "annual_premium": 46200,
        "estimate_2026": 860000,
        "history": {
            2021: 455000, 2022: 535000, 2023: 645000, 2024: 765000, 2025: 915000
        },
        "current_total": 590000,
        "pattern": "seasonal_growth",
        "review": {
            "rule_code": "test_growth_variance",
            "priority": "high",
            "title": "Rapid payroll growth requires estimate review",
            "evidence": "Current payroll pace is materially above the recorded annual estimate."
        },
        "contact": ("Marcus Hill", "President", "marcus.hill@example.test"),
        "city": "Bloomington",
    },
    {
        "name": "[TEST] IronGate Commercial Builders",
        "industry": "Commercial construction",
        "renewal_month": 1,
        "class_code": "5645",
        "class_description": "Carpentry — Detached Dwellings",
        "annual_premium": 112500,
        "estimate_2026": 1480000,
        "history": {
            2021: 1280000, 2022: 1460000, 2023: 1190000, 2024: 1510000, 2025: 1360000
        },
        "current_total": 690000,
        "pattern": "volatile",
        "review": {
            "rule_code": "test_classification_review",
            "priority": "medium",
            "title": "Validate payroll allocation and class-code usage",
            "evidence": "Payroll varies significantly year to year and should be reconciled by operation before renewal."
        },
        "contact": ("Dana Brooks", "Chief Financial Officer", "dana.brooks@example.test"),
        "city": "Peoria",
    },
    {
        "name": "[TEST] Midwest Regional Freight",
        "industry": "Trucking and logistics",
        "renewal_month": 1,
        "class_code": "7219",
        "class_description": "Trucking — NOC",
        "annual_premium": 158000,
        "estimate_2026": 1150000,
        "history": {
            2021: 1495000, 2022: 1370000, 2023: 1210000, 2024: 970000, 2025: 735000
        },
        "current_total": 300000,
        "pattern": "declining",
        "review": {
            "rule_code": "test_declining_payroll",
            "priority": "high",
            "title": "Recorded payroll estimate appears materially overstated",
            "evidence": "Five-year payroll history shows a sustained decline and current pace is below the recorded estimate."
        },
        "contact": ("Luis Martinez", "Operations Manager", "luis.martinez@example.test"),
        "city": "Springfield",
    },
]

MONTH_WEIGHTS = {
    "stable": [0.080, 0.080, 0.083, 0.083, 0.084, 0.084, 0.084, 0.084, 0.084, 0.084, 0.083, 0.083],
    "seasonal_growth": [0.045, 0.050, 0.070, 0.095, 0.120, 0.125, 0.125, 0.120, 0.100, 0.075, 0.050, 0.025],
    "volatile": [0.060, 0.090, 0.055, 0.120, 0.075, 0.110, 0.065, 0.130, 0.080, 0.095, 0.055, 0.065],
    "declining": [0.090, 0.085, 0.085, 0.082, 0.082, 0.080, 0.080, 0.080, 0.079, 0.079, 0.079, 0.079],
}

def monthly_values(total: int, pattern: str, months: int = 12) -> list[int]:
    weights = MONTH_WEIGHTS[pattern][:months]
    scale = sum(weights)
    values = [round(total * (w / scale)) for w in weights]
    values[-1] += total - sum(values)
    return values

def add_year(db, exposure, user_id: int, year: int, total: int, pattern: str, months: int = 12):
    for month, amount in enumerate(monthly_values(total, pattern, months), start=1):
        db.add(ReportingEntry(
            exposure=exposure,
            period_start=date(year, month, 1),
            period_end=date(year, month, monthrange(year, month)[1]),
            actual_value=Decimal(amount),
            source="test_seed",
            note=f"Synthetic test payroll for {year}-{month:02d}",
            accepted=True,
            created_by=user_id,
        ))

def seed():
    initialize()
    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.username == "admin"))
        if not admin:
            raise RuntimeError("Default administrator was not created.")

        existing = list(db.scalars(select(Business).where(Business.legal_name.like(f"{TEST_PREFIX}%"))))
        for business in existing:
            db.delete(business)
        db.commit()

        for client in CLIENTS:
            business = Business(
                legal_name=client["name"],
                industry=client["industry"],
                status="active",
                renewal_month=client["renewal_month"],
                producer_id=admin.id,
            )
            business.contacts.append(Contact(
                name=client["contact"][0],
                title=client["contact"][1],
                email=client["contact"][2],
                phone="309-555-01" + str(len(client["class_code"])),
                is_primary=True,
            ))
            business.locations.append(Location(
                label="Primary",
                address1="100 Test Data Way",
                city=client["city"],
                state="IL",
                postal_code="61701",
                active=True,
            ))
            policy = Policy(
                line="Workers Compensation",
                policy_number_ref=f"TEST-WC-{client['class_code']}",
                effective_date=date(2026, 1, 1),
                expiration_date=date(2026, 12, 31),
                annual_premium=Decimal(client["annual_premium"]),
                notes=(
                    f"TEST DATA — WC class code {client['class_code']}: "
                    f"{client['class_description']}. Synthetic records for application testing only."
                ),
            )
            exposure = Exposure(
                exposure_type=f"WC Payroll — Class {client['class_code']}",
                recorded_estimate=Decimal(client["estimate_2026"]),
                cadence="monthly",
                unit="payroll dollars",
                reporting_due_days=15,
                active=True,
            )
            policy.exposures.append(exposure)
            business.policies.append(policy)
            db.add(business)
            db.flush()

            for year, total in client["history"].items():
                add_year(db, exposure, admin.id, year, total, client["pattern"], 12)

            # Six accepted monthly reports for the current year provide a live projection.
            add_year(db, exposure, admin.id, 2026, client["current_total"], client["pattern"], 6)
            db.flush()

            if client["review"]:
                db.add(ReviewItem(
                    business_id=business.id,
                    exposure_id=exposure.id,
                    rule_code=client["review"]["rule_code"],
                    priority=client["review"]["priority"],
                    title=client["review"]["title"],
                    evidence=client["review"]["evidence"],
                    status="open",
                    assigned_to=admin.id,
                ))
                db.flush()

            calculate_projection(db, exposure, as_of=date(2026, 6, 30))

        db.commit()

        rows = list(db.scalars(
            select(Business).where(Business.legal_name.like(f"{TEST_PREFIX}%")).order_by(Business.legal_name)
        ))
        if len(rows) != 4:
            raise RuntimeError(f"Expected 4 test clients, found {len(rows)}")
        for business in rows:
            exposure = business.policies[0].exposures[0]
            if len(exposure.entries) != 66:
                raise RuntimeError(f"{business.legal_name} has {len(exposure.entries)} entries; expected 66.")

        print("Created 4 full-spectrum test clients with 264 monthly payroll records.")

if __name__ == "__main__":
    seed()

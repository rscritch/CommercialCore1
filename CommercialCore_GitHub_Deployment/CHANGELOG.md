# CommercialCore v1.4 — Phase 7.4.3

- Added auditable portfolio composition and concentration analytics.
- Added tracked premium breakdowns by carrier, industry, and policy line.
- Added largest-account ranking and top-five premium concentration.
- Added geographic account and premium distribution using primary active locations.
- Added growing and declining account views based on two stored projections.
- Added dashboard charts, tables, and automated coverage for the calculations.

# CommercialCore v1.3 — Phase 7.4.2

- Added auditable staff analytics to the Executive Dashboard.
- Added open, overdue, due-soon, and completed task metrics by staff member.
- Added trailing-30-day client activity and average task-completion metrics.
- Added open-review ownership and producer account counts.
- Added staff workload and activity visualizations.
- Added automated coverage for staff calculations and dashboard rendering.

# Changelog

## 1.2 — Phase 7.4.1 Executive Analytics
- Added an agency-level Executive Analytics section to the dashboard.
- Added tracked annual premium to policies and policy-entry forms.
- Added trailing twelve-month premium effective-date trend.
- Added six-month renewal pipeline by policy count and tracked premium.
- Added executive portfolio-health distribution and reporting-completeness summary.
- Added automated tests for analytics calculations and rendered dashboard sections.

Previous v1.1 recommendation-engine, portfolio-intelligence, CRM, review-packet, reporting, and audit features remain included.

## v1.5 - Phase 7.4.4 Executive Reporting
- Added printable Executive Reporting workspace.
- Added monthly executive management PDF.
- Added portfolio, staff scorecard, and trend CSV exports.
- Added agency scorecard and six-month renewal summary.
- Added audit records for management report generation and exports.

## v1.6 — Phase 7.4.5 Historical Analytics
- Added trailing 12-month task creation and completion trends.
- Added client activity history by month.
- Added recommendation creation, resolution, and resolution-rate analytics.
- Added monthly CommercialCore Index calculation history and month-over-month movement.
- Added a Historical Analytics section to the Executive Dashboard.
- Added automated calculation and rendering tests.

## v1.7 — Intelligence Engine completion
- Replaced the two-factor score with a versioned seven-component CommercialCore Intelligence model.
- Added visible weights for exposure accuracy, reporting completeness, reporting freshness, historical support, renewal readiness, open-review risk, and data readiness.
- Persisted the full score calculation and scoring version with every new projection.
- Added safe SQLite upgrades for existing installations.
- Added exposure-level and account-level component explanations.
- Added regression tests for score persistence, exact weighted reconciliation, and UI visibility.

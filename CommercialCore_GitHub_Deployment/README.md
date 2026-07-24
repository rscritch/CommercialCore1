# CommercialCore Master v1.7


## Intelligence Engine v2.0

Every newly calculated projection stores a transparent seven-component score: exposure accuracy (30%), reporting completeness (20%), reporting freshness (15%), historical support (10%), renewal readiness (10%), open-review risk (10%), and data readiness (5%). The exposure and business workspaces show the component scores and the reason behind each component. Existing databases are upgraded automatically with version and score-detail fields.

CommercialCore is an internal commercial insurance workflow and decision-support application.

## v0.8 focus

This release modernizes the full visual foundation without changing the v0.5 data model. It adds a responsive sidebar, balanced dashboards, modern cards and tables, improved forms, consistent status language, and a streamlined login experience.

## Windows startup

1. Extract this folder.
2. Double-click `run.bat`.
3. Open `http://127.0.0.1:8000`.
4. Sign in with `admin` / `admin123` for a new installation.

## Existing v0.5 data

Copy `data/commercialcore.db`, `data/reports`, and `data/uploads` from v0.5 into the matching v0.8 folders before starting v0.8.

## Tests

Run `run_tests.bat`.


## Phase 5 - Policy Review Builder
Open a business account and choose **Build annual review**. Complete the guided builder, choose packet sections, generate the PDF, review it, and approve it.


## Phase 6
Multi-user CRM with tasks, activities, documents, staff roles, and personal work queues.


## Phase 7.1 — Business Intelligence
Each business dashboard now summarizes account health in plain language, lists the strongest positive and negative drivers, explains why the current assessment was assigned, and recommends the next action. The engine is deterministic and transparent: it uses current projection scores, reporting status, review items, material exposure variance, and renewal timing.



## Version 1.1 — Phase 7.3 Recommendation Engine

CommercialCore now converts detected account conditions into persistent, transparent recommended actions. Each recommendation includes the triggering reason, priority, confidence, and suggested steps. Staff can create an assigned task, add the recommendation to a draft annual review packet, mark it complete, dismiss it, or reopen it.

Current rule categories include:
- High-priority and open review items
- Renewals within 60 days
- Overdue exposure reporting
- Material estimate-to-projection variance
- Active exposures without calculated projections
- Incomplete account setup
- Routine monitoring when no issue is detected

The engine is deterministic and rule-based; it does not use an unexplained AI score.

## Version 1.0 — Phase 7.2 Portfolio Intelligence
Adds agency-wide health distribution, transparent account prioritization, score deterioration tracking, six-month renewal pressure, reporting problem visibility, and staff workload concentration.


## v1.3 — Phase 7.4.2 Executive Analytics
The Executive Dashboard includes tracked annual premium, average CommercialCore Index, overdue-account visibility, a six-month renewal pipeline, trailing premium trend, portfolio-health distribution, and reporting completeness. Enter annual premium when adding a policy to populate premium analytics.


## Phase 7.4.2 Staff Analytics
The Executive Dashboard includes per-user workload, overdue assignments, 30-day task completions, average task completion time, client activity counts, review ownership, and producer account counts.


## Executive Reporting (v1.5)
Use **Executive reports** in the left navigation to print the agency scorecard, download the monthly management PDF, or export portfolio, staff, and trend CSV files.

## Phase 7.4.5 — Historical Analytics
The Executive Dashboard now includes trailing 12-month operating history for tasks, client activities, recommendations, and CommercialCore Index calculations. Historical values are calculated only from dated records stored in the application; months without stored history remain blank or zero.


## Full-spectrum test clients
This package includes four clearly labeled `[TEST]` workers-compensation clients with five complete historical payroll years (2021–2025), six 2026 monthly entries, distinct WC class codes, current projections, and contrasting stable, growing, volatile, and declining patterns. The included database is preloaded; `load_test_clients.bat` safely recreates the same test set.


## Four-point projection comparison
Each exposure now reports straight-line, prior-year pace, seasonal, and WC class-code benchmark values separately. All available values appear together in the projection comparison table and graph, while the selected account-specific method remains clearly identified.

## GitHub and Railway deployment

This edition includes a Dockerfile, Railway configuration, persistent-volume bootstrap, health check,
environment-based administrator credentials, and a deployment guide. See `GITHUB_DEPLOYMENT.md`.


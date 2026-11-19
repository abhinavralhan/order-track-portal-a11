# MEMORY.md: project state for any returning agent

Read this first. Update it after every step. **Never put secrets, passwords, hashes or order rows here.**

## Project
Takehome "Supply Chain Optimization" (`TAKEHOME_README.md`). The README and `data/orders-2000.csv` are the source of truth: derive scope from them, ask when unclear, invent nothing.
- Factory: Detmold, DE 32756. 10 drones, 200 units each, 100 km/h, unlimited range.
- Task A: CEO portal (planned ship + delivery per order, delivery = ready + 3 working days). Task B: algorithm write-up. Task C: hosting design.

## Current status (2026-11-19): ALL PHASES DONE
0 Setup · 1 Research · 2 Plan · 3 Dates · 4 Importer · 5 Portal · 6 Security · 7 Task B · 8 Task C · 9 Audit · 10 Deliverable · final tests. **68 tests pass** (`uv run pytest`).
- Deliverables: `README.md`, `docs/demo.gif` (6 frames, rendered pages screenshotted with Playwright's cached headless Chromium + ffmpeg, no new dependency),
  `docs/design.md` (Task C, Mermaid diagrams: prototype, data flow, AWS hosting; failure modes; events feed), `docs/task-b-algorithm.md`.
- Presentation pack: `PRESENTATION.md` (349-word script, limit 350), `logic.md` (Task B pseudocode), `docs/architecture.md` (Task C at-scale diagram + talking points; simple image `docs/architecture.svg/.png` (8 boxes, shown in README) + backup `docs/architecture-detailed.svg/.png`; hand-written SVG, no external libraries),
  also published as a private artifact: https://claude.ai/artifact/CeyL8UF6joYRoofZg1UEKs
- Audit (`/ponytail-audit`): 7 findings, all fixed: empty-orders crash on /insights, stage names in one place (`insights.STAGES`),
  shared order-ID rule (`importer.ORDER_ID`), case-only duplicates deduped, bounded login-failure memory, misplaced comment, dead .gitignore rule.
- Secret scan: gitleaks not installed; a pattern scan of all 29 committable files found nothing. `.env`, `.env.login`, `data/portal.db` are gitignored and 0600.
- Git: pushed to https://github.com/abhinavralhan/order-track-portal-a11 (public, branch main). Commit after every small change, **no Claude co-author lines**.
- Known: pytest shows 1 deprecation warning (starlette wants `httpx2` instead of `httpx`); the swap needs the user's approval.

## How to run
- Import: `uv run python -m portal.importer data/orders-2000.csv data/portal.db` -> 1,946 orders, 49 rejected, 3 duplicates removed.
- Portal: `uv run uvicorn portal.app:create_app --factory --env-file .env --no-access-log --no-server-header` -> http://localhost:8000 (Chrome/Firefox).
- Local login for the user: username `ceo`, password in `.env.login` (generated, never printed). New setups follow `.env.example`.

## What the portal does
- `/` Orders: "Needs your attention today" panel (promise misses, ship today, arrive today, stale-data banner; mailto reminders to the stage owner),
  stage pipeline, search (a rejected ID shows "on hold" + "Notify dev team"), 50 per page, owners list.
- `/orders/{id}`: stage timeline, owner, reminder. `/insights`: KPIs, per-day stacked status columns, why orders fail (holiday cause computed; on-hold
  reasons in plain words; ranked bars, not a pie), cumulative planned deliveries, orders by city. Server-rendered SVG, no JS.
- `/quality`: data import report for the dev team, one notify button. Data problems are kept off the CEO's main view (user decision).

## Decisions (agreed with the user)
- Stack: Python, FastAPI, Jinja2, SQLite (stdlib), pytest, uv. Pydantic beyond FastAPI's own use and async: judged overkill.
- Order data on the server only; pages `no-store`; strict CSP; no third-party requests. No prices/currency stored (random, no signal).
- Customers treated as B2B (one reseller "ACME", 12 sites): deliveries only on working days at the destination.
- Working days skip weekends and public holidays at the factory (NRW) and the destination state (`dates.holidays`). Table covers 2026-11-02..2027-03-25; outside is flagged.
- Ship date = ready date; statuses are **planned** (no actual events in the data). Events feed + reconciliation designed in `docs/design.md` §5, not built.
- Contacts: `contacts.toml` role mailboxes (placeholders). Reminders are mailto links: no SMTP secret, the server sends nothing.
- Auth: one CEO account (argon2 hash in `.env`); app refuses to start without secrets, contacts or DB. Production: SSO + MFA (design doc).

## Key findings
- Data: 15 defect types (BOM, shifted columns, decimal commas, `ten` as quantity, `2026-13-01`, conflicting duplicate IDs...). Rules in `docs/data-analysis.md`.
- 13 Saxony orders (ready 13 or 17 Nov) miss the 5-day promise because of Buß- und Bettag (Wed 18 Nov). Drones fly in hours, so Task B can still deliver them on time.
- Logistics: 7 zone loops save 35–42 % flight time; ~39 drone-h/day needed vs ~80 (daylight) / 240 (24 h). München and the South loop (9.3 h) exceed one daylight window.

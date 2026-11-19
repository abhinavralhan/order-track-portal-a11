# Development plan

Inputs: [research.md](research.md), [data-analysis.md](data-analysis.md). State and progress: [../MEMORY.md](../MEMORY.md).

## Architecture in one line

The CSV goes through the importer (validate, clean, compute dates) into SQLite. FastAPI renders HTML pages on the server for the logged-in CEO.
The browser only ever receives the page it asked for. Nothing is stored client-side.

## File layout (target)

```
pyproject.toml          deps pinned to exact versions, managed with uv
.env.example            placeholder config only, never real values
portal/
  dates.py              add_working_days() + NRW holiday set
  importer.py           CSV -> cleanup rules -> SQLite (atomic swap); CLI
  app.py                FastAPI: login/logout, orders, data-quality page, security headers
  templates/            base.html, login.html, orders.html, quality.html
  static/style.css      self-hosted, no CDN or web fonts
tests/
  test_dates.py  test_importer.py  test_app.py
docs/
  research.md  data-analysis.md  plan.md  task-b-algorithm.md  design.md
README.md  MEMORY.md  demo.gif
```

## Storage

- `data/portal.db` (SQLite, gitignored). Two tables:
  - `orders(order_id PK, sku, quantity, ready_date, ship_date, delivery_date, city)`. No price, currency or full postcode (minimisation).
  - `issues(line, order_id, action, reason)` where `action` is fixed, flagged or rejected. Order IDs and reasons only, never raw rows.
  - A `meta` row holding the import timestamp ("data as of").
- The import builds a new DB file, then atomically swaps it with `os.replace`. A failed import leaves the old data untouched, and running it twice gives the same result.
- Erasure: delete at the source (ERP) and re-import. Wiping everything = delete `data/portal.db`.

## Credentials and config

- Environment only, from `.env` (gitignored), loaded by `uvicorn --env-file`:
  `PORTAL_USER`, `PORTAL_PASSWORD_HASH` (argon2), `SESSION_SECRET`, `DB_PATH`.
- The app refuses to start if any value is missing. There are no default secrets.
- The password hash is generated with `getpass`, so the password never appears in shell history.
- Session cookie: signed, `HttpOnly`, `SameSite=Strict`, `Secure` when served over HTTPS. Logout is a POST.

## Phases (each one = small reviewed snippets, then a MEMORY.md update)

| # | Phase | Done when |
|---|---|---|
| 0 | Setup | `.gitignore`, `MEMORY.md` exist ✅ |
| 1 | Research | `research.md`, `data-analysis.md` reviewed ✅ |
| 2 | Plan | this file reviewed |
| 3 | Date logic: `dates.py` | Tests pass: Mon→Thu, Fri→Wed, Sat→Wed, Sun→Wed, a ready date just before Christmas skips 25/26 Dec |
| 4 | Import + cleanup: `importer.py` | One test per cleanup rule (small inline CSVs) and a full-file test with exact counts; `docs/data-analysis.md` updated with the exact counts |
| 5 | Portal: `app.py` + templates | Login, order search by ID, table with ship date / delivery date / status (planned, in transit, delivered vs. today), data-quality page, "data as of" |
| 6 | Security pass | Tests: redirect when not logged in, wrong password rejected, login rate-limited, startup fails without secrets, headers set (CSP `default-src 'self'`, `frame-ancestors 'none'`, `nosniff`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store`), access log without query strings |
| 7 | Task B: `task-b-algorithm.md` | Method + pseudocode (below) |
| 8 | Task C: `design.md` | System design, infrastructure diagram, data-flow diagram (Mermaid), failure modes, access control |
| 9 | Audit | `/ponytail-audit` run, findings fixed or noted as shortcuts |
| 10 | Deliverable | `demo.gif` (Playwright), crisp `README.md`, final `MEMORY.md`, secret scan (gitleaks) clean |

## Task B approach (to be written up in Phase 7)

1. Deadline per order = ready date + 5 days. An order can leave from its ready date onward.
2. Group orders by destination city. A trip takes one or more orders to one city (≤ 200 units). Flight time = 2 × distance / 100 km/h.
3. Greedy, earliest deadline first: each time a drone becomes free, send it to the city whose waiting orders have the least slack. Fill the trip in deadline order up to 200 units.
4. If an order can no longer make its deadline, drop it from the priority queue (it ships later, as a late order). This is Moore–Hodgson's idea: give up the fewest orders.
5. Upgrade path if the greedy result is not good enough: a CP-SAT model (OR-Tools) maximising Σ on-time orders. 2,000 orders is a small model.
6. Allow for the regulatory limits: flight-hour windows and no-fly zones reduce capacity.

## Task C approach (to be written up in Phase 8)

EU region (e.g. AWS eu-central-1 Frankfurt). Request path: identity provider (SSO/OIDC, MFA), then a load balancer with TLS and WAF, then the app container (ECS Fargate or Cloud Run, 2 instances), then managed Postgres (multi-AZ, private subnet, KMS encryption at rest, point-in-time recovery).
The importer runs as a scheduled job reading from the ERP export bucket. Secrets live in Secrets Manager. Logs and alerts contain no order data.
Deliberately not used: microservices, a distributed database, a cache. The data is small, has one source and is mostly read.

## Out of scope (skipped on purpose)

Editing orders, multiple user roles, CSV upload via UI, i18n, a live drone schedule in the portal.

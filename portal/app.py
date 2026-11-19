"""CEO portal.

Run: uv run uvicorn portal.app:create_app --factory --env-file .env --no-access-log --no-server-header
"""
import os
import secrets
import sqlite3
import time
import tomllib
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error
from fastapi import Depends, FastAPI, Form, HTTPException, Path as PathParam, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from portal import insights
from portal.insights import STAGES
from portal.dates import holidays
from portal.importer import CITIES, ORDER_ID

HERE = Path(__file__).parent
MAX_FAILS, FAIL_WINDOW = 5, 15 * 60


def berlin_today() -> date:
    return datetime.now(ZoneInfo("Europe/Berlin")).date()


def stage_of(order, today: str) -> str:
    if today < order["ready_date"]:
        return "In production"
    if today == order["ready_date"]:
        return "Ready to ship"
    if today < order["delivery_date"]:
        return "In transit"
    return "Delivered (planned)"


def misses_promise(o) -> bool:
    return (date.fromisoformat(o["delivery_date"]) - date.fromisoformat(o["ready_date"])).days > PROMISE_DAYS


# contacts.toml key -> stages that role owns
ROLES = {"production": "In production", "shipping": "Ready to ship, In transit", "customer": "Delivered (planned)", "data": "Order data import"}
STAGE_OWNER = {"In production": "production", "Ready to ship": "shipping", "In transit": "shipping", "Delivered (planned)": "customer"}
PROMISE_DAYS = 5
PAGE_SIZE = 50
STALE_HOURS = 24
SECURITY_HEADERS = {
    # Only our own CSS: no scripts, no third-party content, no framing (clickjacking).
    "Content-Security-Policy": "default-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; object-src 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",  # order IDs in URLs never leak to other sites
    "Cache-Control": "no-store",  # pages hold personal data: never keep them in browser or proxy caches
    "Strict-Transport-Security": "max-age=31536000",
}


def load_contacts(path):
    with open(path, "rb") as f:
        contacts = tomllib.load(f)
    for key in ROLES:
        c = contacts.get(key)
        if not (isinstance(c, dict) and c.get("role") and "@" in c.get("email", "")):
            raise SystemExit(f"{path}: [{key}] needs a role and an email")
    return contacts


def mailto(contact, subject, intro, ids):
    """A pre-filled email the CEO sends from her own mail app: no SMTP secret, nothing sent by the server."""
    # shortcut: lists at most 25 IDs so the mailto URL stays short enough for mail clients; the rest are counted.
    listed = ", ".join(ids[:25]) + (f" and {len(ids) - 25} more (see the portal)" if len(ids) > 25 else "")
    orders_line = f"Orders: {listed}\n" if ids else ""
    body = f"Hello {contact['role']},\n\n{intro}\n{orders_line}\nPlease reply with the status or an ETA.\n"
    return f"mailto:{contact['email']}?" + urlencode({"subject": subject, "body": body}, quote_via=quote)


def setting(name):
    value = os.environ.get(name, "")
    if not value:
        raise SystemExit(f"missing setting {name}: see .env.example")  # fail closed, never default a secret
    return value


def create_app():
    user = setting("PORTAL_USER")
    pw_hash = setting("PORTAL_PASSWORD_HASH")
    secret = setting("SESSION_SECRET")
    db_path = setting("DB_PATH")
    if len(secret) < 32:
        raise SystemExit("SESSION_SECRET must be at least 32 characters")
    if not pw_hash.startswith("$argon2"):
        raise SystemExit("PORTAL_PASSWORD_HASH must be an argon2 hash, not a password")
    if not Path(db_path).is_file():
        raise SystemExit(f"no data at {db_path}: run `python -m portal.importer <csv> {db_path}` first")

    contacts = load_contacts(HERE.parent / "contacts.toml")
    hasher = PasswordHasher()
    fails = {}  # shortcut: in-memory, per process; move to the IdP / a shared store when running more than one instance
    templates = Jinja2Templates(HERE / "templates")
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(SessionMiddleware, secret_key=secret, max_age=8 * 3600, same_site="strict", https_only=True)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        return response

    def db():
        # Read-only: the portal can never change order data.
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            yield con
        finally:
            con.close()

    def signed_in(request: Request):
        if request.session.get("user") != user:
            raise HTTPException(303, headers={"Location": "/login"})

    @app.get("/login")
    def login_form(request: Request):
        return templates.TemplateResponse(request, "login.html")

    @app.post("/login")
    def login(request: Request, username: str = Form(), password: str = Form()):
        ip = request.client.host if request.client else "?"
        now = time.monotonic()
        recent = [t for t in fails.get(ip, []) if now - t < FAIL_WINDOW]
        if len(recent) >= MAX_FAILS:
            return templates.TemplateResponse(request, "login.html", {"error": "Too many attempts. Try again in 15 minutes."}, 429)
        try:
            ok = hasher.verify(pw_hash, password)
        except Argon2Error:
            ok = False
        if ok and secrets.compare_digest(username.encode(), user.encode()):
            fails.pop(ip, None)
            request.session.clear()
            request.session["user"] = user
            return RedirectResponse("/", 303)
        fails[ip] = recent + [now]
        for old in [k for k, v in fails.items() if now - v[-1] >= FAIL_WINDOW]:
            del fails[old]  # keep memory bounded
        return templates.TemplateResponse(request, "login.html", {"error": "Wrong username or password."}, 401)

    @app.post("/logout")
    def logout(request: Request):
        request.session.clear()
        return RedirectResponse("/login", 303)

    @app.get("/", dependencies=[Depends(signed_in)])
    def home(request: Request, q: str = Query("", max_length=40), stage: str = "", page: int = Query(1, ge=1), con=Depends(db)):
        today = berlin_today().isoformat()
        meta = dict(con.execute("SELECT key, value FROM meta").fetchall())
        orders = [dict(r, stage=stage_of(r, today)) for r in con.execute("SELECT * FROM orders ORDER BY ready_date, order_id")]
        q, stage = q.strip().upper(), stage if stage in STAGES else ""
        ship_today = [o["order_id"] for o in orders if o["ready_date"] == today]
        arrive_today = [o["order_id"] for o in orders if o["delivery_date"] == today]
        late = [o["order_id"] for o in orders if misses_promise(o)]
        age_h = (datetime.now(ZoneInfo("UTC")) - datetime.fromisoformat(meta["imported_at"])).total_seconds() / 3600
        stale = age_h > STALE_HOURS and {
            "hours": round(age_h), "owner": contacts["data"],
            "href": mailto(contacts["data"], "Portal data is out of date",
                           f"The last order import was at {meta['imported_at']}. Please re-run the import.", []),
        }
        # (order ids, what, owner key, email subject, email intro); only non-empty items are shown.
        items = [
            (late, f"orders planned to miss the {PROMISE_DAYS}-day delivery promise", "shipping",
             "Orders at risk of missing the delivery promise", f"These orders are planned to arrive more than {PROMISE_DAYS} days after they are ready."),
            (ship_today, "orders planned to ship today", "shipping",
             f"Shipping today ({today})", "Please confirm these orders leave today."),
            (arrive_today, "orders planned to arrive today", "customer",
             f"Arriving today ({today})", "Please confirm receipt with the customer for these orders."),
        ]
        attention_items = [
            {"count": len(ids), "what": what, "owner": contacts[key], "href": mailto(contacts[key], subject, intro, ids)}
            for ids, what, key, subject, intro in items if ids
        ]
        shown = [o for o in orders if (not stage or o["stage"] == stage) and q in o["order_id"]]
        pages = max(1, -(-len(shown) // PAGE_SIZE))
        page = min(page, pages)
        link = lambda n: "/?" + urlencode({k: v for k, v in {"q": q, "stage": stage, "page": n}.items() if v})
        # A searched order the importer rejected is "on hold" for the CEO; the details are for the dev team.
        on_hold = [r[0] for r in con.execute("SELECT DISTINCT order_id FROM issues WHERE action = 'rejected' AND order_id IS NOT NULL")
                   if q and q in r[0]]
        return templates.TemplateResponse(request, "home.html", {
            "meta": meta, "today": today, "stages": STAGES, "stage": stage, "q": q,
            "counts": Counter(o["stage"] for o in orders),
            "attention_items": attention_items, "stale": stale,
            "contacts": [contacts[k] | {"stages": stages} for k, stages in ROLES.items()],
            "total": len(shown), "orders": shown[(page - 1) * PAGE_SIZE: page * PAGE_SIZE],
            "page": page, "pages": pages,
            "prev": link(page - 1) if page > 1 else None, "next": link(page + 1) if page < pages else None,
            "on_hold": [(oid, mailto(contacts["data"], f"Order {oid} on hold", f"The CEO asked about order {oid}, which is on hold because of a data error.", [oid]))
                        for oid in on_hold],
        })

    @app.get("/insights", dependencies=[Depends(signed_in)])
    def insights_page(request: Request, con=Depends(db)):
        today = berlin_today().isoformat()
        orders = [dict(r, stage=stage_of(r, today)) for r in con.execute("SELECT * FROM orders ORDER BY ready_date, order_id")]
        stages = Counter(o["stage"] for o in orders)
        late = sum(misses_promise(o) for o in orders)
        meta = dict(con.execute("SELECT key, value FROM meta").fetchall())
        if not orders:
            return templates.TemplateResponse(request, "insights.html", {"meta": meta, "today": today, "empty": True})
        return templates.TemplateResponse(request, "insights.html", {
            "meta": meta, "today": today,
            "kpi": {"total": len(orders), "delivered": stages["Delivered (planned)"], "late": late,
                    "on_promise": 100 * (len(orders) - late) / len(orders) if orders else 0,
                    "last": max((o["delivery_date"] for o in orders), default="-")},
            "daily": insights.daily(orders, today, misses_promise),
            "cum": insights.cumulative(orders, today),
            "cities": insights.by_city(orders),
            "fail": insights.failures(
                orders, con.execute("SELECT reason FROM issues WHERE action = 'rejected'").fetchall(),
                misses_promise, lambda o: holidays(CITIES[o["postcode"]][1])),
        })

    @app.get("/orders/{order_id}", dependencies=[Depends(signed_in)])
    def order(request: Request, order_id: str = PathParam(pattern=f"^{ORDER_ID}$"), con=Depends(db)):
        o = con.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
        if not o:
            return RedirectResponse(f"/?q={quote(order_id)}", 303)  # search explains rejected or unknown IDs
        o = dict(o, stage=stage_of(o, berlin_today().isoformat()))
        owner = contacts[STAGE_OWNER[o["stage"]]]
        intro = (f"Order {o['order_id']} ({o['quantity']} x {o['sku']} to {o['city']} {o['postcode']}) is '{o['stage']}'. "
                 f"Planned ship date {o['ready_date']}, planned delivery {o['delivery_date']}.")
        return templates.TemplateResponse(request, "order.html", {
            "meta": dict(con.execute("SELECT key, value FROM meta").fetchall()),
            "o": o, "stages": STAGES, "current": STAGES.index(o["stage"]), "owner": owner,
            "remind": mailto(owner, f"Status of order {o['order_id']}", intro, [o["order_id"]]),
        })

    @app.get("/quality", dependencies=[Depends(signed_in)])
    def quality(request: Request, con=Depends(db)):
        issues = con.execute("SELECT line, order_id, action, reason FROM issues ORDER BY action DESC, line").fetchall()
        open_refs = sorted({i["order_id"] or f"(no id, line {i['line']})" for i in issues if i["action"] != "fixed"})
        counts = Counter(i["action"] for i in issues)
        return templates.TemplateResponse(request, "quality.html", {
            "meta": dict(con.execute("SELECT key, value FROM meta").fetchall()),
            "issues": issues, "owner": contacts["data"], "counts": counts,
            "notify": mailto(contacts["data"], "Order import: rows to fix at the source",
                             f"The last import rejected {counts['rejected']} rows and flagged {counts['flagged']}. "
                             "Details: portal page /quality.", open_refs),
        })

    return app

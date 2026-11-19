import io
from datetime import date

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from portal.app import create_app, load_contacts, mailto, stage_of
from portal.importer import load, write_db

CSV = ("external_order_id,sku,quantity,unit_price,currency,ready_to_ship_date,delivery_postcode\n"
       "ACME-00001,SKU-10419,26,162.61,EUR,2026-11-06,28195\n"   # delivered 11 Nov
       "ACME-00002,SKU-10420,10,10.00,EUR,2026-12-01,10115\n"    # still in production
       "ACME-00003,SKU-10421,ten,10.00,EUR,2026-12-01,10115\n"   # rejected by importer
       "ACME-00004,SKU-10422,5,10.00,EUR,2026-11-19,20095\n")    # ships today


@pytest.fixture
def env(tmp_path, monkeypatch):
    db = str(tmp_path / "portal.db")
    write_db(db, *load(io.StringIO(CSV)), "test.csv")
    values = {
        "PORTAL_USER": "ceo",
        "PORTAL_PASSWORD_HASH": PasswordHasher().hash("correct horse"),
        "SESSION_SECRET": "x" * 32,
        "DB_PATH": db,
    }
    for k, v in values.items():
        monkeypatch.setenv(k, v)
    return values


@pytest.fixture
def client(env, monkeypatch):
    monkeypatch.setattr("portal.app.berlin_today", lambda: date(2026, 11, 19))
    return TestClient(create_app(), base_url="https://testserver", follow_redirects=False)


def login(client, password="correct horse", username="ceo"):
    return client.post("/login", data={"username": username, "password": password})


@pytest.mark.parametrize("name", ["PORTAL_USER", "PORTAL_PASSWORD_HASH", "SESSION_SECRET", "DB_PATH"])
def test_refuses_to_start_without_setting(env, monkeypatch, name):
    monkeypatch.delenv(name)
    with pytest.raises(SystemExit):
        create_app()


@pytest.mark.parametrize("name, value", [("SESSION_SECRET", "short"), ("PORTAL_PASSWORD_HASH", "plaintext")])
def test_refuses_weak_settings(env, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(SystemExit):
        create_app()


def test_pages_require_login(client):
    r = client.get("/")
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_wrong_password_rejected(client):
    assert login(client, "nope").status_code == 401
    assert client.get("/").status_code == 303


def test_wrong_username_rejected(client):
    assert login(client, username="admin").status_code == 401


def test_login_then_logout(client):
    assert login(client).status_code == 303
    assert client.get("/").status_code == 200
    client.post("/logout")
    assert client.get("/").status_code == 303


def test_session_cookie_flags(client):
    cookie = login(client).headers["set-cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=strict" in cookie


def test_login_rate_limited(client):
    for _ in range(5):
        login(client, "nope")
    assert login(client).status_code == 429  # even the right password is blocked


@pytest.mark.parametrize("today, expected", [
    ("2026-11-05", "In production"),
    ("2026-11-06", "Ready to ship"),
    ("2026-11-10", "In transit"),
    ("2026-11-11", "Delivered (planned)"),
])
def test_stage_of(today, expected):
    assert stage_of({"ready_date": "2026-11-06", "delivery_date": "2026-11-11"}, today) == expected


def test_orders_page_shows_stages_and_dates(client):
    login(client)
    html = client.get("/").text
    assert "ACME-00001" in html and "2026-11-11" in html and "Delivered (planned)" in html
    assert "ACME-00002" in html and "In production" in html


def test_search_and_stage_filter(client):
    login(client)
    assert "ACME-00002" not in client.get("/?q=acme-00001").text
    assert "ACME-00001" not in client.get("/?stage=In production").text


def test_search_explains_rejected_order(client):
    login(client)
    html = client.get("/?q=ACME-00003").text
    assert "ACME-00003 is on hold" in html and "mailto:dev-team@example.com" in html


def test_search_input_length_limited(client):
    login(client)
    assert client.get("/?q=" + "A" * 41).status_code == 422


def test_quality_page(client):
    assert client.get("/quality").status_code == 303
    login(client)
    html = client.get("/quality").text
    assert "ACME-00003" in html and "rejected" in html


def test_contacts_need_every_role(tmp_path):
    bad = tmp_path / "contacts.toml"
    bad.write_text('[production]\nrole = "Production lead"\nemail = "production@example.com"\n')
    with pytest.raises(SystemExit):
        load_contacts(bad)


def test_mailto_lists_at_most_25_ids():
    href = mailto({"role": "Ops", "email": "ops@example.com"}, "S", "Intro.", [f"ACME-{i:05}" for i in range(30)])
    assert href.startswith("mailto:ops@example.com?subject=S&body=")
    assert "ACME-00024" in href and "ACME-00025" not in href and "and%205%20more" in href


def test_attention_panel_has_owner_reminders(client):
    login(client)
    html = client.get("/").text
    assert "Needs your attention today" in html
    assert "dev-team@example.com?subject=Blocked" not in html  # data problems stay off the CEO view
    assert "1</span> orders planned to ship today" in html and "mailto:drone-ops@example.com" in html


def test_order_detail_timeline_and_reminder(client):
    login(client)
    html = client.get("/orders/ACME-00001").text
    assert 'aria-current="step"' in html and "Delivered (planned)" in html
    assert "mailto:customer-service@example.com?subject=Status%20of%20order%20ACME-00001" in html


def test_order_detail_unknown_or_rejected_goes_to_search(client):
    login(client)
    r = client.get("/orders/ACME-00003")
    assert r.status_code == 303 and r.headers["location"] == "/?q=ACME-00003"


def test_order_detail_rejects_odd_ids(client):
    login(client)
    assert client.get("/orders/a%20b").status_code == 422


def test_quality_page_has_reminders(client):
    login(client)
    assert "mailto:dev-team@example.com?subject=Order%20import" in client.get("/quality").text


def test_refuses_to_start_without_database(env, monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "missing.db"))
    with pytest.raises(SystemExit):
        create_app()


def test_security_headers_on_every_response(client):
    for r in (client.get("/login"), client.get("/")):
        assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
        assert r.headers["cache-control"] == "no-store" and r.headers["referrer-policy"] == "no-referrer"
        assert r.headers["x-content-type-options"] == "nosniff"


def test_pagination_50_per_page(env, monkeypatch, tmp_path):
    rows = "".join(f"ACME-{i:05},SKU-1,1,1.00,EUR,2026-11-06,28195\n" for i in range(1, 61))
    db = str(tmp_path / "many.db")
    write_db(db, *load(io.StringIO(CSV.splitlines(True)[0] + rows)), "many.csv")
    monkeypatch.setenv("DB_PATH", db)
    c = TestClient(create_app(), base_url="https://testserver")
    login(c)
    p1, p2 = c.get("/").text, c.get("/?page=2").text
    assert p1.count('href="/orders/') == 50 and "page 1 of 2" in p1 and "ACME-00051" in p2 and "ACME-00050" not in p2
    assert c.get("/?page=99").status_code == 200  # clamped to the last page


def test_stale_data_banner(client, env):
    import sqlite3
    con = sqlite3.connect(env["DB_PATH"])
    with con:
        con.execute("UPDATE meta SET value = '2026-01-01T00:00:00+00:00' WHERE key = 'imported_at'")
    login(client)
    assert "Figures may be out of date" in client.get("/").text


def test_insights_page(client):
    assert client.get("/insights").status_code == 303
    login(client)
    html = client.get("/insights").text
    assert "Orders in plan" in html and "Why some orders fail" in html and "Invalid quantity" in html


def test_failure_reason_names_the_holiday():
    from portal.dates import holidays
    from portal.insights import failures, plain
    o = {"ready_date": "2026-11-13", "delivery_date": "2026-11-19", "city": "Dresden", "postcode": "01067", "stage": "In transit"}
    f = failures([o], [{"reason": "missing order id"}], lambda _: True, lambda _: holidays("SN"))
    assert f["causes"] == [("Public holiday at destination (Wed 18 Nov)", 1)] and f["late_cities"] == ["Dresden"]
    assert plain("order id also on line 7 with different content") == "Same order ID with conflicting details"
    assert plain("8 fields, expected 7") == "Malformed row in the order export"


def test_insights_with_no_orders_does_not_crash(env, monkeypatch, tmp_path):
    db = str(tmp_path / "empty.db")
    write_db(db, *load(io.StringIO(CSV.splitlines(True)[0] + "ACME-00009,SKU-1,ten,1.00,EUR,2026-11-06,28195\n")), "empty.csv")
    monkeypatch.setenv("DB_PATH", db)
    c = TestClient(create_app(), base_url="https://testserver")
    login(c)
    r = c.get("/insights")
    assert r.status_code == 200 and "No orders imported yet" in r.text

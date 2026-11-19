import io
import os
import sqlite3

import pytest

from portal.importer import load, write_db

HEAD = "external_order_id,sku,quantity,unit_price,currency,ready_to_ship_date,delivery_postcode\n"
OK = "ACME-00001,SKU-10419,26,162.61,EUR,2026-11-06,28195"


def run(*lines):
    return load(io.StringIO(HEAD + "\n".join(lines) + "\n"))


def test_valid_row_gets_city_and_delivery_date():
    orders, issues = run(OK)
    assert orders["ACME-00001"] == {
        "order_id": "ACME-00001", "sku": "SKU-10419", "quantity": 26,
        "ready_date": "2026-11-06", "delivery_date": "2026-11-11",
        "postcode": "28195", "city": "Bremen",
    }
    assert issues == []


@pytest.mark.parametrize("line, reason", [
    ("ACME-00002,SKU-1,26,1.00,EUR,2026-11-06,28195,Berlin", "8 fields, expected 7"),
    ("ACME-00002,33,38.11,EUR,2026-11-09,90402", "6 fields, expected 7"),
    (",SKU-1,26,1.00,EUR,2026-11-06,28195", "missing order id"),
    ("ACME-00002,,26,1.00,EUR,2026-11-06,28195", "missing or invalid sku"),
    ("ACME-00002,SKU-1,ten,1.00,EUR,2026-11-06,28195", "quantity is not a positive whole number"),
    ("ACME-00002,SKU-1,1.5,1.00,EUR,2026-11-06,28195", "quantity is not a positive whole number"),
    ("ACME-00002,SKU-1,0,1.00,EUR,2026-11-06,28195", "quantity is not a positive whole number"),
    ("ACME-00002,SKU-1,-5,1.00,EUR,2026-11-06,28195", "quantity is not a positive whole number"),
    ("ACME-00002,SKU-1,26,1.00,EUR,2026-13-01,28195", "missing or invalid ready_to_ship_date"),
    ("ACME-00002,SKU-1,26,1.00,EUR,,28195", "missing or invalid ready_to_ship_date"),
    ("ACME-00002,SKU-1,26,1.00,EUR,2026-11-06,99999", "unknown delivery_postcode"),
])
def test_rejected(line, reason):
    orders, issues = run(line)
    assert orders == {}
    assert issues[-1][2:] == ("rejected", reason)


@pytest.mark.parametrize("line, action, reason", [
    ("ACME-00002,SKU-1,26,171,15,EUR,2026-11-06,28195", "fixed", "decimal comma in unit_price"),
    ("ACME-00002,SKU-1,26,1.00,eur,2026-11-06,28195", "fixed", "currency upper-cased"),
    ("ACME-00002,SKU-1,26,1.00,EUR,06.11.2026,28195", "fixed", "date DD.MM.YYYY converted"),
    ("ACME-00002,SKU-1,26,1.00,,2026-11-06,28195", "flagged", "missing currency"),
])
def test_kept_with_note(line, action, reason):
    orders, issues = run(line)
    assert orders["ACME-00002"]["ready_date"] == "2026-11-06"
    assert issues == [(2, "ACME-00002", action, reason)]


def test_exact_duplicate_kept_once():
    orders, issues = run(OK, OK)
    assert list(orders) == ["ACME-00001"]
    assert issues == [(3, "ACME-00001", "fixed", "exact duplicate of line 2, removed")]


def test_conflicting_duplicates_all_rejected():
    orders, issues = run(OK, OK.replace("28195", "10115"))
    assert orders == {}
    assert [i[2] for i in issues] == ["rejected", "rejected"]


def test_blank_lines_skipped():
    orders, issues = run("", OK, "")
    assert list(orders) == ["ACME-00001"] and issues == []


def test_wrong_header_imports_nothing():
    with pytest.raises(SystemExit):
        load(io.StringIO("id,qty\n1,2\n"))


def test_full_file_every_row_accounted_for():
    with open("data/orders-2000.csv", encoding="utf-8-sig", newline="") as f:
        orders, issues = load(f)
    rejected = {i[0] for i in issues if i[2] == "rejected"}
    removed = {i[0] for i in issues if i[3].startswith("exact duplicate")}
    assert (len(orders), len(rejected), len(removed)) == (1946, 49, 3)
    assert len(orders) + len(rejected) + len(removed) == 2000 - 2  # minus 2 blank lines


def test_write_db_is_private_and_atomic(tmp_path):
    db = str(tmp_path / "portal.db")
    orders, issues = run(OK)
    write_db(db, orders, issues, "x.csv")
    assert os.stat(db).st_mode & 0o777 == 0o600
    bad = {"X": dict(orders["ACME-00001"], order_id="X", quantity=0)}  # violates CHECK
    with pytest.raises(sqlite3.IntegrityError):
        write_db(db, bad, [], "x.csv")
    con = sqlite3.connect(db)
    assert con.execute("SELECT order_id FROM orders").fetchall() == [("ACME-00001",)]
    assert not os.path.exists(db + ".tmp")


def test_date_outside_holiday_calendar_flagged():
    orders, issues = run("ACME-00002,SKU-1,26,1.00,EUR,2027-06-01,28195")
    assert "ACME-00002" in orders
    assert issues == [(2, "ACME-00002", "flagged", "date outside the holiday calendar, delivery date may be off")]


def test_duplicate_differing_only_in_case_is_kept_once():
    orders, issues = run(OK, OK.replace("EUR", "eur"))
    assert list(orders) == ["ACME-00001"] and issues[0][2] == "fixed"


def test_order_id_the_portal_cannot_link_is_rejected():
    orders, issues = run("ACME/001,SKU-1,26,1.00,EUR,2026-11-06,28195")
    assert orders == {} and issues[0][3] == "invalid order id (letters, digits and dashes only)"

"""Import the orders CSV into SQLite, applying the cleanup rules in docs/data-analysis.md.

Usage: python -m portal.importer data/orders-2000.csv data/portal.db
"""
import csv
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone

from portal.dates import COVERED, add_working_days

ORDER_ID = r"[A-Za-z0-9-]{1,40}"  # the portal links orders by this pattern
HEADER = ["external_order_id", "sku", "quantity", "unit_price", "currency", "ready_to_ship_date", "delivery_postcode"]
# postcode -> (city, state code for holidays)
CITIES = {
    "01067": ("Dresden", "SN"), "04109": ("Leipzig", "SN"), "10115": ("Berlin", "BE"),
    "20095": ("Hamburg", "HH"), "28195": ("Bremen", "HB"), "30159": ("Hannover", "NI"),
    "44135": ("Dortmund", "NW"), "50667": ("Köln", "NW"), "60311": ("Frankfurt am Main", "HE"),
    "70173": ("Stuttgart", "BW"), "80331": ("München", "BY"), "90402": ("Nürnberg", "BY"),
}
SCHEMA = """
CREATE TABLE orders (
    order_id TEXT PRIMARY KEY,
    sku TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    ready_date TEXT NOT NULL,
    delivery_date TEXT NOT NULL,
    postcode TEXT NOT NULL,
    city TEXT NOT NULL
);
CREATE TABLE issues (
    line INTEGER NOT NULL,
    order_id TEXT,
    action TEXT NOT NULL CHECK (action IN ('fixed', 'flagged', 'rejected')),
    reason TEXT NOT NULL
);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


class Rejected(Exception):
    pass


def clean_row(fields, notes):
    """Return the order as a dict, appending (action, reason) to notes. Raises Rejected."""
    f = [x.strip() for x in fields]
    # An unquoted decimal comma ("171,15") splits unit_price into two fields.
    if len(f) == 8 and f[3].isdigit() and re.fullmatch(r"\d\d", f[4]):
        f[3:5] = [f"{f[3]}.{f[4]}"]
        notes.append(("fixed", "decimal comma in unit_price"))
    if len(f) != 7:
        raise Rejected(f"{len(f)} fields, expected 7")
    oid, sku, qty, _price, cur, ready, pc = f
    if not oid:
        raise Rejected("missing order id")
    if not re.fullmatch(ORDER_ID, oid):
        raise Rejected("invalid order id (letters, digits and dashes only)")
    if not re.fullmatch(r"SKU-\d+", sku):
        raise Rejected("missing or invalid sku")
    if not re.fullmatch(r"\d+", qty) or int(qty) == 0:
        raise Rejected("quantity is not a positive whole number")
    try:
        ready_date = datetime.strptime(ready, "%Y-%m-%d").date()
    except ValueError:
        try:
            ready_date = datetime.strptime(ready, "%d.%m.%Y").date()
            notes.append(("fixed", "date DD.MM.YYYY converted"))
        except ValueError:
            raise Rejected("missing or invalid ready_to_ship_date") from None
    if pc not in CITIES:
        raise Rejected("unknown delivery_postcode")
    if not cur:
        notes.append(("flagged", "missing currency"))
    elif cur != cur.upper():
        notes.append(("fixed", "currency upper-cased"))
    city, state = CITIES[pc]
    delivery = add_working_days(ready_date, 3, state)
    if not (COVERED[0] <= ready_date and delivery <= COVERED[1]):
        notes.append(("flagged", "date outside the holiday calendar, delivery date may be off"))
    return {
        "order_id": oid, "sku": sku, "quantity": int(qty),
        "ready_date": ready_date.isoformat(), "delivery_date": delivery.isoformat(),
        "postcode": pc, "city": city,
    }


def load(f):
    """Parse an open CSV file. Return (orders by id, issues as (line, order_id, action, reason))."""
    reader = csv.reader(f)
    if [h.strip() for h in next(reader, [])] != HEADER:
        raise SystemExit("unexpected CSV header, nothing imported")
    orders, issues, seen, conflicts = {}, [], {}, set()
    for fields in reader:
        line = reader.line_num
        stripped = [x.strip() for x in fields]
        if not any(stripped):
            continue
        oid = stripped[0]
        if oid and oid in seen:
            first_line, first = seen[oid]
            if [x.upper() for x in stripped] == [x.upper() for x in first]:  # 'eur' and 'EUR' twins are the same row
                issues.append((line, oid, "fixed", f"exact duplicate of line {first_line}, removed"))
            else:
                conflicts.add(oid)
                issues.append((line, oid, "rejected", f"order id also on line {first_line} with different content"))
            continue
        seen[oid] = (line, stripped)
        notes = []
        try:
            orders[oid] = clean_row(fields, notes)
        except Rejected as e:
            notes.append(("rejected", str(e)))
        issues += [(line, oid or None, action, reason) for action, reason in notes]
    for oid in sorted(conflicts):
        if orders.pop(oid, None):
            issues.append((seen[oid][0], oid, "rejected", "order id used for conflicting rows"))
    return orders, sorted(issues)


def write_db(path, orders, issues, source):
    """Build the DB in a temp file, then swap it in, so a failed import keeps the old data."""
    tmp = path + ".tmp"
    if os.path.exists(tmp):
        os.remove(tmp)
    con = sqlite3.connect(tmp)
    try:
        os.chmod(tmp, 0o600)  # personal data: owner-only
        with con:
            con.executescript(SCHEMA)
            con.executemany(
                "INSERT INTO orders VALUES (:order_id, :sku, :quantity, :ready_date, :delivery_date, :postcode, :city)",
                orders.values())
            con.executemany("INSERT INTO issues VALUES (?, ?, ?, ?)", issues)
            con.executemany("INSERT INTO meta VALUES (?, ?)", [
                ("imported_at", datetime.now(timezone.utc).isoformat(timespec="seconds")),
                ("source", os.path.basename(source)),
            ])
        con.close()
        os.replace(tmp, path)
    except BaseException:
        con.close()
        os.remove(tmp)
        raise


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    src, dst = sys.argv[1:]
    with open(src, encoding="utf-8-sig", newline="") as f:
        orders, issues = load(f)
    write_db(dst, orders, issues, src)
    rejected = len({i[0] for i in issues if i[2] == "rejected"})
    # Counts only: never print order data to logs.
    print(f"imported {len(orders)} orders, rejected {rejected} rows, {len(issues)} issues recorded -> {dst}")

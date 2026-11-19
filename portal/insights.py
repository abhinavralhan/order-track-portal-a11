"""Chart data for the CEO insights tab: geometry computed here, drawn as plain SVG by the template (no JavaScript)."""
from collections import Counter
from datetime import date, timedelta

# Pipeline stages in order; ship date = ready date, delivery = ready + 3 working days.
STAGES = ["In production", "Ready to ship", "In transit", "Delivered (planned)"]
# Bottom -> top of each column: the pipeline (one blue ramp), then the exception (status red).
SERIES = STAGES[::-1] + ["Misses 5-day promise"]
CLASS = dict(zip(SERIES, ["s-delivered", "s-transit", "s-ready", "s-production", "s-risk"]))
W, H, LEFT, BOTTOM, TOP = 960, 280, 48, 30, 16
GAP = 2  # surface gap between stacked segments


def axis(vmax):
    """Clean y-axis: top value and ticks, at most 5 steps."""
    step = next(s for s in (1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000) if vmax / s <= 5)
    top = max(step, -(-vmax // step) * step)
    return top, list(range(0, top + 1, step))


def column(x, y, w, h, rounded):
    """A bar segment; the top one gets 4px rounded corners, square at the bottom."""
    r = min(4, w / 2, h) if rounded else 0
    return f"M{x:.1f},{y + h:.1f} V{y + r:.1f} Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f} H{x + w - r:.1f} Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f} V{y + h:.1f} Z"


def daily(orders, today, late):
    """Stacked column per ship (= ready) day, split by status."""
    per_day = {}
    for o in orders:
        per_day.setdefault(o["ready_date"], Counter())["Misses 5-day promise" if late(o) else o["stage"]] += 1
    days = sorted(per_day)
    top, ticks = axis(max(sum(c.values()) for c in per_day.values()))
    plot_w, plot_h = W - LEFT - 8, H - TOP - BOTTOM
    band = plot_w / len(days)
    bar = min(24, band * 0.7)
    scale = plot_h / top
    cols = []
    for i, d in enumerate(days):
        x, y = LEFT + i * band + (band - bar) / 2, H - BOTTOM
        present = [s for s in SERIES if per_day[d][s]]
        segs = []
        for s in present:
            h = per_day[d][s] * scale
            y -= h
            segs.append({"cls": CLASS[s], "d": column(x, y, bar, max(h - GAP, 1), s == present[-1])})
        label = f"{d}: {per_day[d].total()} orders, " + ", ".join(f"{per_day[d][s]} {s.lower()}" for s in present)
        cols.append({"day": d, "x": x + bar / 2, "segs": segs, "label": label,
                     "tick": i % 7 == 0, "today": d == today})
    return {"cols": cols, "yticks": [(t, H - BOTTOM - t * scale) for t in ticks], "series": SERIES, "classes": CLASS,
            "table": [(d, [per_day[d][s] for s in SERIES], per_day[d].total()) for d in days]}


def cumulative(orders, today):
    """Planned deliveries, cumulative by delivery date (one series)."""
    per_day = Counter(o["delivery_date"] for o in orders)
    days, run, points = sorted(per_day), 0, []
    top, ticks = axis(len(orders))
    plot_w, plot_h = W - LEFT - 80, H - TOP - BOTTOM
    for i, d in enumerate(days):
        run += per_day[d]
        points.append((d, run, LEFT + i * plot_w / max(len(days) - 1, 1), H - BOTTOM - run * plot_h / top))
    done = [p for p in points if p[0] <= today]
    return {"path": "M" + " L".join(f"{x:.1f},{y:.1f}" for _, _, x, y in points),
            "now": done[-1] if done else None, "end": points[-1],
            "yticks": [(t, H - BOTTOM - t * plot_h / top) for t in ticks],
            "xticks": [(d, x) for i, (d, _, x, _) in enumerate(points) if i % 7 == 0]}


def by_city(orders):
    """Ranked horizontal bars: orders per destination, largest first."""
    counts = Counter(o["city"] for o in orders).most_common()
    top = counts[0][1]
    units = Counter()
    for o in orders:
        units[o["city"]] += o["quantity"]
    return [{"city": c, "n": n, "units": units[c], "y": i * 26, "w": max(n / top * 520, 2)} for i, (c, n) in enumerate(counts)]


# Importer reasons (dev wording) -> plain words for the CEO. First match wins.
PLAIN = [
    ("quantity", "Invalid quantity"),
    ("missing or invalid ready", "Missing or invalid ready date"),
    ("missing order id", "Missing order ID"),
    ("invalid order id", "Invalid order ID"),
    ("missing or invalid sku", "Missing product code (SKU)"),
    ("order id", "Same order ID with conflicting details"),
    ("unknown delivery_postcode", "Unknown destination"),
]


def plain(reason):
    return next((text for start, text in PLAIN if reason.startswith(start)), "Malformed row in the order export")


def failures(orders, rejected, late, closed_on):
    """Why orders fail: promise misses explained by the closed days in their delivery window, plus on-hold rows by plain reason."""
    causes, cities = Counter(), Counter()
    for o in (o for o in orders if late(o)):
        ready, delivery = date.fromisoformat(o["ready_date"]), date.fromisoformat(o["delivery_date"])
        holidays = [d for d in (ready + timedelta(days=i) for i in range(1, (delivery - ready).days)) if d in closed_on(o)]
        causes["Public holiday at destination (" + ", ".join(f"{d:%a %d %b}" for d in holidays) + ")" if holidays
               else "Weekend plus 3 working days runs past 5 days"] += 1
        cities[o["city"]] += 1
    on_hold = Counter(plain(r["reason"]) for r in rejected)
    rows = [("Misses 5-day promise", c, n) for c, n in causes.most_common()] + [("On hold", c, n) for c, n in on_hold.most_common()]
    top = max((n for _, _, n in rows), default=1)
    return {
        "late": sum(causes.values()), "late_cities": [c for c, _ in cities.most_common()], "causes": causes.most_common(),
        "on_hold": sum(on_hold.values()),
        "bars": [{"group": g, "reason": c, "n": n, "y": i * 26, "w": max(n / top * 420, 2)} for i, (g, c, n) in enumerate(rows)],
    }

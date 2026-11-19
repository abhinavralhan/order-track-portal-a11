# Task B: maximise orders delivered within 5 days of ready_to_ship

No implementation required by the README. This is the method, the pseudocode, and what to expect on this data.
Numbers come from [data-analysis.md](data-analysis.md).

## 1. Problem

- Each order `o` has a ready date `r(o)`, a quantity `q(o)` ≤ 48, and a destination city.
- Promise: delivered by the deadline `d(o) = r(o) + 5 calendar days`, on a day the destination is open (B2B: Mon–Fri, no public holiday in that state).
- Fleet: 10 drones, 200 units each, 100 km/h, unlimited range, all based in Detmold.
- Flight window: assume **daylight only** (about 8 h/day in Nov/Dec) unless the operating permit allows night flights. This is the safe case (see the regulation notes in data-analysis.md).
- Goal: maximise the number of orders with delivery ≤ `d(o)`. Secondary goal: fewest drone-hours.

## 2. What the data tells us before designing anything

- Demand is about 47 orders and 1,170 units a day, to 12 cities that are 76–464 km away.
- Sharing trips is what matters. Flying one drone per order needs about 235 drone-hours a day. Flying **one loop per zone** needs about 39 drone-hours a day, against about 80 available in daylight.
- Seven zones, each flown as one loop (35–42 % shorter than separate trips): Near (Hannover), West (Dortmund + Köln), North (Bremen + Hamburg),
  East-1 (Leipzig + Dresden), East-2 (Berlin), South-West (Frankfurt + Stuttgart), South (Nürnberg + München).
- The one hard limit: the South loop and a single München trip take 9.3 h, longer than one daylight window.
- Conclusion: on today's volume the promise is reachable for practically every order. The algorithm matters when volume grows, flight windows shrink, or drones fail.

## 3. Method: daily rolling plan, earliest deadline first, filling zone loops

Every morning (and after any disruption) re-plan from the current state. The planner is idempotent: the same state always gives the same plan.

1. **Candidates for today:** orders that are ready (`r(o) ≤ today`), not yet shipped, not on hold for data errors, and whose destination is open today.
2. **Latest departure** per order: the last flight window, on a day the destination is open, whose arrival is ≤ `d(o)`.
   `slack(o)` = days between today and that latest departure.
3. **Priority classes** (highest first):
   1. `slack = 0`: must fly today or the promise is lost.
   2. Past the 3-working-day target but still within the promise: ship today. This is the SLA rule: anything past day 3 goes out immediately.
   3. Everything else: may wait for a fuller loop, but never beyond the day-3 target.
   4. Doomed orders (cannot make `d(o)` any more): fly only with spare capacity. Giving up the fewest orders is Moore–Hodgson's idea.
4. **Build trips per zone:** sort the zone's candidates by (class, slack). Fill drones up to 200 units in that order (first fit).
   One zone may need several drones on a heavy day.
5. **Assign trips to drones:** longest trips first, each to the drone that frees up earliest (the LPT rule), and only if the trip lands before the window ends.
   Trips that don't fit move to tomorrow. Their orders keep their priority, so tomorrow they come first.
6. **If today's must-fly orders (class 1) do not all fit:** drop the trip that saves the fewest on-time orders per drone-hour (far, half-empty loops first). Repeat until the plan fits.
   This is the Moore–Hodgson step: sacrifice the fewest orders, not the latest ones.

### Pseudocode

```
plan_day(today, orders, drones, window):
    cand = [o for o in orders if o.ready <= today and not o.shipped
                                and not o.on_hold and open(o.city, today)]
    for o in cand:
        o.latest = last_departure(o, window)          # respects destination calendar
        o.cls = 1 if o.latest == today
                else 2 if today > target_day3(o)
                else 4 if o.latest < today
                else 3
    trips = []
    for zone, group in group_by(cand, key=zone_of):
        queue = sort(group, key=(cls, latest))
        while queue:
            load = take_while_fits(queue, capacity=200)   # first fit by priority
            if all(o.cls == 3 for o in load) and not fills(load) and can_wait(load, today):
                break                                     # hold for a fuller loop (never past day 3)
            trips.append(Trip(zone, load, hours=loop_km(zone, load) / 100 + stops(load) * HANDLING))
    trips = sort(trips, key=hours, descending=True)       # LPT: long trips first
    for t in trips:
        d = drone_free_earliest(drones)
        if d.free_at + t.hours <= window.end: assign(t, d)
        else: defer(t)                                    # stays top priority tomorrow
    while unassigned_class1(trips):                       # Moore-Hodgson step
        drop(trip with fewest class-1 orders saved per drone-hour)
        reassign()
    return assigned trips
```

Cost: sorting about 50 candidates a day per zone, so milliseconds. It runs again after each disruption.

## 4. Optimal variant (if the greedy plan is not good enough)

The data is small enough to solve exactly with an integer program (OR-Tools CP-SAT or any MILP solver) by grouping orders by zone and day:

- `x[o, t] ∈ {0,1}`: order `o` flies on day `t` (only `t ≥ r(o)` and destination open on `t`).
- `n[z, t] ∈ ℕ`: number of loops to zone `z` on day `t`.
- Capacity: `Σ q(o)·x[o,t] for o in z ≤ 200 · n[z,t]`.
- Fleet time: `Σ hours(z) · n[z,t] ≤ 10 · window_hours(t)`. A loop longer than the window is allowed only if night flights are permitted.
- Each order flies once: `Σ_t x[o,t] = 1` (on time or late).
- Objective: maximise `Σ on_time(o)`, where `on_time(o) = Σ_{t ≤ latest(o)} x[o,t]`, minus a small weight × drone-hours.

That is about 2,000 × 6 binary variables (the plausible flight days per order), which solves in seconds. Use the greedy plan as the starting solution and as the fallback if the solver times out.

## 5. Edge cases handled by the design

- **Destination calendars:** a delivery must land on an open day in that state. Example: Saxony is closed on Buß- und Bettag, 18 Nov.
  Because a flight takes hours, drones can still deliver the 13 Saxony orders that Task A's 3-working-day rule makes late, so they arrive on time.
- **Daylight-only windows:** München and the South loop (9.3 h) cannot round-trip in one window. Options: a night authorisation for the return leg only, an overnight stop at a southern site, or splitting into two shorter flights.
- **Orders > 200 units** (none today): split across drones and count the order on time only when the last part arrives.
- **No-fly zones** (city centres, airports): use real route distances instead of straight lines. Times only get longer, so keep 10–15 % spare capacity.
- **Drone failure or weather:** re-plan with fewer drones. The priority classes protect the orders closest to their deadline first.
- **Bad data:** orders on hold (rejected by the importer) never enter the planner. They are reported to the dev team.

## 6. How to validate

Simulate the 41 days of this data with the planner and report: % on time, drone-hours per day, and the largest daily load per zone. Compare against two baselines:
(a) one drone per order on its ready day, and (b) one trip per city per day.
Expected from the capacity numbers: close to 100 % on time with zone loops, while baseline (a) runs out of drones every day.

# Task B: shipping logic (pseudocode)

Goal: maximise orders delivered within 5 days of `ready_to_ship`. Full write-up: [docs/task-b-algorithm.md](docs/task-b-algorithm.md).

**Inputs:** orders (ready date `r`, quantity ≤ 200, destination), 10 drones × 200 units at 100 km/h from Detmold, 7 zone loops
(Hannover · Dortmund+Köln · Bremen+Hamburg · Leipzig+Dresden · Berlin · Frankfurt+Stuttgart · Nürnberg+München),
calendars (NRW + destination state, B2B so no weekends), flight window (daylight unless the permit allows night).
**Targets:** SLA = arrive by working day 3. Promise = arrive by `r + 5` calendar days.

**In short:**
1. Every morning, take the orders that are ready, not shipped, not on hold, and whose destination is open today. Rank them: must fly today, past day 3, can wait, already too late.
2. Per zone, fill drones up to 200 units in that order. Hold a part-full drone only if every order on it can still wait.
3. Assign the longest trips first to the drone free soonest, if they land inside the flying window. Defer the rest. If urgent orders still don't fit, drop the trips that save the fewest of them.

```
every morning, and again after any disruption        # same state -> same plan (idempotent)
  cand = orders where ready <= today, not shipped, not on hold, destination open today

  for o in cand:
    latest(o) = last flight window that lands by the promise, on a day the destination is open
    class(o)  = 1  if latest(o) == today            # fly today or the promise is lost
              | 2  if today > sla_day3(o)           # past the SLA: ship immediately
              | 4  if latest(o) < today             # promise already lost: spare capacity only
              | 3  otherwise                        # may wait for a fuller loop, never past day 3

  trips = []
  for zone in zones:                                # nearby cities share one multi-stop loop (-35..42% flight time)
    queue = sort(cand in zone, by (class, latest))
    while queue:
      load  = take from queue in order until 200 units
      hours = loop_km(zone, stops(load)) / 100 + HANDLING * len(stops(load))
      if all(class == 3 for o in load) and units(load) < 200 and can_wait(load):
        break                                       # hold to fill the drone tomorrow
      trips.append(Trip(zone, load, hours))

  for t in sort(trips, by hours, descending):      # longest loops first (LPT)
    d = drone that is free earliest
    if d.free_at + t.hours <= window.end            # or: night permit covers the return leg
      assign(t, d)
    else
      defer(t)                                      # stays top priority tomorrow

  while any class-1 order is unassigned:            # Moore-Hodgson: lose the fewest orders
    drop the trip that saves the fewest class-1 orders per drone-hour
    reassign freed drones

  publish flight plans; keep orders on hold out of the plan (dev team fixes the data)
```

**Why this works on this data:** ~39 drone-hours a day are needed with zone loops, against ~80 in daylight. So almost every order makes the
promise, including the 13 Saxony orders that Task A's 3-working-day rule marks late (a flight takes hours, not days).
**Exact variant:** an integer program by zone and day (CP-SAT) maximising on-time orders, seeded with this greedy plan as the fallback.
**Watch-outs:** München and the South loop take 9.3 h, longer than a winter daylight window. Real routes avoid no-fly zones, so keep 10–15 % spare capacity.

# Data analysis: `data/orders-2000.csv`

Method: a one-off profile with Python's stdlib `csv` module (counts, field counts per row, format checks per column, duplicate grouping).
The importer (Phase 4) is the repeatable version of this analysis: it applies the rules below and stores every finding.

## Shape

- 2000 lines after the header, 7 columns: `external_order_id, sku, quantity, unit_price, currency, ready_to_ship_date, delivery_postcode`.
- UTF-8 with BOM, CRLF line endings.
- 12 postcodes, all major German cities. Ready dates 2026-11-02..2026-12-12 (41 days).
- Quantity 1..48, so no order needs more than one drone. About 48k units in total.
- Daily load: about 1,165 units on average, 1,474 at most. One trip by the whole fleet carries 2,000 units.
- Mixed EUR/CHF. 531 rows are ready on a Saturday or Sunday.

## Logistics analysis (feeds Task B)

Method: straight-line (great-circle) distance from Detmold to each postcode's city centre at 100 km/h, using hard-coded coordinates (no external geocoder).
Daily demand = units per city over the 41 ready days. Real flight paths around restricted zones will be longer, so treat these times as lower bounds.

### Distances and demand per destination

| City | km | Round trip (h) | Units/day | Full trips/day |
|---|---|---|---|---|
| Hannover | 76 | 1.5 | 107 | 0.54 |
| Dortmund | 108 | 2.2 | 107 | 0.53 |
| Bremen | 127 | 2.5 | 87 | 0.44 |
| Köln | 173 | 3.5 | 97 | 0.49 |
| Hamburg | 194 | 3.9 | 94 | 0.47 |
| Frankfurt | 204 | 4.1 | 86 | 0.43 |
| Leipzig | 250 | 5.0 | 103 | 0.51 |
| Berlin | 315 | 6.3 | 93 | 0.46 |
| Nürnberg | 317 | 6.3 | 87 | 0.43 |
| Dresden | 350 | 7.0 | 91 | 0.45 |
| Stuttgart | 352 | 7.0 | 102 | 0.51 |
| München | 464 | 9.3 | 101 | 0.50 |

No city needs more than one 200-unit drone per day on average. The longest one-way flight is about 4.6 h (München), so every order can arrive on the day it leaves.

### Capacity: three ways to fly

| Strategy | Drone-hours/day | Fits 24 h ops (240 h)? | Fits daylight only (~80 h)? |
|---|---|---|---|
| One drone per order (~47 orders/day × avg ~5 h) | ~235 | Barely | **No** |
| One trip per city per day (12 trips) | ~59 | Yes | Yes by hours, but München (9.3 h) is longer than one daylight window |
| **Zone loops: one trip per zone per day (7 trips)** | **~39** | Yes | Yes, except the South loop (9.3 h) |

### Zones: grouping nearby cities into one multi-stop trip

| Zone | Loop | Loop km vs 2 separate trips | Loop time | Avg units/day |
|---|---|---|---|---|
| Near | Hannover | 152 | 1.5 h | 107 |
| West | Dortmund → Köln | 355 vs 563 (−37 %) | 3.5 h | 204 |
| North | Bremen → Hamburg | 416 vs 643 (−35 %) | 4.2 h | 181 |
| East-1 | Leipzig → Dresden | 701 vs 1201 (−42 %) | 7.0 h | 194 |
| East-2 | Berlin | 630 | 6.3 h | 93 |
| South-West | Frankfurt → Stuttgart | 709 vs 1112 (−36 %) | 7.1 h | 188 |
| South | Nürnberg → München | 932 vs 1562 (−40 %) | 9.3 h | 188 |

Zone loops save 35–42 % of flight time. Most zone loads sit near 200 units, so on heavy days a zone needs a second drone.
That is still cheap: there is a lot of spare fleet time.

### SLA and shipping priority

- Target (Task A): delivered on working day 3 after ready_to_ship. Promise (Task B): within 5 days.
- Flights take hours, not days. So a 3-day target leaves room to wait and fill a zone trip, and anything late can go at once.
- Priority rule for Task B, highest first:
  1. Orders past their day-3 target: ship on the next flight, even in a part-filled trip.
  2. Orders whose latest safe departure (target day, minus flight time, inside the flight window) is today: ship today.
  3. All others: wait for their zone trip to fill, but never past rule 2.
- With the spare capacity shown above, in practice most orders can go out on their ready day.

### Calendars: working days per destination, not only the factory

- Customers are treated as businesses (B2B), so a delivery must land on a working day at the destination.
- German public holidays differ by state. In the data range (deliveries 2026-11-05..2026-12-17) one state holiday matters:
  **Buß- und Bettag, Wed 2026-11-18, Saxony only** (Dresden, Leipzig). Christmas (25/26 Dec) is national but falls after the range.
- Impact: **36 Saxony orders** (ready 13–17 Nov) shift by one working day. **24 of them** are currently planned to arrive on the holiday itself.
- Fixed: `portal/dates.py` now skips factory (NRW) and destination-state holidays.
- Consequence: **13 Saxony orders now take 6 calendar days**: 7 ready Fri 13 Nov (arrive Thu 19) and 6 ready Tue 17 Nov (arrive Mon 23).
  They break the 5-day promise even under Task A's simple rule. The portal flags them in "Needs your attention".
- Weekends: B2B sites are closed, so there are no deliveries on Sat/Sun. Drones may fly on weekends only if they then arrive on a working day.

### Flight-hour rules by location (not legal advice)

- All 12 destinations are in Germany, so the same federal framework applies everywhere: EU Reg. 2019/947 plus the German LuftVO.
- What differs by location is **geographical zones (LuftVO § 21h)**:
  - All 12 targets are city centres, which means flights over residential areas.
  - All 12 cities have an airport control zone nearby.
  - Berlin has government buildings.
  - These need zone permissions from the **state aviation authority (Landesluftfahrtbehörde) of each state**: 9 states for these 12 cities.
- **Night flights** are allowed in the specific category only if the operational authorisation (SORA) allows them. Many authorisations are daylight-only.
- **Daylight** in Nov/Dec is about 8–8.5 h. If daylight-only:
  - fleet time drops to about 80 h/day
  - the South loop (9.3 h) and the München trip cannot finish a round trip in one window
  - options: a night authorisation for the return leg, or a staging point in the south
- Ground staff loading drones on Sundays or holidays falls under German working-time law (ArbZG § 9).

### Open questions (from this analysis)

1. Should working days count the destination state's holidays as well as NRW's? Recommended: yes, skip any day that is a holiday in NRW or at the destination.
2. Is the flight window 24 h or daylight only? Recommended: plan for daylight only (the safe case) and treat night flights as an upgrade.
3. Does Task A's portal stay on the simple rule (ship = ready date, delivery = ready + 3 working days)? Recommended: yes, with the Saxony holiday fix. Zone loops, priority and flight windows go into the Task B write-up only.

## Defects found

Line = file line number (header = line 1).

| Defect | Rows | Lines / IDs |
|---|---|---|
| Blank line | 2 | 907, 1652 |
| Decimal comma in price, unquoted (`171,15`, so 8 fields) | 4 | ACME-01549, -01586, -01635, -01720 |
| Extra trailing field `Berlin` | 4 | ACME-00735, -01239, -01520, -01960 (3 of 4 contradict their postcode) |
| Missing field (6 fields) | 3 | ACME-00859 (no SKU), -01182 (no date), -01639 (no price) |
| Empty order ID | 4 | lines 385, 642, 1079, 1433 |
| Empty SKU | 3 | ACME-00098, -00239, -00388 |
| Quantity not an integer (`ten`, `x`, `1.5`) | 7 | ACME-00523, -00976, -01077, -01143, -01231, -01893, -01980 |
| Quantity ≤ 0 | 6 | ACME-00267, -00363, -00907, -01028, -01757, -01866 |
| Currency lowercase `eur` | 6 | ACME-00093, -00216, -00417, -00459, -00484, -01739 |
| Currency empty | 2 | ACME-00066, -00787 |
| Date `DD.MM.YYYY` | 2 | ACME-00332, -00929 |
| Date impossible `2026-13-01` | 9 | ACME-00073, -00276, -00803, -01098, -01287, -01498, -01827, -01927, -01967 |
| Date empty | 3 | ACME-00395, -01018, -01163 |
| Exact duplicate row | 3 pairs | ACME-00412, -01288, -01730 |
| Same ID, conflicting content | 10 rows | ACME-00006 ×3, -00023 ×3, -00675 ×4 (different SKUs, dates, postcodes) |

## Cleanup rules

Principle: **fix only what is unambiguous; never guess anything needed to ship.**
Fields needed to ship: ID, SKU, quantity, ready date, postcode. Billing fields: price, currency.

| Rule | Action |
|---|---|
| BOM, CRLF, blank lines, surrounding whitespace | Fixed silently |
| `eur` → `EUR` | Fixed, noted in report |
| `DD.MM.YYYY` → ISO date (dots mean German format, so there is no day/month ambiguity) | Fixed, noted in report |
| Decimal comma split across 2 fields (both digits, second exactly 2 digits) | Fixed (rejoined as `171.15`), noted in report |
| Empty currency | Kept, flagged (billing only, does not block shipping) |
| Exact duplicate | One kept, the copy noted in report |
| Any other wrong field count | Rejected: we cannot know which field is missing; for `Berlin` we cannot know which address is right |
| Missing or invalid ID, SKU, quantity, date | Rejected: guessing would ship wrong goods or on a wrong day |
| Same ID with conflicting content | All rows rejected and flagged for a human |
| Postcode not in the 12-city table | Rejected (unknown destination) |

Result (importer, verified by `tests/test_importer.py`): **1,946 orders accepted, 49 rows rejected, 3 exact duplicates removed**,
plus 2 blank lines = 2,000. A further 12 rows were kept with a fix and 2 were flagged (missing currency).
Every fixed, flagged or rejected row is recorded with its line number, order ID and reason.

## Upstream recommendation

These defects come from the export, not from the customers. Fixing them at the source matters more than cleaning them up downstream:
- a quoted CSV export or a typed API
- ISO dates and `.` as the decimal separator
- a unique constraint on the order ID

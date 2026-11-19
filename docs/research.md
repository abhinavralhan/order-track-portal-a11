# Research

Data findings and cleanup rules: see [data-analysis.md](data-analysis.md).

## 1. Problem and success criteria

| Task | Success means |
|---|---|
| A, portal (60 min) | The CEO logs in, finds any order by ID, and sees its planned ship date and planned delivery date (ready + 3 working days). Bad source rows are visible in a report, never silently lost. |
| B, algorithm (15 min) | A clear method that maximises orders delivered within 5 days of ready_to_ship, under the drone fleet's limits. |
| C, infrastructure (15 min) | A hosting design that is EU-resident, access-controlled, recoverable, and proportionate to an internal read-mostly tool. |

Fleet: 10 drones × 200 units, 100 km/h, unlimited range, starting from Detmold (DE 32756).

## 2. Privacy (GDPR) and external regulation

Not legal advice. Each point needs confirmation by the company's DPO or counsel before production.

Data classification: there are no names or emails, but an order ID plus postcode can be linked to a customer,
so the data is **pseudonymous personal data, and GDPR applies in full** (GDPR Recital 26).

| Regulation | What it means here |
|---|---|
| GDPR Art. 5(1)(c) data minimisation | The portal shows ID, SKU, quantity, dates and city. No prices, no full postcode. |
| GDPR Art. 6(1)(b) lawful basis | Processing is needed to perform the delivery contract. No consent required. |
| GDPR Art. 5(1)(e), 17 storage limitation, erasure | The portal is not the system of record. Its copy is deleted after delivery plus a short window, and one command wipes it. |
| GDPR Art. 25, 32 privacy by design, security | Server-side storage only, authentication, TLS, encryption at rest, least privilege, security headers, logs without order data. |
| GDPR Art. 28 processor | The hosting provider needs a Data Processing Agreement (DPA). |
| GDPR Art. 30 records | Add the portal to the record of processing activities. |
| GDPR Art. 33 breach | Breaches must be reported to the authority within 72 h, which needs access logs and alerting. |
| GDPR Ch. V transfers | Host in the EU. No US CDNs, fonts or analytics. LG München I, 20.01.2022 (3 O 17493/20) found embedding Google Fonts unlawful because it sends visitor IPs to the US. |
| BDSG (German Federal Data Protection Act) | Supplements GDPR in Germany. Portal access logs are employee data, so keep them minimal. |
| TDDDG § 25 (formerly TTDSG) | A login session cookie is strictly necessary, so no consent banner is needed. No tracking cookies. |
| HGB § 257, AO § 147 retention | Order and commercial records have statutory retention periods. These belong in the ERP (system of record), not in the portal. |
| EU drone rules: Reg. (EU) 2019/947 (operations), 2019/945 (aircraft), 2021/664 (U-space) | Autonomous flights beyond the pilot's line of sight carrying 200-unit loads fall at least into the "specific" category. They need an operational authorisation (SORA risk assessment) from the Luftfahrt-Bundesamt (LBA), and must respect German geographical zones (LuftVO). This can limit routes and flight hours, which Task B must allow for. |
| GDPR and drone sensors | If drones carry cameras, images of bystanders are personal data. A separate DPIA (data protection impact assessment) is needed. |
| BGB, EGBGB Art. 246a (distance selling) | A stated delivery time is information owed to the consumer. Missing it gives the customer rights such as withdrawal after a deadline. The 5-day promise is therefore a legal matter, not only a KPI. |
| NIS2 (German implementation) | Check whether the company's size and sector bring it into scope. If so, security and incident-reporting duties apply to this system too. |

## 3. Assumptions

- Working days: Mon–Fri, excluding public holidays in NRW, where the factory is. No holiday falls between 2026-11-02 and 2026-12-17, so the holiday list is a documented shortcut.
- Planned ship date = ready_to_ship_date (Task A wording). Fleet capacity is handled in Task B.
- The 5-day promise in Task B counts calendar days (drones are autonomous). Working days would be a one-line change.
- City coordinates come from a hard-coded table of 12 postcodes. No external geocoder (privacy).

# ARC Order Portal: what I did and why

**How I worked.** I treated the README and the CSV as the source of truth and asked whenever they were ambiguous: business or consumer customers, whose holidays count, daylight-only flying. Research and data analysis first, then a plan, then small reviewed steps. A MEMORY.md lets anyone, human or agent, resume.

**The data was the real test.** 15 planted defect types: shifted columns, German decimal commas, "ten" as a quantity, impossible dates, conflicting duplicate IDs. My rule: fix only what is unambiguous, and never guess a field that decides what ships where. Result: 1,946 clean orders; 49 rejected rows, each with a reason.

**Task A.** One question drove the portal: what does the CEO need to act on today? There is a stage pipeline, an order timeline, a "needs attention" panel with one-click reminders to the right owner, and Insights. Data errors go to the dev team, not the CEO. Every status says "planned", because the data has no actual delivery events, and I would rather be honest than impressive.

**The finding I'm proudest of.** Counting holidays at each destination showed that Saxony's Buß- und Bettag makes 13 orders miss the 5-day promise, even under the README's own rule.

**Task B.** Capacity is a grouping problem, not a fleet-size problem. Flying one drone per order needs about 235 drone-hours a day; 7 zone loops need about 39. The planner re-plans daily by deadline class, flies the longest loops first, and drops as few orders as possible. The binding constraint is daylight: München doesn't fit in a winter day.

**Task C.** Proportionate: one EU region, SSO, two availability zones, Multi-AZ Postgres. The growth path adds a fleet event feed with reconciliation, a planner service, an event bus and a warehouse. Deliberately no microservices.

**Quality.** Privacy by design: no prices stored, no client-side data, strict CSP, secrets never in code. 68 tests pass. The audit found 7 issues, including an empty-import crash; all fixed.

**In hindsight.** I'd timebox the documentation harder. Next steps: real delivery events, SSO, and simulating the planner on this data.

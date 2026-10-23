# 70 — Open Questions for BARO Stakeholders

These are decisions only BARO can make. **None of them is answered here**, and the design deliberately does not pre-answer them: each question instead names *where the unanswered value sits* so the package stays buildable the day it is answered — usually a settings field, a `fetch_from`, or an enum option rather than a code change.

Two kinds of question appear:
- **Blocking** — build cannot start on the named item until it is answered, because guessing would create schema or money-handling behaviour that is expensive to undo.
- **Absorbable** — the design has a placeholder (a config field, a report filter, a deferred DocType) and construction continues in parallel; the answer becomes configuration.

Each row: the question, who answers it, why it changes the design, and what the design does in the meantime.

---

## 1. Blocking questions

### Q1 — Ethiopian statutory accounting, tax, fiscalisation and language
**Asked of:** Finance lead + legal/compliance, with the external auditor.
Needed: VAT rate and registration rules; withholding tax (NIT 30/20/10% patterns) treatment on invoices and supplier payments; turnover tax applicability by category; excise where relevant; the e-Treasury / FRC invoice-submission interface and whether it is mandatory today or on the roadmap; official invoice numbering and print-format requirements (including whether a fiscal receipt number must appear on `Sales Invoice` print formats); ETB rounding rules; chart of accounts (existing CoA to migrate, or a template); payroll statutory deductions and holiday/leave rules (HRMS phase, not the spine); the applicable data-protection obligations for vehicle location and customer data, and the retention period the law or the auditor requires.
**Why it blocks:** nothing in the asset spine, and everything in the billing and payroll phases. Also decides whether `BARO Installation Format` and `BARO Assignment Certificate` are printable in Amharic, English, or both (`30` §13).
**Placeholder while unanswered:** `Subscription`/`Sales Invoice` are used as-is; no BARO tax logic exists anywhere; `30` §13 requires display locale (`dd/MM/yyyy`) never be encoded in a validation rule; presence/location fields are already restricted to permlevel 1 as if the strictest answer is true.

### Q2 — Which GPS tracking platforms, and how they can be talked to
**Asked of:** Technical lead + the platform vendors' contract terms.
Needed: vendor names and how many; auth model per vendor (API key / bearer / basic / OAuth2 / HMAC); documented rate limits and batch endpoints; whether webhooks exist and carry an event id usable as an idempotency key, or whether polling is the only option; the device/group/organisation schema on the platform side and whether a customer maps to a platform group; historical depth available at first sync; a sandbox for adapter development; who pays for and controls the platform account; the platform's own status vocabulary so the enum map in `50` §8 can be written; and the release/retention policy of the platform's API (versioning guarantees).
**Why it blocks:** the connector is the only release-1 component that cannot be built against a stub indefinitely — `50` §3's `PlatformClient` needs a real field list to implement `list_devices`, and `50` §8's mapping table is otherwise guesswork.
**Placeholder:** `50` §3 defines the interface, §4–§7 define the semantics, and every vendor-specific number is already a `Baro GPS Platform` field. Adapter code is the only part that changes per answer.

### Q3 — Dunning and service-suspension policy
**Asked of:** Finance + Customer Care, approved by a director.
Needed: after how many overdue days what happens; whether suspension is per customer, per vehicle or per device; who authorises it; whether tracking suspension is ever permissible at all under BARO's contracts (a speed-limiter or stolen-vehicle device may be a legal or insurance obligation — cutting it could be unlawful); and what the customer is told and when.
**Why it blocks:** `51` RA-5's threshold, `60` T5 vs T12's boundary, and the design of the suspension workflow in `40`. This is the question where an engineer's reasonable default is the most dangerous possible answer, because it involves turning off a safety-relevant service.
**Placeholder:** the design **cannot** suspend anything automatically (`40` §7). Suspension is a Workflow transition requiring `BARO Finance Approver` + `BARO Approver` (`41` §6), so answering Q3 changes only who is in the approval chain and what threshold proposes it.

### Q4 — Does one subscription cover many devices, or one?
**Asked of:** Sales + Finance (this is a commercial-model question, not a technical one).
Needed: for a 40-vehicle fleet customer, is there one contract with one subscription and 40 billing units, or 40 subscriptions? Are partial-month changes prorated? Are device and service billed as one line or two?
**Why it blocks:** it is the only question that decides whether a new DocType gets built. 1:1 → a Custom Field on `Subscription`, no schema. 1:M → `Baro Subscription Asset` (`10` §5, deferred) with its own lifecycle, and `11` R-13's billing chain changes shape.
**Placeholder:** the DocType is listed as deferred, not omitted, and `11` shows it as a deferred entity so the ERD does not need redrawing either way.

### Q5 — What a billing unit actually is
**Asked of:** Finance + Sales.
Needed: price per vehicle, per device, per SIM, per platform connection, or per feature bundle; what happens on device replacement mid-period; whether an offline device is still billable; installation as one-off vs recurring.
**Why it blocks:** `51` RA-6 (`Plan/price drift`) can only be written once the basis is known, and it decides `Subscription Plan` modelling in the billing phase.
**Placeholder:** RA-6 is implemented as a check whose comparison basis reads config, so the answer is a settings change; no other release-1 document depends on it.

### Q10 — Who holds `BARO Approver`, and with what limits
**Asked of:** Management, per department, by name.
Needed: the actual people per branch and per duty (assignment approval, RMA scrap, waiver of an exception, discount, suspension); their monetary or service authority limits; who acts when they are absent; and whether any approval may be delegated in-system.
**Why it blocks:** `41` §1 sizes the role at 1–3 people per branch, and maker-checker depends on the population being large enough that a maker is never their own checker. If only one person exists in a branch, the design has to say so honestly and add a compensating control rather than pretend segregation exists.
**Placeholder:** roles, not users, are referenced everywhere (`51` §7's inbox filters on `baro_assigned_role`, never on a name), so staffing changes need no schema or workflow edit. Absence handling is explicitly *not* invented here.

### Q11 — Hosting, backup and recovery ownership
**Asked of:** Management + IT, and the party that will operate production.
Needed: where production runs (this PC is a development box only, `04` §5); who owns backups, encryption keys, retention and restore testing; RPO and RTO BARO will sign; patching window; whether BARO staff or a vendor holds `BARO System Manager`.
**Why it blocks:** go-live and the ops documents, plus the security controls in the blueprint (MFA for privileged users, secret storage). It does **not** block schema.
**Placeholder:** the acceptance criterion "successful recovery from backup" is recorded in `80` as an *ops* criterion not yet testable in this package, and the "never patch core / `baro_` prefix / fixtures" rules in `04` §6 already make restore-from-upgrade feasible.

---

## 2. Absorbable questions

| # | Question | Answers | Placeholder while open |
|---|---|---|---|
| Q6 | Should `baro_fleet_group` become a master DocType (`Baro Fleet Group`), or stay autocompleted free text? | Sales/BI: is there per-group pricing, per-group reporting, or group-level contract terms? | Release 1 keeps free text (`10` §4.1); promotion to a master is additive and touches nothing else |
| Q7 | Which SIM/telco providers, and is there an API for plan/activation/status, or only a portal? | Connectivity lead | The provider is the **standard `Supplier` link** on `Baro SIM Card`, distinguished by Supplier Group (`21` §3) — there is no BARO provider field and no provider master to invent. If an API exists it becomes one more integration in `50`'s shape, not a redesign |
| Q8 | Volumes and growth: vehicles, devices in stock, active assignments, assignments/year, concurrent users, historical rows to import | Operations | `20` §8's import templates and `31` §7's migration plan are batch-based; the row cap in `51` §2 is config; nothing here is volume-specific |
| Q9 | Migration sources and their data quality: spreadsheets, an existing ERP, the platform's own registry, paper | Operations + Finance | `20` §8 defines the templates; `31` §7.1 runs a duplicate pre-flight that **stops and reports** rather than silently choosing a survivor — which is exactly the behaviour an unknown data quality requires |
| Q12 | Company and branch structure today: one company with branches, or several legal entities (BARO Group divisions)? | Management + Finance | Multi-company is supported by ERPNext as-is; `company` is already on every BARO DocType and User Permissions scope by branch (`41` §5.1), so an answer late changes assignment, not schema |
| Q13 | Which other business divisions of BARO Group are in scope beyond GPS/limiters/installations? | Management | The blueprint already flags this as to-be-confirmed in discovery. Out-of-scope divisions do not alter the spine; they alter `90`'s priority order |
| Q14 | What count delta or exception volume is newsworthy, and to whom? | Management | `baro_count_alert_threshold` and `baro_max_rows_per_run` in `Baro Operations Settings`; `51` §4.4's escalation owner changes with the number |
| Q15 | Legal/audit hold periods for integration evidence and closed exceptions | Compliance + auditor | `baro_log_retention_days` plus the never-purge rules in `51` §9 and `50` §11; a longer hold is a config change, a shorter one needs the auditor's written agreement |
| Q16 | Cross-platform duplication: is the same device legitimately registered on two platforms? | Technical | `51` §4.5 currently treats a second active claim as an exception for `BARO System Manager`. If double registration is legitimate, that bucket gains a whitelist rule — the invariant (`31` U-6) does not move |
| Q17 | Are SIMs stock-tracked (their own `Serial No`) or registry-only? | Warehouse | `Baro SIM Card` already carries an *optional* link to `Serial No` (`03` row 8); the answer decides whether SIM procurement uses the stock ledger at all |
| Q18 | Does BARO capitalise vehicles on its own books, or are they always the customer's? | Finance | `Baro Vehicle`→`Asset` is an optional link (`03` row 6); no depreciation logic is assumed anywhere |
| Q19 | Who signs the UAT report, and against which of `20` §9's scenarios? | Management | U1–U15 are already written as pass/fail; `80` §6 lists them as the acceptance surface, so an answer adds names, not tests |

---

## 3. What we will *not* ask, and why

Some questions look open but are settled by the design, and re-opening them would stall delivery:

| Not asked | Because |
|---|---|
| "Which ERPNext version?" | v16 stable is locked (`04`); the residual is verification debt, tagged `[verify-vs-v16]`, not a decision |
| "One app or six?" | one app now, with explicit split criteria (`02`) |
| "Build a BARO Device doctype?" | `Serial No` is extended, never duplicated (`03` §3) |
| "Rebuild recurring billing?" | `Subscription` ships it (`03` row 15) |
| "Store telemetry in ERP?" | no, firm boundary (`01` §5) — and no volume answer changes it |
| "May a scheduled job suspend service or post an invoice?" | no (`40` §1, `60` §7) — Q3 changes *who approves*, never *whether a cron acts* |
| "Are permissions enforced in the client?" | no; server-side and record-level, per BARO's own stated requirement (`41` §1, §5) |

---

## 4. Sequencing the answers

| When needed | Questions |
|---|---|
| Before schema is frozen (week 1 of build) | Q4, Q6, Q12, Q13, Q16, Q17, Q18 |
| Before the connector is written | Q2 |
| Before reconciliation tuning is configured | Q3, Q5, Q14, Q15 |
| Before billing phase | Q1, Q3, Q4, Q5 |
| Before go-live | Q7, Q9, Q10, Q11, Q19 |
| Any time before go-live | Q8 |

The spine can be built to completion with **only** Q4, Q6, Q12, Q13, Q16, Q17, Q18 answered, because everything else lands in configuration, an adapter, or a later phase. That asymmetry is the practical justification for choosing the asset spine as release 1.

---

## 5. How to answer them

A written answer is a one-line decision plus the reason, filed against this document's number, and then the design document that consumes it is updated in the same change (`10` for a field or setting, `41` for a role, `40` for a transition, `50`/`51` for an integration or threshold). An answer that does not appear in a design document is not an answer — it is an intention, and it will be contradicted by the code.

`80-verification-checklist.md` §7 lists the questions whose placeholder is still active in the package, so a reviewer can see at a glance which parts of the design are provisional and which are decided.

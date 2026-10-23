# 90 — Later-Phase Backlog (deliberately not in release 1)

Release 1 is the asset spine (`01` §2, `03` §2). Everything the blueprints proposed beyond it is collected here with an honest reason for the deferral and the condition that unlocks it. This document exists so that "not built yet" is a recorded decision rather than an omission someone discovers at go-live.

It also protects the spine: several of these items would distort the schema badly if their requirements were allowed to shape it now (§4).

---

## 1. The 24 proposed workspaces — where each one actually comes from

The revision blueprint proposed 24 workspaces. A workspace is a **menu of links**, not a module: in Frappe it is a `Workspace` record with shortcuts to existing DocTypes, reports and pages. Building 24 of them before the records they point at are trustworthy is decorating an empty house.

| Proposed workspace | Release-1 status | Real dependency |
|---|---|---|
| Dashboard | partial — `20` §7's three workspaces | executive BI needs finance + subscription data (`03` rows 14–15) |
| Helpdesk | deferred | `helpdesk` app or `Issue` configuration (§2) |
| Stock | **in** (standard, extended) | — |
| Fleet Register | **in** | — |
| My Claims | deferred | `hrms` app + payroll policy (Q1) |
| Quality | **in** (as `Quality Inspection`, not a BARO doctype) | full checklist library is phase 4 |
| Projects | deferred | standard `Project`/`Task` already in use by T1; costing roll-up needs phase 3 |
| CRM | deferred (standard doctypes already usable) | configuration, not schema |
| ToDo Manager | deferred | standard `Task` covers it; a workspace is a shortcut list |
| Performance | deferred | `hrms` appraisal + technician productivity from assignment counts |
| SIM Management | **in** | — |
| Billing & Subscription | deferred **design**, standard `Subscription` untouched | Q3, Q4, Q5 |
| Installations | **in** (extended `Installation Note`) | mobile forms (§3) |
| GPS Devices | **in** (extended `Serial No`) | — |
| Procurement | deferred | standard ERPNext purchasing; needs supplier/landed-cost policy |
| Accounting | deferred | Q1 is blocking, not deferrable-by-choice |
| HR & Payroll | deferred | `hrms` app; version-compat pin needed (`04` §3) |
| Contracts | deferred (standard `Contract` already linked) | expiry automation T3 is already live |
| Scheduling | deferred | standard `Appointment`/`Calendar Event` reuse already decided (`03` row 23) |
| Analytics | deferred | needs a reporting layer decision (§3) |
| Compliance | deferred | needs the compliance DocTypes deferred in `10` §5 + Q1 |
| AI Assistant | deferred | §3 — highest risk item on the list |
| Customer Portal | deferred | Q16/Q1 visibility rules + portal user governance |
| Administration | partial — roles/permissions are designed now (`41`) | — |

**Sequenced workspace rollout** (phase 2+): add a workspace only when (a) its records are populated, (b) its role has a named holder in Q10, and (c) at least one report exists for it. Department→workspace defaults in the blueprint's §6 table are *configuration*, recorded as such in `41` §9.

---

## 2. Separate apps to evaluate, not to install casually

| App | Needed for | Watch out for |
|---|---|---|
| `hrms` | employees beyond the legacy `Employee` link, attendance, leave, payroll, appraisal, expense claims (My Claims) | it is a separate release train from ERPNext; the version-compatibility matrix in `04` §3 must be extended, not assumed. Payroll in Ethiopia depends on Q1 |
| `helpdesk` | the blueprint's "Helpdesk" module with SLA policies and agent queues | ERPNext already ships `Issue` with native SLA fields (`02` §6). Decide *reuse vs app* once, deliberately — two ticket systems is the worst outcome |
| `lending` / payment gateways | instalments, local gateway integration | money-handling; needs Q1, Q3 and a security review before any pilot |
| a reporting/BI add-on | the Executive Dashboard's cross-module KPIs | a Script Report reading through Frappe keeps permissions (`41` §5.3). Any tool that queries MariaDB directly bypasses every control this package designs |

---

## 3. Feature-level deferrals and why they are not small

| Item | Why it is not a config change | Condition to unlock |
|---|---|---|
| **Mobile technician workspace with offline sync** | Offline capture plus controlled conflict resolution is a client-side data store, a sync queue, conflict rules against the very invariants `31` protects, and an identity/session story for shared devices in a van. Frappe's web UI is mobile-responsive; that is not the same thing as offline. A naive "queue and post later" implementation lets a technician submit an assignment whose device was reassigned hours earlier — which is exactly the invariant we sell as proven | Device inventory for the field team + an agreed conflict policy + the spine proven under concurrent use (`31` §8 T-4 green in production) |
| **AI assistant over permission-filtered data** | The blueprint's own wording ("retrieves only data the employee is authorized to access") is the hard part. Safe implementation means every retrieval runs *as the user*, through permission-filtered queries — not through a raw-SQL index the assistant holds. Write actions require confirmation, and a hallucinated submit is a service/billing event with legal consequences. Vehicle presence data is personal data (Q1) | A written data-handling position from legal (Q1), an approved model/hosting path (Q11), a read-only pilot against non-sensitive doctypes, and an evaluation set built from `20` §9's questions |
| **Customer self-service portal** | `Customer.portal_users` and ERPNext's portal exist, so the plumbing is cheap; the *policy* is not — which invoices, which vehicles, which tickets, and never any reconciliation/billing-mismatch finding (`51` §12). Needs the same permission model proven server-side, then a guest-facing surface | Q16/Q1 + a portal-user governance rule (who creates and revokes portal logins) |
| **Universal search / one search bar** | One-Scan (§`03` §4) already solves the identifier case with `search_index` fields. A global bar across all doctypes is a UI aggregation over permission-filtered results; the risk is that a fast search becomes an enumeration oracle (`41` §5.3 addresses this for One-Scan) | Release-1 fields keep `search_index: 1`, so this is additive later |
| **Approval inbox** (all pending approvals in one place) | Trivially built from `Baro Device Assignment` + RMA + workflow-state queries; deliberately not built now because two people with one inbox start approving each other's queue without reading | A named `BARO Approver` population per branch (Q10) |
| **Notification centre / digest tuning** | `40` §8 and `60` §4 already define recipients and anti-spam rules; a centre is presentation | Usage data from the phase-1 notification set |
| **Duplicate detection beyond the unique indexes** | `31` enforces exact identifier uniqueness. Fuzzy duplicate detection (same customer typed three ways, same vehicle with a mis-read plate) is a scoring problem with a human queue — and if it auto-merges, it destroys assignment history | A data-quality owner + Q9's migration actually run, so the real duplicate shape is known |
| **Digital document centre** | Frappe `File`, attachments and private files already carry evidence (`21` §2 signature/photos). A managed-document repository with retention categories is a compliance product, not a folder | Q1/Q15 retention rules |
| **Audit timeline as a product surface** | `track_changes: 1` + Version records already exist underneath; the blueprint asks for a *view*. Low risk, low urgency | Any reporting phase |
| **Scheduled reports to email** | Standard Frappe report subscription capability | Recipients + Q14 thresholds |
| **SLA monitoring & escalation** | `Issue` SLA fields exist; escalation needs an agreed policy | A helpdesk decision (§2) + policy owner |
| **Telemetry-derived analytics** (idling, speeding, driving score) | Out of scope by design: telemetry stays outside ERP (`01` §5). Any future version must read an aggregate from the platform, never ingest points | A platform aggregate API (Q2) + a privacy position (Q1) |

---

## 4. Items that must *not* shape the spine schema

Recorded because these are the requirements that will be raised in phase 2 and answered with "change the spine now", which is the expensive option:

| Later requirement | Tempting spine change | Correct answer |
|---|---|---|
| Per-vehicle service history for the portal | add customer-visible flags to `Baro Vehicle` | portal reads permission-filtered existing records; nothing new on the master |
| Multi-platform registration of one device | add a second platform id field on `Serial No` | `Baro Platform Mapping` is already 1:M by construction (`11` R-10) — no schema change |
| Bundling devices under one subscription | add a device list to `Subscription` | `Baro Subscription Asset` if Q4 says 1:M; `03` row 16 already anticipated it |
| Tracking installer commissions | add a commission field to `Baro Device Assignment` | timesheets/`Task` billing + payroll in `hrms`; a money field on an operational record invites an audit finding |
| Field photos in offline mode | store base64 blobs on the assignment | `File` attachments + a sync queue in the mobile design (§3), never a column |
| Speed-limiter certificate as a printable compliance doc | a new compliance doctype now | certificate fields already live on `Baro Vehicle` (`10` §4.1); promote to a DocType when Q1 defines the compliance model |
| "Just let the scheduler auto-resolve matching exceptions" | a flag on the exception doctype | `51` §6.3 permits *auto-clear by a complete run only*; an always-on resolver was rejected in `60` §7 |

---

## 5. Phase order (unchanged from the blueprint's shape, restated against this package)

| Phase | Content | Depends on |
|---|---|---|
| 1 | **Asset spine** — this package | Q4, Q6, Q12, Q13, Q16, Q17, Q18 |
| 2 | Customer operations: helpdesk decision, contracts, subscriptions/billing live | Q1, Q3, Q4, Q5 |
| 3 | Finance depth: procurement, accounting, tax/fiscalisation, bank rec | Q1 |
| 4 | Internal management: claims, quality checklists as a library, projects costing, tasks/performance | `hrms` pin, Q10 |
| 5 | Automation & integrations at scale: notification gateways, payment providers, reconciliation tuning | Q2, Q7, Q14 |
| 6 | Advanced experience: mobile offline, customer portal, AI assistant, BI | §3 conditions, Q1, Q11 |

Discovery, migration rehearsal and security/UAT run **alongside** these, not after them — the roadmap's phases 1 and 7 are activities, not modules.

---

## 6. Carrying this document forward

Any item promoted from here into scope re-enters through the design sequence, not the code: `03` (verdict), `10` (fields), `11` (relationships), `40`/`41` (states and permissions), `60` (automation), then `80` re-verified. An item that skips that sequence becomes the kind of feature that needs a raw SQL patch six months later.

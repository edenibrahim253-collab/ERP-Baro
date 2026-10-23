# 60 — Automation Trigger Catalog

Every automated behaviour in release 1 is one row here. A trigger not in this table does not exist; a trigger in a blueprint but not here is either deferred (§6) or rejected (§7).

The table answers, for each trigger: **what sets it off, which DocType and event handles it, who is guarding, what it writes, who is told, whether a human must approve, and which mechanism from `40` §2 implements it.** Numbers (`T1`…`T14`) are stable identifiers — `30` §11 jobs, `40` §8 notifications and `10` §4.9 config fields reference them, and `80` §3 checks that every `Tn` referenced anywhere resolves to a row here.

**The governing rule, restated once:** a trigger may detect, flag, notify and create *drafts*. It may never submit, cancel, amend, suspend a service, or touch a ledger. That is BARO's own stated invariant ("financial or service-impacting actions … require appropriate approval and validation rather than running solely from an automated alert"), and it is the reason several rows below end with "human transition" instead of "done".

---

## 1. The catalog

| # | Trigger source | DocType / event | Guard role | Side effect (what is written) | Notification | Approval required? | Mechanism |
|---|---|---|---|---|---|---|---|
| **T1** | Installation completed | `Installation Note` → `on_submit` | `BARO Installer` | `Baro Device Assignment` state → `Installed` on `Serial No.baro_device_status`; **draft** `Task` "Verify activation" on the Installation's project, `exp_end_date = now + baro_activation_sla_days` | in-app to installer + supervisor | no (draft creation); the *activation* itself is T2/`50` §9 | `doc_events` → controller |
| **T2** | Device assigned to vehicle (assignment submitted) | `Baro Device Assignment` → `on_submit` | `BARO Service Supervisor` submits, `BARO Approver` approves | `baro_active_serial_key`/`baro_active_vehicle_key` set; `Serial No.baro_device_status = Allocated→Installed`; `Baro Vehicle.baro_current_device` + `baro_current_assignment` recomputed; `Baro SIM Card.baro_installed_device` where a SIM is named; append `Baro Firmware History` seed row | in-app on approval only | **yes** — the submit is the maker act; the Active state is the checker act (`40` §4) | controller + `doc_events` |
| **T3** | Contract approaching expiry | `Contract.end_date` scan → `flag_contracts_expiring` (daily) | `BARO Sales Officer` owns the relationship | **none** — flag + per-customer digest | email to `Customer.account_manager` (standard field — `10` §2 says do not add a BARO duplicate) | no | scheduler → notify only |
| **T4** | Subscription billing date | ERPNext `Subscription` native scheduler | `BARO Accounts User` | Draft `Sales Invoice` by standard behaviour — **BARO writes nothing here**; `Baro Device Assignment` supplies the vehicle count via `baro_service_level` on the Subscription | standard ERPNext | yes, at invoice submit (existing ERPNext approval) | reuse standard — do not re-implement (`03` row 15) |
| **T5** | Invoice overdue | `Sales Invoice.outstanding_amount` scan → `flag_overdue_invoices` (daily) | `BARO Accounts User` | none; a `Billing mismatch` exception row only when the overdue set crosses the policy threshold (`51` RA-5) | email finance; optional customer reminder per policy | **yes for any dunning action** — suspension is T12, never T5 | scheduler → notify only |
| **T6** | Device inactive | `Serial No.baro_last_comm_at` < `now - baro_inactive_threshold_hours` → `flag_inactive_devices` (hourly) | `BARO Support Agent` queue | **draft** `Issue` (or notification if draft-issue creation is disabled) — never submitted | in-app + optional SMS | no for the draft; yes for dispatching a technician | scheduler → draft creation |
| **T7** | SIM data plan approaching expiry | `Baro SIM Card.baro_expiry_date` scan → `flag_sim_expiry` (daily, `baro_expiry_notice_days`) | `BARO Connectivity Admin` | none. **The job does not set `baro_sim_status = Expired`** — a status technicians read in the field is changed only by a human from the flagged list (`21` §4) | email + list view | no (notify), yes (status) | scheduler → notify only |
| **T8** | Compliance certificate / registration expiry | `Baro Vehicle` certificate + registration + insurance dates → `flag_certificates_expiring` (daily, `baro_cert_notice_days`) | `BARO Fleet Officer` | none | email fleet officer + compliance | no | scheduler → notify only |
| **T9** | Stock below reorder point | standard `Item` reorder / `safety_stock` → `flag_reorder_points` (daily) | `baro_reorder_notice_role` (config value: Stock Manager *or* Procurement Officer — one of them, never both, so the recommendation has an owner) | **none in release 1.** No automatic `Purchase Request`; ERPNext's native reorder report remains the source of truth | email with the report link | yes for the actual purchase (`41` §6) | scheduler → notify only |
| **T10** | Warranty approaching expiry | `Serial No.warranty_expiry_date` scan → `flag_warranty_expiry` (weekly) | `BARO Service Supervisor` | none; feeds the RMA in-warranty/out-of-warranty decision at inspection time | weekly digest | no | scheduler → notify only |
| **T11** | Device replaced (RMA disposition = Replace) | `Baro Device RMA` → `on_submit` | `BARO Service Supervisor` + `BARO Approver` (Scrap) | Ends the old assignment (`to_time`, `baro_status = Superseded`), creates the **draft** new assignment, links both on `baro_old_assignment`/`baro_new_assignment`; old serial → `RMA`/`Returned`; quarantine `Stock Entry` is created as **draft** and submitted by Stock Manager | in-app to supervisor | **yes** — the new assignment still needs its own approval, so a replacement cannot silently put a device live | controller + `doc_events` |
| **T12** | Customer terminated / suspension for non-payment | Human act on `Subscription` + `Baro Device Assignment` batch | `BARO Finance Approver` (money) + `BARO Approver` (service) | Trigger **starts an approval workflow**; the deactivation transitions then run per document. No job may enter this path | in-app to approver | **yes — this row exists to make that explicit** | Workflow only; scheduler may raise the *proposal* via T5/T13 |
| **T13** | ERP ↔ platform state or count disagreement | `run_platform_reconciliation` → writes `Baro Reconciliation Exception` | `BARO Integrator` (bot) creates; owning roles close | exception rows only, deduped by `baro_match_key`; auto-clear sweep when a complete run no longer sees the condition | daily run digest | no to raise; `BARO Approver` to waive (`40` §5) | scheduler → exception rows (`51` §4–§6) |
| **T14** | Inbound event references an unmapped device | `baro_core.api.webhook_gps` / poller resolve step (`50` §5 step 6) | `BARO Integrator` | `Mapping missing` exception row. **Explicitly forbidden: creating a `Serial No` or a mapping from platform data** — the bot has no Create on `Serial No` (`41` §5.4) | counted in `50` §10 alert ("> 10/day") | no to raise; a human registers the device | inbound handler → exception row |

---

## 2. Traceability to the blueprint's automation table

The original blueprint listed twelve trigger/action pairs. Every one lands above — none was dropped, two were re-homed, and two rows were added by this design.

| Blueprint trigger | Here | Note |
|---|---|---|
| New GPS installation completed → submit activation verification task | **T1** | created as a *draft* `Task`, not "submitted": submitting on behalf of a human would defeat the verification |
| Device assigned to vehicle → update assignment history | **T2** | |
| Contract approaching expiry → notify sales officer | **T3** | |
| Subscription billing date → generate scheduled invoice | **T4** | re-homed: this is ERPNext's own scheduler, and building a BARO version of it is the most expensive avoidable mistake in the project |
| Invoice overdue → notify finance/customer based on policy | **T5** | |
| GPS device inactive → create support alert after threshold | **T6** | |
| SIM data plan approaching expiry → notify connectivity administrator | **T7** | |
| Stock below reorder point → create procurement recommendation | **T9** | re-homed: "recommendation" is implemented as a notification pointing at the standard reorder report, because an auto-created purchase request is an unsupervised money commitment |
| Warranty approaching expiry → notify service team | **T10** | added row — the blueprint's *module* list requires it (warranty history) even though its automation table omitted it |
| Device replaced → close old assignment and record replacement | **T11** | |
| Customer terminated → start service deactivation approval workflow | **T12** | the blueprint's own wording already says "start … approval workflow" — that phrasing is why T12 is a workflow and not a job |
| ERP/GPS platform fleet mismatch → create reconciliation exception | **T13** | |
| — (not in the blueprint) | **T14** | event-driven counterpart of T13; kept separate because its urgency is different (`51` §4.2) |
| — (not in the blueprint) | **T8** | vehicle compliance certificates; required by the compliance module and by Ethiopian speed-limiter documentation |

---

## 3. Job-name cross-check

`30` §11 is the deployment contract; the names must match this table exactly.

| Trigger(s) | Job (`30` §11) | Cadence source |
|---|---|---|
| T3 | `flag_contracts_expiring` | fixed daily |
| T5 | `flag_overdue_invoices` | fixed daily |
| T6 | `flag_inactive_devices` | hourly, threshold from `baro_inactive_threshold_hours` |
| T7 | `flag_sim_expiry` | fixed daily, window from `baro_expiry_notice_days` |
| T8 | `flag_certificates_expiring` | fixed daily, window from `baro_cert_notice_days` |
| T9 | `flag_reorder_points` | fixed daily |
| T10 | `flag_warranty_expiry` | fixed weekly |
| T13 | `run_platform_reconciliation` | `baro_reconciliation_cron` |
| — | `sync_platform_fleet` | `Baro GPS Platform.baro_pull_interval` |
| — | `process_integration_retries` | every 5 min (`50` §7) |
| — | `archive_integration_logs` | weekly (`50` §11, `51` §9) |

The two documents are one list seen from two sides; `80` §3.4 asserts they stay equal in both directions — a job with no trigger row is an undocumented behaviour, and a trigger row with no job is a behaviour nobody deployed.

**Common contract for every row above** (from `30` §11 and `40` §7): idempotent, batched with a hard row limit, guarded by a named Redis lock, writes a run marker to `Baro Integration Log` or `Error Log`, safe to run twice on the same day, and aborts without side effects when its upstream read fails (`51` §8).

---

## 4. Where each trigger's notification is defined

Notification names follow `30` §2 and **zero-pad the trigger id to two digits** so the notification list sorts numerically: catalog id `T3` becomes `BARO - T03 Contract Expiring`. The catalog keeps single-digit ids (`T1`…`T14`) because they are easier to cite in prose; the padded form exists only in the record name.

Recipient resolution is always through a *role* or a *document field*, never a hard-coded user:

| Trigger | Recipient resolved from |
|---|---|
| T1, T2 | `Baro Device Assignment.baro_technician`'s reporting supervisor + role `BARO Approver` filtered by the vehicle's branch User Permission |
| T3, T4, T5 | `Customer.account_manager` (T5 also `BARO Accounts User`) |
| T6 | role `BARO Support Agent` (queue), plus `BARO Service Supervisor` when the vehicle is under an open installation |
| T7 | role `BARO Connectivity Admin` |
| T8 | `BARO Fleet Officer` + the customer's registered contact where the certificate is contractual |
| T9 | the role named in `baro_reorder_notice_role` |
| T10 | `BARO Service Supervisor` |
| T11, T12 | `BARO Approver` (workflow transition email, not a scheduler email — `40` §2) |
| T13 | `baro_assigned_role` on each exception row + daily digest to `BARO System Manager` |
| T14 | `BARO Stock Manager` |

Two content rules (`40` §8): no IMEI or plate in an email subject, and no per-vehicle spam — anything that can fire for 200 vehicles of one customer fires once as a digest.

---

## 5. Adding a trigger later — the gate

A new automated behaviour must answer all five before it is built. These five questions are the reason this catalogue can be trusted during an upgrade review.

1. **Does it write a business document, or only flag/notify/draft?** If it writes or submits, it is not a trigger — it is a workflow transition and needs a named approving role.
2. **Is it safe to run twice?** Requires an idempotency key or a "already raised?" check (`51` §6.1 pattern), plus the named lock.
3. **What happens when its upstream source is unavailable?** The answer must be "abort, do not infer" (`51` §8), never "assume empty".
4. **Which config value carries its threshold?** A number in code is a defect; every threshold above reads `Baro Operations Settings`.
5. **Which report or inbox shows its output?** A trigger whose only output is an email is unmeasurable and will be silently ignored within a quarter.

---

## 6. Deferred triggers (phase 2+)

| Trigger | Phase | Why not now |
|---|---|---|
| Ticket SLA breach → escalate to supervisor | Helpdesk phase | `Issue` SLA fields exist (`02` §6) but no BARO-owned SLA policy is agreed; escalation without a policy is noise |
| Installation evidence missing → block close-off | Field-service phase | needs the mobile/offline form design (`90`), which decides what "missing" means |
| Vehicle transfer between customers → auto-move assignments | Phase 3 | must be an approved pair of documents (end + create), not an automatic edit of history (`11` R-04) |
| Platform shows `Stolen` → notify insurer / authority workflow | Compliance phase | depends on the compliance DocTypes deferred in `10` §5 and on legal input (`70`) |
| Payment gateway webhook → reconcile against invoice | Payments phase | an inbound money event needs its own idempotency and reconciliation design, not a bolt-on to T14 |
| Predictive device-failure signal | later, if ever | needs telemetry, which stays outside ERP by design (`01` §5) |

---

## 7. Rejected — triggers that looked reasonable

| Proposed | Rejected because |
|---|---|
| Auto-suspend tracking after N days unpaid | a service cut driven by a cron is the exact case BARO's invariant forbids; T12 with a human approver is the answer |
| Auto-create `Serial No` from an unmapped platform IMEI | lets a bot mint inventory records, corrupting stock valuation and the IMEI uniqueness proof (`41` §5.4) |
| Auto-set `baro_device_status = Active` when the platform reports first ping | "reported once" is not "verified" — activation verification is T1→T2 with a human close-off (`50` §9) |
| Auto-cancel a subscription when its contract expires | cancellation has billing consequences in the other direction (refunds, final invoice); T3 notifies, a human decides |
| Auto-resolve an exception when the platform stops reporting it | only a *complete* run may clear (`51` §6.3); a failed run would "resolve" the whole fleet |
| Nightly job that repairs overlapping active assignments | if the invariant is violated, something is broken in code or someone bypassed the model; deleting history to make a report green destroys the evidence (`40` §7 last row) |
| Auto-send the customer a "device offline" alert | turns an internal signal into customer-visible noise and presumes a comms policy that does not exist yet |

---

## 8. Verification hooks

| Check | Assert |
|---|---|
| V-T1 | every `Tn` referenced in `10`, `20`, `21`, `30`, `40`, `41`, `50`, `51` resolves to a row in §1 |
| V-T2 | no row in §1 has a side effect that submits, cancels or amends a document (`40` §7) |
| V-T3 | every threshold in §1 is a `Baro Operations Settings` field name that exists in `10` §4.9 |
| V-T4 | every role named as guard/recipient exists in `41` §1 |
| V-T5 | §3's job names equal `30` §11's job names, in both directions |
| V-T6 | §1's T13/T14 exception types are members of `10` §6's Exception type enum |

These six are executed as part of `80-verification-checklist.md`; V-T3 and V-T4 are the two that catch drift when someone later adds a knob or renames a role.

---

*Read with: `40-workflows-approvals.md` (mechanism boundaries), `51-reconciliation-exception-design.md` (T13/T14 detail), `30-schema-conventions.md` §11 (job deployment), `70-open-questions-stakeholders.md` (which thresholds are still unanswered).*

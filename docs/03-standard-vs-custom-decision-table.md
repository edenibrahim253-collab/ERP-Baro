# 03 — Standard vs Custom Decision Table

This is the spine document: every other document in this package must reconcile against the verdicts here. It answers one question per business entity — **Reuse standard as-is (R) / Extend standard with Custom Field or Property Setter (E) / Build a new DocType (C)** — and why.

Field names in the "standard anchor" column were read from the downloaded ERPNext source; each is spot-checkable via `appendix/spot-check-paths.md` and tagged `[verify-vs-v16]` where the source tree is newer than the v16 target.

## 1. Verdict table — asset spine (release 1)

| # | Business entity | Verdict | Standard anchor | Reasoning |
|---|---|---|---|---|
| 1 | Customer | **R** | `selling/doctype/customer` (`customer_name, customer_group, territory, default_price_list, default_receivable_accounts, tax_id, on_hold, is_frozen, portal_users`) | Fleet accounts are ordinary Customers. Segmentation via `customer_group`; branch scoping via User Permissions. |
| 2 | GPS device / speed limiter (physical unit) | **E** | `stock/doctype/serial_no` | **The central decision of this design.** `Serial No` *is* the device record: `name` = serial (PK-unique for free), plus `item_code, warehouse, status, customer, batch_no, purchase_rate, location, employee, warranty_period, warranty_expiry_date, amc_expiry_date, maintenance_status, asset, reference_doctype/reference_name`. Only IMEI and BARO-specific state are missing. |
| 3 | Device model / product | **R** | `stock/doctype/item` (`has_serial_no, serial_no_series, warranty_period, barcodes, quality_inspection_template, safety_stock, reorder_levels, inspection_required_before_delivery`) | Series-warrantied stock item; reorder alerts are native. |
| 4 | Barcode / QR for scanning | **R** | `stock/doctype/item_barcode` (child of Item), `stock_entry.scan_barcode`, `stock_entry.last_scanned_warehouse` | Scanning into stock movements is native. Note the DocType is **`item_barcode`, not `barcode`**. Per-unit IMEI/ICCID lookup is a search-index resolve, not an Item barcode (§4). |
| 5 | Warehouse, transfers, reconciliation | **R** | `stock/doctype/warehouse` (`warehouse_type, is_rejected_warehouse, parent_warehouse, company, account, customer`), `stock/doctype/stock_entry` (`purpose, from_warehouse, to_warehouse, items`) | A quarantined/faulty device area maps to `is_rejected_warehouse` or a dedicated `warehouse_type` — no BARO warehouse object needed. |
| 6 | Vehicle / fleet register | **C** `Baro Vehicle` | links `selling/customer`, optional `assets/doctype/asset` | Nothing standard models plate/VIN/tracking state. `Asset` is for capitalised, depreciating records; using it for every vehicle forces depreciation on non-accounting objects. Link to `Asset` only when BARO capitalises a vehicle. |
| 7 | Device ↔ vehicle ↔ customer over time | **C** `Baro Device Assignment` | — | The spine's core record. No standard DocType expresses a time-bounded relationship with an ACTIVE uniqueness rule. |
| 8 | SIM card | **C** `Baro SIM Card` | optional link to `stock/doctype/serial_no` when SIMs are stock-tracked | ICCID/MSISDN/telco/plan/expiry/cost lifecycle is not device lifecycle. Keeping it off `Serial No` prevents a single hot record owning two independent state machines. |
| 9 | Installation | **E** | `selling/doctype/installation_note` + `installation_note_item` (`item_code, serial_no, qty, serial_and_batch_bundle, prevdoc_doctype/prevdoc_docname`) | Installation Note already carries customer, address, contact, project, `inst_date/inst_time`, `status`, naming series, and is submittable, and `Delivery Note` exposes `per_installed` / `installation_status`. A `BARO Installation` DocType would fork that link. |
| 10 | Technician work / job card | **R (later)** | `manufacturing/doctype/job_card` (+ `_item`, `_operation`, `_time_log`, `_scheduled_time`), `maintenance/doctype/maintenance_visit` + `maintenance_visit_purpose` (`item_code, serial_no, work_details, service_person, work_done`) | Field service work orders are a later-phase workspace; the spine must not pre-commit to Job Card semantics. |
| 11 | Installation inspection / quality | **E** | `stock/doctype/quality_inspection` (`inspection_type, reference_type/reference_name, item_code, item_serial_no, quality_inspection_template, specification_details, readings, inspected_by, verified_by, status, manual_inspection`) | A `Quality Inspection Template` per device type gives the blueprint's checklist + readings + evidence, is linkable to any reference, and is already understood by auditors. `BARO Service Inspection` is rejected. |
| 12 | Warranty / fault claim | **R** | `support/doctype/warranty_claim` (`serial_no, customer, complaint, issue_details, warranty_amc_status, warranty_expiry_date, resolution_details, service_address`) | Direct fit, already links on `serial_no`. |
| 13 | Helpdesk ticket | **R** | `support/doctype/issue` (+ native SLA fields listed in `02-app-boundary-decision.md` §6) | Later-phase workspace; no new DocType. |
| 14 | Contract / agreement | **R** | `crm/doctype/contract` (`party_type, party, start_date, end_date, status, contract_template, contract_terms, requires_fulfilment, fulfilment_deadline`) + `crm/doctype/contract_template` | Contract expiry automation hangs here. |
| 15 | Subscription & recurring billing | **R** | `accounts/doctype/subscription` (40 fields: `plans, subscription_period, current_invoice_start/end, next_billing_period_start/end, generate_invoice_at, days_until_due, cancel_at_period_end, party_type/party, sales_tax_template, cost_center`) + `accounts/doctype/subscription_plan` (`item, price_list, cost, billing_interval, billing_interval_count, payment_gateway`) | Rebuilding this is the single most expensive avoidable error in the project. |
| 16 | Subscription ↔ device bundle | **Deferred** | — | Build `Baro Subscription Asset` **only** if one subscription must cover many devices/vehicles (stakeholder question Q4). If 1:1, a Custom Field on `Subscription` suffices. |
| 17 | Firmware version history | **C** `Baro Firmware History` | links `stock/serial_no` | Append-only history; embedding it as a child table on `Serial No` grows the hottest record in the system. |
| 18 | Device RMA / replacement | **C** `Baro Device RMA` | cross-links `support/warranty_claim`, `stock/stock_entry` | Warranty Claim records a complaint and resolution; it does not move stock or express disposition. Reference both, own the RMA state machine. |
| 19 | Platform device mapping | **C** `Baro Platform Mapping` | — | External id namespace; the reconciliation join key and inbound idempotency anchor. |
| 20 | Integration log / dead letter | **C** `Baro Integration Log` | complements Frappe `Error Log` | Frappe's Error Log captures exceptions only; BARO needs received/processed/retrying/dead with idempotency keys. |
| 21 | Platform credentials & endpoints | **C** `Baro GPS Platform` (one row per platform) | Frappe `Password` fieldtype for secrets | Holds base URL, auth type, `Password`-type secret fields, rate limit and timeout per platform. A `Single` cannot hold multiple platforms, and secrets must never live in a plain Data field. Also serves as the Link target that makes `Baro Platform Mapping` composite-uniqueness work (`30-schema-conventions.md` §3). |
| 22 | Projects, tasks, milestones | **R** | `projects/doctype/project`, `projects/doctype/task` (`subject, project, issue_type, priority, depends_on_tasks, exp_start_date, act_start_date, completed_by, total_billing_amount`) | Note: the DocType is **`Task`, not `project_task`**. Fleet-rollout profitability reuses `Project` costing fields (`total_costing_amount, total_purchase_cost, total_billed_amount`). |
| 23 | Scheduling / appointment / dispatch | **R** | `crm/doctype/appointment` (`scheduled_time, calendar_event, appointment_with, party, status`), `crm/doctype/appointment_booking_settings`, Frappe `Calendar Event` | Covers step 4 of the 11-step journey without custom schema. |
| 24 | Employee / technician | **R** | `setup/doctype/employee` (`employee_name, department, attendance_device_id` unique) | Present in ERPNext `setup` for legacy links; the full HR lifecycle requires the separate `hrms` app. |
| 25 | Claims, payroll, appraisal, performance | **Deferred** | `hrms` app | Out of release-1 scope (`90-later-phase-backlog.md`). |
| 26 | Reconciliation / revenue-assurance exception | **C** `Baro Reconciliation Exception` | contrast `support/doctype/issue`, `stock/doctype/stock_reconciliation` | The blueprint's revenue-assurance checks (unbilled active vehicles, terminated-but-billed subscriptions, ERP-vs-platform fleet count mismatch) need a tracked, assigned, closable work item. `Issue` is customer-facing and SLA-metered — injecting system-generated data-quality rows would pollute the support queue and expose internal mismatches to portal users. `Stock Reconciliation` is a financial adjustment document, not an exception inbox. Non-submittable, never auto-mutates anything (`40` §1). |

## 2. Net result

**Nine business DocTypes + one Single** in release 1: `Baro Vehicle`, `Baro Device Assignment`, `Baro SIM Card`, `Baro Platform Mapping`, `Baro Firmware History`, `Baro Device RMA`, `Baro Integration Log`, `Baro Reconciliation Exception`, `Baro GPS Platform`, and `Baro Operations Settings` (Single) — plus 15 Custom Fields on six standard DocTypes (`10-data-dictionary.md` §3). The Table MultiSelect in `Baro Operations Settings` auto-generates one small child DocType, which is the only child table created.

Everything else the blueprints listed as "custom" is either already in ERPNext or is a workspace/permission configuration concern, not schema.

## 3. The Serial No duplication trap

The blueprints' `BARO Device Lifecycle Management` module invites a `BARO Device` DocType. It must not be built:

- Stock ledger, delivery, installation and warranty records all key on `Serial No`. A parallel device record means device availability, valuation and location exist in two places, and the first reconciliation report finds them disagreeing.
- Device identity, warranty and ownership fields already live on `Serial No`.
- The only true gaps are IMEI, BARO lifecycle state, firmware, and platform mapping — which is exactly what the Custom Fields and the four satellite DocTypes provide.

**Rule:** anything that answers "which physical unit is it" or "where is it in stock" resolves to `Serial No`. Anything that answers "what is it connected to over time" or "what did the platform say about it" is a BARO record linking to `Serial No`.

## 4. One-scan lookup: not a barcode feature

The blueprint's "scan an IMEI or SIM barcode opens its complete history" is a **search-resolve**, not an Item barcode: `item_barcode` belongs to Item (a product type), while IMEI/ICCID/plate identify one unit. Design:

- `search_index=1` on `baro_imei`, `baro_iccid`, `baro_plate_no`, `platform_device_id` (`30-schema-conventions.md` §4).
- One whitelisted resolve endpoint: scan string → try `Serial No.baro_imei` → `Baro SIM Card.baro_iccid` → `Baro Vehicle.baro_plate_no` → redirect to the record's Device 360 / Fleet view.
- Item barcodes remain for product-level scanning in Stock Entry (`scan_barcode`).

## 5. Rules for future change requests

A request to add a BARO DocType is approved only if it answers all four:

1. Which standard DocType was considered, and why does it not fit? (cite the field list, not the module name)
2. Does it fork a fact ERPNext already owns (stock balance, invoice state, customer identity)? If yes, reject and extend.
3. Is it a *time series* or an *entity*? Time series get their own append-only DocType; entities must attach to the standard one.
4. Which of the seven release-1 DocTypes could carry it as a field or child table instead?

## 6. Rejected blueprint items and why

| Blueprint item | Disposition |
|---|---|
| `BARO Device` doctype | Rejected → extend `Serial No` |
| `BARO Installation` doctype | Rejected → extend `Installation Note` |
| `BARO Device Assignment` | Accepted as new (only genuine gap) |
| `BARO Subscription Asset` | Deferred pending Q4 |
| Six custom apps | Rejected for release 1 → `02-app-boundary-decision.md` |
| New billing engine | Rejected → `Subscription` / `Subscription Plan` |
| Telemetry storage in ERP | Rejected → `01-architecture-overview.md` §5 |
| `project_task`, `barcode` doctype names | Corrected → `Task`, `item_barcode` |

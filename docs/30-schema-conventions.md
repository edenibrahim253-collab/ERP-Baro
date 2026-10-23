# 30 — Schema and Code Conventions

Rules the `baro_core` app must follow. They exist to keep the app upgradeable, diffable and reviewable — not for style.

## 1. App file layout

```
baro_core/
├── pyproject.toml                     # frappe pin matching the v16 line (see 04)
├── license.txt  README.md  MANIFEST.in
├── baro_core/
│   ├── hooks.py                       # doc_events, scheduler_events, fixtures, after_migrate
│   ├── patches.txt                    # ONE ordered chain (see 02 §2)
│   ├── modules.txt                    # baro_fleet, baro_devices, baro_connectivity,
│   │                                  # baro_field_service, baro_billing, baro_integrations, baro_settings
│   ├── <module>/doctype/<doctype_snake>/<doctype_snake>.json|.py
│   ├── baro_core/number_rule/…        # only if a numbering rule is needed later
│   ├── overrides/                     # only where a standard controller truly must be extended
│   ├── public/js/baro_*.js            # cosmetic client scripts, never enforcement
│   ├── templates/                     # print formats, 360 pages
│   ├── integrations/                  # GPS connector, idempotency, retry poller
│   │   ├── base.py                    # platform-agnostic client contract
│   │   ├── <vendor>.py                # one module per platform vendor
│   │   └── handlers.py                # inbound event → doc mutation, all idempotent
│   ├── api.py                         # whitelisted endpoints (§10)
│   ├── jobs.py                        # scheduler entrypoints (§11)
│   └── tests/                         # test_vehicle, test_assignment, test_uniqueness, test_integration
```

**One module partition per `02` §3.** Controllers stay thin: state transitions and derived writes in the DocType controller; cross-DocType effects in `doc_events` handlers, so the same logic is reachable from the connector and from the UI.

## 2. Naming

| Object | Pattern | Example |
|---|---|---|
| DocType | `Baro <Singular Noun>` | `Baro Device Assignment` |
| Custom field | `baro_<meaning>` | `baro_imei` |
| Standard field used as-is | unchanged | `customer`, `warehouse` |
| Python module | snake_case of DocType | `baro_device_assignment.py` |
| Whitelisted endpoint | `baro_core.api.<verb>_<noun>` | `baro_core.api.resolve_scan` |
| Scheduler entrypoint | `baro_core.jobs.<verb>_<noun>` | `baro_core.jobs.flag_inactive_devices` |
| Workspace | `BARO <Area>` | `BARO Fleet` |
| Report | `BARO - <Topic>` | `BARO - Assignment History` |
| Print format | `BARO <Doctype> Format` | `BARO Installation Format` |
| Role | `BARO <Function>` | `BARO Connectivity Admin` |
| Notification | `BARO - <Trigger id>` | `BARO - T03 Contract Expiring` |
| Patch | `YYYY-MM-DD <snake_description>` | `2026_03_14 add_active_key_unique_indexes` |

**Never** reuse an ERPNext fieldname for different semantics, and **never** name a BARO object the same as a standard one (`Task`, `Asset`, `Item`, `Subscription`, `Contract`, `Installation Note` are taken).

## 3. Autoname policy

| Case | Mechanism | Used by | Why |
|---|---|---|---|
| Human-facing internal id | Naming series `BARO-XXX-.####` | Vehicle, Assignment, SIM, Firmware History, RMA, Integration Log, Reconciliation Exception | Stable across edits; supports amend; readable in support calls |
| **Composite natural key** | `autoname: format:{field_a}-{field_b}` | `Baro Platform Mapping` = `{baro_platform}-{platform_device_id}` | Gets DB-level uniqueness for free from the primary key — no DDL, survives `bench migrate`, and is a readable reference in logs |
| Name is the natural key already | `autoname: field:<name field>` | `Baro GPS Platform` = `baro_platform_name` | One row per platform; PK uniqueness |
| External identity | Use the standard record's own name | device = `Serial No` name | Reuses ERPNext's PK uniqueness for the physical unit |
| Never | hash / random / prompt for business records | — | Breaks amend, traceability and import idempotency |

Rules:
1. A business identifier that can be re-issued externally (plate, ICCID, IMEI) must **not** be the `name` — it becomes a unique field instead, so history survives re-issue.
2. Format autoname components must be `reqd` and normalised in `validate` before naming runs, or a re-save can orphan the name.
3. Series prefixes are declared in one place (`Baro Operations Settings`) so branch/company numbering changes are configuration, not code.

## 4. List, filter and index conventions

| Rule | Requirement |
|---|---|
| Every Link to a spine record (`customer`, `baro_vehicle`, `serial_no`, `baro_sim_card`, `baro_platform`) sets `in_list_view: 1` and `in_standard_filter: 1` | Lists must be usable without opening records |
| Every externally scannable identifier sets `search_index: 1`: `Serial No.baro_imei`, `Baro SIM Card.baro_iccid`, `Baro SIM Card.baro_msisdn`, `Baro Vehicle.baro_plate_no`, `Baro Vehicle.baro_vin`, `Baro Platform Mapping.platform_device_id`, `Baro Integration Log.baro_correlation_id` | Global search and One-Scan resolve depend on it. Precedent in the shipped tree: `Serial No` indexes `serial_no`, `maintenance_status`, `company` |
| Each DocType declares `search_fields` covering its scannable keys + customer | Enables the resolve endpoint to use standard search rather than bespoke SQL |
| `fetch_from` for any denormalisable label (`baro_customer_name`, `baro_device_item`, `baro_imei` on the assignment) | A typed copy of a related name is a future data error |
| UQ-DRV columns (`baro_active_serial_key`, `baro_active_vehicle_key`) are `read_only`, hidden from list view | They are index machinery, not user data |
| Currency/Date/Datetime get explicit `precision`/`default` where they drive automation | Silent timezone or rounding drift breaks expiry jobs |
| `track_changes: 1` on all eight business DocTypes + both Singles | BARO requires an audit trail on device and customer-status changes |

## 5. Fieldtype policy

| Need | Fieldtype | Notes |
|---|---|---|
| Identifiers (IMEI/ICCID/plate/VIN) | `Data` + `unique` + validation | Never `Int` (leading zeros), never `Long Text` |
| State | `Select` with values defined in `10` §6 | Never `Autocomplete`/`Data` — free text destroys automation |
| Relations | `Link` (or `Dynamic Link` for the integration log's polymorphic reference) | Always with a matching `DocField.link_filters` where the domain is narrow |
| Secrets (API keys, PIN/PUK, webhook signing) | `Password` | Never `Data`; never in fixtures; never printed (`21` §3, §8) |
| Evidence | standard `File` attachments on the document | No BARO attachment DocType |
| Signature | `Signature` | `Installation Note.baro_customer_signature` |
| Money | `Currency` with company currency default | ETB is the base; multi-currency deferred |
| Long prose | `Text` / `Small Text` | `Small Text` for notes that appear in reports |
| Quantities read from the platform (data usage) | **not stored** | `01` §5 |

## 6. `docstatus` and `allow_on_submit`

| DocType | Submittable | Rationale |
|---|---|---|
| `Baro Device Assignment` | yes | It is the record service and billing depend on; needs amend/cancel semantics |
| `Baro SIM Card` | yes | Activation/suspension are contractual acts |
| `Baro Device RMA` | yes | Asset movement and supplier credit depend on it |
| `Baro Vehicle` | no | Master data; its *changes* are audited by `track_changes` |
| `Baro Platform Mapping` | no | Reference data written by the connector |
| `Baro Firmware History` | no | Append-only log |
| `Baro Integration Log` | no | Append-only log |
| `Baro Reconciliation Exception` | no | A work item, not a business transaction; its resolution is recorded in-place, and the corrective edit happens on the real document |
| `Baro GPS Platform` / `Baro Operations Settings` | no | Configuration |

`allow_on_submit` is granted **only** to `Baro Device Assignment.to_time` (a service ending must not require an amendment) and to the UQ-DRV key columns. Every other on-submit change is an amendment. This is a deliberate, reviewable exception list.

Cancellation rules are in `21` §2 (`on_cancel`) — a document that produced service or billing history is amended, never cancelled.

## 7. Derived-field discipline

Three classes, each with exactly one writer:

| Class | Definition | Examples | Rule |
|---|---|---|---|
| **FF** | `fetch_from` a linked record | `baro_customer_name`, `baro_device_item` | Frappe populates it; read-only everywhere; never recomputed by hand |
| **DRV** | written by a controller/`doc_events` | `Baro Vehicle.baro_current_device`, `Baro SIM Card.baro_installed_device`, `Serial No.baro_firmware_version` | UI read-only for every human role; the authority document is named in `21` §9 |
| **INT** | written only by the connector | `Serial No.baro_last_comm_at`, `Baro Platform Mapping.baro_*_at`, `Baro GPS Platform.baro_last_*` | Permission granted to `BARO Integrator` only; a human editing these is an audit event |

No field may be both user-editable and derived. `80` checks that every RO/DRV/INT field names its writer.

## 8. Fixture packaging (how BARO schema reaches production)

Everything is version-controlled as app fixtures, exported in a deterministic order:

```python
BARO_DT = ["Baro Vehicle", "Baro Device Assignment", "Baro SIM Card",
           "Baro Platform Mapping", "Baro Firmware History", "Baro Device RMA",
           "Baro Integration Log", "Baro Reconciliation Exception", "Baro GPS Platform"]
STD_DT  = ["Serial No", "Installation Note", "Customer", "Subscription",
           "Quality Inspection", "Issue"]

fixtures = [
  {"doctype": "Role", "filters": [["name", "like", "BARO %"]]},
  {"doctype": "DocType", "filters": [["module", "in", BARO_MODULES], ["is_standard", "!=", 1]]},
  # Custom Field.name is "<dt>-<fieldname>", so a name filter would never match:
  {"doctype": "Custom Field", "filters": [["fieldname", "like", "baro_%"]]},
  # Property Setter.name is a generated hash, so filter on its doc_type column instead:
  {"doctype": "Property Setter", "filters": [["doc_type", "in", BARO_DT + STD_DT]]},
  {"doctype": "Workflow", "filters": [["name", "like", "BARO%"]]},
  {"doctype": "Assignment Rule", "filters": [["assign_condition", "like", "%baro%"]]},  # later phase only
  {"doctype": "Notification", "filters": [["subject", "like", "BARO%"]]},
  {"doctype": "Workspace", "filters": [["title", "like", "BARO%"]]},
  {"doctype": "Report", "filters": [["name", "like", "BARO%"]]},
  {"doctype": "Print Format", "filters": [["name", "like", "BARO%"]]},
  {"doctype": "Baro Operations Settings"},   # Single shipped as fixture WITHOUT secrets
]
```

`Property Setter.doc_type` and `Custom Field.fieldname` are Frappe-framework columns, not ERPNext ones, so they are outside the archive this package was checked against — tagged `[verify-vs-framework]` alongside `04` §4's list (`appendix` §1 notes the framework is not in the zip).

Rules:
1. **Secrets are never fixtures.** `Baro GPS Platform` Password fields are excluded from export; production sets them in the UI.
2. `Property Setter` and `Custom Field` fixtures make the design re-appliable to a fresh site — this is what makes staging→prod reproducible.
3. Order matters: Roles → DocTypes → Custom Fields → Property Setters → Workflows → Notifications → Workspaces/Reports.
4. Never export `DocPerm` rows inline-only; they live on the DocType JSON for BARO DocTypes and as fixtures for standard ones.
5. `after_migrate` hook re-applies the UQ-DRV index patch (`31` §5) idempotently.

## 9. Property Setters expected on standard DocTypes

| Target | Property | Purpose |
|---|---|---|
| `Serial No` | layout: add a "BARO Device" section | keeps custom fields grouped, not scattered |
| `Serial No` | `baro_device_status`, `baro_last_comm_at`, `baro_firmware_version` → `read_only` for non-manager roles | derived-field discipline (§7) |
| `Installation Note` | make `customer_address`, `contact_person` mandatory via fetch defaults; add BARO section | installer completeness |
| `Installation Note` | `baro_activation_status`, `baro_quality_inspection` → read-only for Installer | WF-only fields |
| `Issue` | add `baro_vehicle` to list view | support triage by fleet |
| `Subscription` | add `baro_service_level` to list view | billing ops |
| `Item` | none | device category is Item Group, not a new field |

## 10. API conventions (`api.py`)

| Endpoint | Behaviour |
|---|---|
| `baro_core.api.resolve_scan` | input string → tries `Serial No.baro_imei`, `Serial No.name`, `Baro SIM Card.baro_iccid`/`msisdn`, `Baro Vehicle.baro_plate_no`, `Baro Platform Mapping.platform_device_id`; returns doctype+name for the 360 redirect. Permission-checked per role — a technician cannot resolve a record they may not read |
| `baro_core.api.get_device_360` | aggregated read (stock, assignments, firmware, RMA, mapping, warranty, tickets). Read-only by design |
| `baro_core.api.webhook_gps` | inbound platform events; requires `cmd`-level HMAC verification against `Baro GPS Platform.baro_webhook_secret`; **idempotent** — writes `Baro Integration Log` first, then applies (`50` §4–5) |
| `baro_core.api.get_assignments` | outbound feed for internal tools; paginated, permission-filtered |
| `baro_core.api.run_reconciliation` | the manual "Run now" behind `51` §2 — same implementation the cron calls, restricted to `BARO System Manager`/`BARO Integrator`, refuses if the platform lock is held, and writes only `Baro Reconciliation Exception` rows |

Rules: every endpoint is `@frappe.whitelist()`, `methods` declared explicitly, `frappe.has_permission` checked **server-side**, no endpoint performs a state change that bypasses a Workflow transition, and no endpoint accepts a raw SQL fragment as a filter.

## 11. Scheduler conventions (`jobs.py`)

| Job | Frequency | Contract |
|---|---|---|
| `flag_contracts_expiring` | daily (`60` T3) | notify only; writes no state |
| `flag_overdue_invoices` | daily (T5) | notify finance; may raise a `Billing mismatch` exception (`51` RA-5) — never suspends |
| `flag_sim_expiry` | daily (T7) | flag + notify; **does not** set `Expired` (`21` §3) |
| `flag_certificates_expiring` | daily (T8) | vehicle certificate/registration/insurance windows; notify only |
| `flag_reorder_points` | daily (T9) | reads standard reorder data; notifies `baro_reorder_notice_role`; creates no purchase request |
| `flag_warranty_expiry` | weekly (T10) | digest to `BARO Service Supervisor` |
| `flag_inactive_devices` | hourly (T6) | reads `Serial No.baro_last_comm_at` vs `baro_inactive_threshold_hours`; creates `Issue` **draft** or notification — never auto-submits |
| `sync_platform_fleet` | per `Baro GPS Platform.baro_pull_interval` | upsert mapping + last-comm only; performs no diff (`51` §1) |
| `process_integration_retries` | every 5 min | claim rows with a Redis lock so two workers cannot retry the same row |
| `run_platform_reconciliation` | per `baro_reconciliation_cron` (`51` §2) | one lock per platform; writes `Baro Reconciliation Exception` rows only, never documents; aborts without writing when the platform read fails (`51` §8) |
| `archive_integration_logs` | weekly | honours `baro_log_retention_days`; extends to auto-cleared, non-billable exception rows (`51` §9) |

Every job: idempotent, bounded (batch + limit), logs to `Baro Integration Log` or `Error Log`, guarded by a named lock, and **cannot** submit or cancel a business document without a Workflow transition executed by a user.

## 12. Reports, print formats, workspaces

- Reports: Query Report where a single SQL suffices (assignment history, pending activations); Script Report for reconciliation and 360 views where permission filtering must run through Frappe, not raw SQL.
- Print formats: `BARO Installation Format` (customer-facing, includes signature + certificate references), `BARO Assignment Certificate` for compliance. Amharic/English print templates pending Q1.
- Workspaces in release 1: the eleven views in `20` §7 (3 workspaces, 2 × 360 pages, One-Scan, 5 reports/lists) — **not** the 24 proposed workspaces (`90`).

## 13. Translations and locale

User-facing strings (labels, error messages, notifications) are extracted for translation; Amharic localisation is deferred to Q1 but no design may assume English-only strings are final. Ethiopian locale means dates display `dd/MM/yyyy` while storage stays ISO — never encode a display format into a validation rule.

## 14. Testing conventions

| Test | Minimum case |
|---|---|
| `test_uniqueness.py` | duplicate IMEI/ICCID/MSISDN/plate rejected; UQ-DRV keys null after ending; **concurrent** overlapping submits (two threads) |
| `test_assignment.py` | the full hook map in `21` §2, including cancel-after-activation refusal |
| `test_vehicle.py` | plate normalisation, owner change while active |
| `test_rma.py` | replacement chain, warranty override approval, scrap guard |
| `test_integration.py` | idempotent replay, retry backoff, dead-letter, webhook HMAC failure |
| `test_permissions.py` | role × document matrix assertions from `41`, incl. record-level scoping |
| `test_import.py` | the 1,000-assignment CSV scenario (U10) |

Tests run against a real MariaDB test site (`bench run-tests`), not mocks — a uniqueness rule proven against a mocked DB proves nothing.

## 15. Branching and release hygiene

`main` (production-tagged) ← `staging` ← `develop` ← feature branches, with ERPNext/Frappe pins recorded in `pyproject.toml` and never floated. Release checklist: fixtures export diff → `bench migrate` on staging → run the §14 suite → reconciliation dry-run on staging data → approval by a named `BARO Approver` before production.

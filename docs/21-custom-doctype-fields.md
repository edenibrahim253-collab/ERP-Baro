# 21 — Custom DocType Behaviour Specification

Fields are defined once in `10-data-dictionary.md` §4 and are **not** repeated here. This document specifies behaviour: naming, states, validation, side effects, permissions and tests per DocType.

Error messages are written as they should appear to a user — they are part of the spec, because a validation rule nobody can diagnose is a rule that will be bypassed.

---

## 1. `Baro Vehicle` (module `baro_fleet`, non-submittable)

**Purpose:** the fleet register unit — plate, VIN, owner, compliance dates, and derived current device.

**States:** `Registered` (created, no active device) → `In-Service` (has an Active assignment) → `Transferred` (owner changed, pending new registration) → `Retired` (scrapped/sold/decommissioned). `baro_status` is **DRV**: `Registered → In-Service` and back are written by assignment events; `Transferred`/`Retired` are manual with a reason and require `BARO Fleet Officer` + `BARO Approver`.

**Naming:** series `BARO-VEH-.####`. Plate is *not* the name (plates are re-issued in Ethiopia when a vehicle changes owner; the internal id must survive that).

| Hook | Rule | Error text |
|---|---|---|
| `validate` | Normalise `baro_plate_no`: uppercase, strip spaces/`-`/`_` | — (silent) |
| `validate` | Plate must match the configured Ethiopian pattern (kept in `baro_settings`, not hard-coded) | `Plate {x} does not match the Ethiopian format` |
| `validate` | VIN, when present, must be 17 chars | `VIN must be 17 characters` |
| `validate` | `customer` required; if changing owner while an Active assignment exists → block | `End or supersede assignment {name} before changing the vehicle's customer` |
| `validate` | Warn (non-blocking) on near-duplicate plate | `Similar plate {y} already exists for {customer}` |
| `before_rename` | Not applicable (non-submittable), but plate change requires `baro_notes` reason | `A plate change requires a reason` |
| `on_update` | Re-check derived `baro_current_device` consistency | — |

**Derived read-only:** `baro_current_assignment`, `baro_current_device`, `baro_customer_name` (FF). No BARO code may write these from the UI; they follow `Baro Device Assignment`.

**Permissions:** create/edit `BARO Fleet Officer`, `BARO Sales Officer`; delete only `BARO System Manager` and only while never assigned (a vehicle that has had an assignment cannot be deleted — cancel/retire instead); read `BARO Support Agent`, `BARO Installer` (record-scoped by customer/branch).

**Integrations:** feeds reconciliation (`51`), platform mapping denormalisation, compliance notifications (`60` T8).

**Open questions:** Q6 — should `baro_fleet_group` become a master (per-group pricing/reporting)?

---

## 2. `Baro Device Assignment` (module `baro_field_service`, **submittable**)

**Purpose:** the time-bounded relationship device ↔ vehicle ↔ customer (↔ SIM). The spine's authority record.

**States:** `Draft` (docstatus 0) → `Pending Approval` (submitted, workflow) → `Active` (approved) → `Ended` (to_time set) or `Superseded` (replaced by another assignment). Cancellation is a separate axis (docstatus 2) and is only legitimate before activation.

**Naming:** `BARO-ASSIGN-.####`.

**Validation hook map**

| Hook | Rule | Error text |
|---|---|---|
| `validate` | `customer` must equal `baro_vehicle.customer` | `Vehicle {plate} belongs to {other}; the assignment customer must match` |
| `validate` | `serial_no` must be a device item (Item Group in the configured GPS device groups) | `Serial {x} is not a GPS device item` |
| `validate` | Device `baro_device_status` ∈ {Reserved, Allocated, Returned, Faulty} — i.e. issuable, and not already Active | `Device {x} is {status} and cannot be assigned` |
| `validate` | Reserved-for-customer check: device reserved for another customer cannot be assigned here | `Device {x} is reserved for {other customer}` |
| `validate` | Customer not `on_hold` / `is_frozen` / disabled | `Customer {name} is blocked; clear the hold before assigning` |
| `validate` | `from_time` required, not more than `n` days in the future (n from `baro_settings`, default 0), and `to_time > from_time` when set | `Active To must be after Active From` |
| `validate` | `baro_assignment_type = Replacement` requires `baro_previous_assignment` | `A replacement must reference the assignment it replaces` |
| `validate` | SIM, when set, must not be installed in another device | `SIM {iccid} is installed in {serial}` |
| `validate` | If `baro_previous_assignment` set, its `to_time` must be ≤ this `from_time` | `Overlaps the assignment being replaced` |
| `before_submit` | Overlap check under lock + `SELECT … FOR UPDATE` (`31` §4) — both device and vehicle | `Device {x} is already assigned to {plate} from {from_time}` |
| `before_submit` | Maintain `baro_active_serial_key` / `baro_active_vehicle_key` | (duplicate-key error surfaces from the index if raced) |
| `on_submit` | Device `→ Installed`; vehicle `baro_current_assignment`/`baro_current_device`; SIM `baro_installed_device`/`baro_installed_vehicle`; create activation-verification `Task` (subject `Verify activation — {plate}`, `issue_type`, `completed_by = baro_technician`, `exp_end_date = from_time + 2 days`); write `Baro Firmware History` if the device's `baro_firmware_version` is known; back-fill `Installation Note.baro_assignment` when the note already exists | — |
| `on_update_after_submit` | Any change to `to_time` / `baro_status` re-runs the overlap check for the resulting window; ending an assignment sets device `→ Returned` (or `RMA` when an open RMA exists) and clears the vehicle's derived current fields; clears the UQ-DRV key to NULL | `Ending this assignment would overlap {name}` |
| `on_cancel` | Allowed only when `baro_activation_status = Not Verified` **and** no Installation Note is submitted against it **and** no billing period consumed it; revert all derived fields | `Assignment {name} has produced service or billing history; amend it instead of cancelling` |

**Maker-checker:** the submitter cannot approve (`40` §4). `baro_status`, `baro_activation_status` are WF-only. `baro_replaced_by`, keys, derived links are RO/DRV.

**Permissions:** create `BARO Installer`, `BARO Service Supervisor`, `BARO Fleet Officer`; submit `BARO Service Supervisor`; approve transition `BARO Approver`; cancel `BARO System Manager` + reason; record-scoped read for technicians via Permission Query Condition `baro_technician = login employee` (`41` §5).

**Integrations:** `on_submit` is the event the GPS-platform connector listens to for activation; `Installation Note.baro_activation_status = Verified` is written by the connector path (`50` §7), not by a human.

**Tests:** U2, U3, U4, U5, U6, U7, U11, U15 (from `20` §9).

---

## 3. `Baro SIM Card` (module `baro_connectivity`, **submittable**)

**States:** `Provisioned → Activated → Suspended → Deactivated → Expired`. The scheduled job **flags** approaching and passed expiry (`60` T7) and surfaces it in a report; it does **not** flip `baro_sim_status` to `Expired`, because a silent status change in a record technicians rely on would break field diagnostics. `Expired` is set by the Connectivity Admin from the flagged list.

**Naming:** `BARO-SIM-.####`. ICCID is not the name (it can be reprinted/reissued; the internal id must be stable for history).

| Hook | Rule | Error text |
|---|---|---|
| `validate` | ICCID: 19–20 digits, Luhn-valid (ICCID check digit is standard) | `ICCID {x} is not valid` |
| `validate` | MSISDN: normalise to national/international form per `baro_settings` pattern | `MSISDN {x} does not match the provider format` |
| `validate` | `supplier` required and flagged as a connectivity provider (Supplier Group) | `Select the connectivity provider` |
| `validate` | `baro_expiry_date` required and in the future when Provisioning | `Plan expiry must be in the future` |
| `validate` | Replacement chain must be acyclic | `Replacement chain loops back to {name}` |
| `before_submit` | SIM must not be installed in another device (checks `baro_installed_device`) | `SIM is installed in {serial}` |
| `on_submit` | If the SIM arrives via an assignment, status → `Activated` (driven by the assignment, not manually) | — |
| `on_update_after_submit` | Suspension/reactivation only through the workflow transition, with reason captured in `baro_notes` | `Suspension requires approval by a Finance Approver` |
| `on_cancel` | Revert `baro_installed_device/vehicle` if set | — |

**Secrets:** `baro_pin`/`baro_puk` use the **Password** fieldtype: never exported as fixtures, never printed, never logged, readable only by `BARO Connectivity Admin`.

**Permissions:** create/edit `BARO Connectivity Admin`; approve activation/suspension `BARO Approver` (+ `BARO Finance Approver` for suspension-for-payment); read `BARO Installer` (own assignments only), `BARO Support Agent`.

**Tests:** duplicate ICCID/MSISDN blocked; SIM cannot be in two devices; suspension requires approval.

---

## 4. `Baro Platform Mapping` (module `baro_integrations`, non-submittable)

**Purpose:** the only place an external platform's identity is stored; the reconciliation join key and inbound routing anchor.

**Naming:** `autoname: format:{baro_platform}-{platform_device_id}` — composite uniqueness via the primary key, no DDL, survives `bench migrate`.

| Hook | Rule | Error text |
|---|---|---|
| `validate` | `platform_device_id` non-empty and normalised (trim) | `Platform device id is required` |
| `validate` | One serial may have **at most one** mapping per platform (soft check; the PK handles the reverse direction) | `Device {serial} is already mapped on {platform}` |
| `validate` | `serial_no` must be a device item | — |
| `on_update` | Recompute `Serial No.baro_last_comm_at` = max over enabled mappings for that serial | — |
| Permission | `baro_last_comm_at`, `baro_platform_status`, `baro_last_sync_at` writable only by `BARO Integrator` | `Only the integration service may update platform status` |

**No submit:** mapping is reference data about an external system, not a business transaction. Keeping it non-submittable lets the connector upsert it freely while business records stay under workflow control.

**Permissions:** create/update `BARO Integrator` (API only), `BARO System Manager`; read `BARO Support Agent`, `BARO Stock Manager`.

---

## 5. `Baro Firmware History` (module `baro_devices`, non-submittable, append-only)

**Purpose:** device firmware/version timeline; supports support diagnostics and compliance ("which fleet units are on firmware X").

| Hook | Rule |
|---|---|
| `validate` | `serial_no` required, must be a device item |
| `validate` | `(serial_no, baro_firmware_version, baro_update_date)` must be unique — duplicate sync deliveries are the realistic cause |
| `after_insert` | Set `Serial No.baro_firmware_version` to the newest row's version (recompute by `baro_update_date`) |
| Permission | insert via UI `BARO Stock Manager`, via integration `BARO Integrator`; **no delete** for anyone but `BARO System Manager`; `baro_update_source` distinguishes human vs sync |

**Naming:** `BARO-FW-.####`.

---

## 6. `Baro Device RMA` (module `baro_devices`, **submittable**)

**States:** `Open → Awaiting Return → Received → Inspected → Replaced | Refunded | Scrapped | Closed`. Transitions are Workflow-gated (`40` §5); disposition requires `BARO Stock Manager`, and `Scrap` additionally `BARO Approver` (asset write-off). `Restock` is a **disposition value**, not a state: a restocked device returns to `In-Stock` while the RMA closes.

| Hook | Rule | Error text |
|---|---|---|
| `validate` | `serial_no` required; device cannot already have an open RMA | `RMA {name} is already open for this device` |
| `validate` | `customer` must equal the device's customer or the assignment's customer | `Customer mismatch` |
| `validate` | `baro_rma_type = In-warranty` requires `serial_no.warranty_expiry_date` ≥ raise date (or an explicit override with reason, recorded, requiring `BARO Approver`) | `Warranty expired on {date}; choose Out-of-warranty or get approval` |
| `validate` | `baro_replacement_serial` ≠ `serial_no` | `Replacement must be a different unit` |
| `before_submit` | Device status must be `Faulty`, `Active` (transitioning) or `Returned` | `Device is {status}` |
| `on_submit` | Device `→ RMA` |
| `on_update_after_submit` | `Replaced` requires `baro_replacement_serial` and creates nothing by itself: the **Service Supervisor** creates the new assignment; the RMA links `baro_old_assignment`/`baro_new_assignment` (DRV) and marks the old one `Superseded` |
| `on_update_after_submit` | `Scrapped` requires the device to have no Active assignment and a stock entry into the scrap/rejected warehouse | `Device {x} still has an active assignment` |
| `on_cancel` | Revert device status to its pre-RMA value (stored in `baro_notes` audit or via Version) | — |

**Naming:** `BARO-RMA-.####`.
**Permissions:** create `BARO Support Agent`, `BARO Installer`; approve `BARO Approver`; financial link `BARO Accounts User`; delete none (cancel + amend).

---

## 7. `Baro Integration Log` (module `baro_integrations`, non-submittable, append-only)

**Purpose:** every inbound event and outbound call, with retry state and dead-letter handling. It *is* the "documented synchronization error handling" acceptance criterion.

| Rule | Spec |
|---|---|
| Uniqueness | `baro_idempotency_key` **UQ**. On conflict the handler returns the existing row's result instead of re-processing (`50` §4) |
| Insert rights | `BARO Integrator` only via the connector; humans cannot create log rows |
| Update rights | status/attempts/next-retry/error fields writable by the retry poller only; `Dead → Retrying` re-drive requires `BARO System Manager` and writes a note |
| Delete/retention | no delete permission; archived after `baro_log_retention_days` (default 90, on `Baro Operations Settings`) by an export-and-purge job, documented in `50` §7 |
| Payload | never inline: `baro_payload_ref` → `File`, with private storage |
| PII/secrets | the log writer must strip `Authorization`, API keys and secrets before persisting; message text is truncated |

**Naming:** `BARO-INTLOG-.####`.

---

## 8. `Baro GPS Platform` (module `baro_settings`, non-submittable master)

**Purpose:** per-platform endpoint, auth, limits and health. One row per tracking platform.

| Rule | Spec |
|---|---|
| Naming | `field:baro_platform_name` (PK-unique) |
| Secrets | `baro_api_key`, `baro_api_secret`, `baro_webhook_secret` are **Password** fields: never fixtures, never printed, never logged; readable by `BARO System Manager` only |
| Write of health fields | `baro_last_success_at`, `baro_last_failure_at`, `baro_last_error` — `BARO Integrator` only |
| `baro_enabled` off | blocks the scheduler for that platform and makes new mappings rejected (`validate` on Platform Mapping) |
| Change control | edits to base URL/auth/rate limit require `BARO System Manager` and are `track_changes`-audited |

**Open questions:** Q2 (platform vendors, auth model, official limits) makes most of this table concrete.

---

## 9. Cross-DocType dependency matrix

| DocType | Reads | Writes on others |
|---|---|---|
| `Baro Vehicle` | Customer, Assignment | — |
| `Baro Device Assignment` | Vehicle, Serial No, SIM, Installation Note, Employee, Project, Appointment | Serial No status, Vehicle derived links, SIM derived links, Firmware History insert, Task insert, Installation Note custom fields |
| `Baro SIM Card` | Supplier, Assignment | Serial No (via assignment only) |
| `Baro Platform Mapping` | GPS Platform, Serial No | Serial No `baro_last_comm_at` (max) |
| `Baro Firmware History` | Serial No | Serial No `baro_firmware_version` (latest) |
| `Baro Device RMA` | Serial No, Warranty Claim, Quality Inspection, Assignments, Purchase Invoice | Serial No status, Assignment status (Superseded via supervisor action) |
| `Baro Integration Log` | GPS Platform, DocType (ref) | none |
| `Baro GPS Platform` | Company | none |

This matrix is what makes the split to `baro_integrations` safe later (`02` §4): the integration module writes into `Serial No` only through two derived fields, and everything else flows one way.

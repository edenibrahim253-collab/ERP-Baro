# 10 — Data Dictionary (source of truth)

Every field used anywhere in this package appears here exactly once. `20`, `21`, `30`, `31`, `40`, `41`, `50`, `51` and `60` reference these names verbatim; `80-verification-checklist.md` machine-checks that.

## 1. Flag legend

| Flag | Meaning |
|---|---|
| REQ | `reqd: 1` |
| ILV | `in_list_view: 1` |
| SF | `in_standard_filter: 1` |
| SIDX | `search_index: 1` |
| UQ | `unique: 1` — Frappe field-level UNIQUE index. Precedent in the shipped tree: `Employee.attendance_device_id`, `Item.item_code`, `Supplier.alias` |
| UQ-DRV | UNIQUE index on a Python-maintained key column that is **NULL when inactive** — the conditional-uniqueness mechanism enforcing "one active assignment per device/vehicle" (`31-uniqueness-concurrency-design.md` §3) |
| RO | `read_only: 1` for UI roles; writable only by the named mechanism |
| FF | `fetch_from: <source>` — never hand-typed |
| OS | `allow_on_submit: 1` |
| INT | writable only by the integration path (`BARO Integrator` role) |
| DRV | derived/maintained by a controller or `doc_events`; authority is stated in the row |
| WF | transitioned by Workflow only (`40-workflows-approvals.md`) |

`is_submittable`, `naming` and `track_changes` are declared once per DocType header, not per field.

---

## 2. Section A — standard DocTypes BARO relies on (no schema created here)

Fields listed are the ones this design reads or links to. All are read from the supplied tree and tagged `[verify-vs-v16]` (`04-version-compatibility-matrix.md` §4).

| DocType (module) | Fields relied upon | BARO use |
|---|---|---|
| `Customer` (selling) | `customer_name, customer_group, territory, default_price_list, tax_id, on_hold, is_frozen, account_manager, portal_users` | Account spine; `account_manager` is the standard owner field — **do not add a BARO duplicate** |
| `Item` (stock) | `item_code, item_name, item_group, stock_uom, has_serial_no, serial_no_series, warranty_period, barcodes, quality_inspection_template, safety_stock, reorder_levels, inspection_required_before_delivery, is_fixed_asset` | Device/SIM product definitions, reorder alerts, serial enablement |
| `Warehouse` (stock) | `warehouse_name, parent_warehouse, warehouse_type, is_rejected_warehouse, company, account` | Device storage + faulty-quarantine areas |
| `Serial No` (stock) | `serial_no(name), item_code, status, customer, warehouse, batch_no, location, employee, warranty_period, warranty_expiry_date, amc_expiry_date, maintenance_status, asset, purchase_rate, reference_doctype, reference_name` | **The device record.** Extended in Section B |
| `Serial and Batch Bundle` (stock) | `voucher_type, voucher_no, item_code, warehouse, qty, type_of_transaction, entries` | How serials move in modern ERPNext; BARO must not bypass it |
| `Stock Entry` (stock) | `purpose, from_warehouse, to_warehouse, items, scan_barcode, last_scanned_warehouse, project` | Device transfers, RMA inward/outward |
| `Delivery Note` (stock) | `customer, items, per_installed, installation_status, scan_barcode` | Links dispatch to installation progress |
| `Installation Note` (selling) | `naming_series, customer, customer_address, contact_person, territory, inst_date, inst_time, status, project, items, company` | **The installation record.** Extended in Section B |
| `Installation Note Item` (selling) | `item_code, serial_no, qty, serial_and_batch_bundle, prevdoc_doctype, prevdoc_docname` | Which unit went into the job |
| `Maintenance Visit` (maintenance) + `Maintenance Visit Purpose` | `customer, mntc_date, completion_status, maintenance_type, purposes; item_code, serial_no, work_details, service_person, work_done` | Service/maintenance history per unit |
| `Quality Inspection` (stock) | `naming_series, inspection_type, reference_type, reference_name, item_code, item_serial_no, quality_inspection_template, specification_details, readings, inspected_by, verified_by, status, manual_inspection` | **The inspection record.** Extended in Section B |
| `Warranty Claim` (support) | `serial_no, customer, complaint, issue_details, warranty_amc_status, warranty_expiry_date, resolution_details, service_address, status` | Fault claims; linked from RMA |
| `Issue` (support) | `subject, customer, status, priority, issue_type, service_level_agreement, response_by, first_responded_on, avg_response_time, resolution_time, on_hold_since, total_hold_time, project` | Helpdesk (later phase) — already has SLA timers |
| `Contract` + `Contract Template` (crm) | `party_type, party, start_date, end_date, status, contract_terms, requires_fulfilment, fulfilment_deadline` | Customer agreements; expiry automation |
| `Subscription` + `Subscription Plan` (accounts) | `status, subscription_period, plans, current_invoice_start, current_invoice_end, next_billing_period_start, next_billing_period_end, generate_invoice_at, days_until_due, cancel_at_period_end, party_type, party, cost_center, payment_gateway` | **Recurring billing.** Extended in Section B |
| `Sales Invoice` (accounts) | `customer, subscription, due_date, outstanding_amount, status` | Receivables, overdue automation |
| `Sales Order` (selling) | `customer, order_date, status, per_delivered` | Reservation source (`01` §2.1) |
| `Project` + `Task` (projects) | `project_name, customer, status, total_costing_amount, total_billed_amount; subject, issue_type, priority, depends_on_tasks, completed_by, exp_end_date` | Fleet rollouts; activation-verification tasks |
| `Appointment` + `Appointment Booking Settings` (crm) | `scheduled_time, calendar_event, appointment_with, party, status` | Dispatch/scheduling (later phase) |
| `Employee` (setup) | `employee_name, department, attendance_device_id` | Technician reference; proves field-level UQ on an external device id |
| `Company`, `Currency`, `UOM`, `Price List`, `Supplier` | standard | Multi-company, ETB, telco supplier as SIM cost counterparty |

## 3. Section B — Custom Fields added to standard DocTypes

15 Custom Fields, all prefixed `baro_`, all created as **Custom Field records (fixtures)** — never by editing ERPNext JSON.

| Target DocType | fieldname | label | type | options / link | flags | Authority / notes |
|---|---|---|---|---|---|---|
| `Serial No` | `baro_imei` | IMEI | Data | — | REQ*, ILV, SIDX, UQ | *required by server validation when the Item belongs to a GPS device Item Group, not by `reqd` (which would break non-GPS serials). Normalised to 15 digits, Luhn-checked in `validate` |
| `Serial No` | `baro_device_status` | BARO Device Status | Select | `In-Stock\nReserved\nAllocated\nInstalled\nActive\nFaulty\nRMA\nReturned\nDisposed` | ILV, SF, SIDX, DRV | **`Baro Device Assignment` / RMA controllers are the authority**; UI is read-only for all roles except `BARO Stock Manager` (In-Stock↔Reserved↔Allocated only). Deliberately separate from standard `status` (stock semantics) |
| `Serial No` | `baro_firmware_version` | Current Firmware | Data | — | RO, ILV | DRV: latest `Baro Firmware History.baro_firmware_version` for this serial |
| `Serial No` | `baro_last_comm_at` | Last Communication | Datetime | — | RO, SF, INT | DRV: **max** of `Baro Platform Mapping.baro_last_comm_at` across enabled platforms. Written only by the integration path; the "device inactive" scheduler reads it |
| `Installation Note` | `baro_vehicle` | Vehicle | Link | `Baro Vehicle` | ILV, SF | Set at installation; validated to match the assignment's vehicle |
| `Installation Note` | `baro_assignment` | Device Assignment | Link | `Baro Device Assignment` | ILV, SF | The submit of the assignment is what activates billing |
| `Installation Note` | `baro_technician` | Installer | Link | `Employee` | ILV, SF | Also drives performance reporting |
| `Installation Note` | `baro_activation_status` | Platform Activation | Select | `Not Verified\nVerified\nFailed` | SF, WF | Set by the activation-verification step, not by the installer |
| `Installation Note` | `baro_customer_signature` | Customer Sign-off | Signature | — | — | Satisfies the blueprint's customer sign-off requirement |
| `Installation Note` | `baro_quality_inspection` | Inspection | Link | `Quality Inspection` | SF | Set when quality approves; gates the activation transition |
| `Customer` | `baro_fleet_account` | Fleet Account | Check | — | ILV | Segmentation; drives portal/scheduling defaults later |
| `Customer` | `baro_platform_customer_ref` | Platform Account Ref | Data | — | SIDX | External platform's own customer/account id, for inbound event routing |
| `Subscription` | `baro_service_level` | Service Level | Select | `Trial\nBronze\nSilver\nGold` | ILV, SF | Maps to SLA and support policy later; kept on Subscription, not Contract |
| `Quality Inspection` | `baro_vehicle` | Vehicle | Link | `Baro Vehicle` | SF | Lets quality reporting slice by fleet |
| `Issue` | `baro_vehicle` | Vehicle | Link | `Baro Vehicle` | ILV, SF | Support tickets sliced by vehicle (later phase, defined now so the link exists) |

**Fifteen fields on six standard DocTypes — and deliberately no more.** Installation evidence photographs are **not** a field: they are Frappe `File` records attached to the `Installation Note` through the document's built-in attachment area, marked private, which is why `50` §11 and `90` §3 can talk about stored evidence without this table growing an `Attach` column per document type. A capture field exists only where a *value* must be validated or filtered — hence `baro_customer_signature` (`Signature`) but no `baro_photo_1..n`.

## 4. Section C — new BARO DocTypes

### 4.1 `Baro Vehicle` — module `baro_fleet`
`is_submittable: 0` · `autoname`: naming series `BARO-VEH-.####` · `track_changes: 1` · `search_fields: baro_plate_no, baro_vin, customer`

| fieldname | label | type | options / link | flags |
|---|---|---|---|---|
| `naming_series` | Series | Select | `BARO-VEH-.####` | REQ |
| `baro_plate_no` | Plate Number | Data | — | REQ, ILV, SF, SIDX, UQ |
| `baro_vin` | VIN / Chassis | Data | — | SIDX, UQ (NULL-allowed when absent) |
| `baro_chassis_no` | Chassis No | Data | — | — |
| `customer` | Customer | Link | `Customer` | REQ, ILV, SF |
| `baro_customer_name` | Customer Name | Data | — | RO, ILV, FF `customer.customer_name` |
| `baro_vehicle_type` | Vehicle Type | Select | `Car\nPickup\nTruck\nBus\nTrailer\nMotorcycle\nHeavy Equipment\nOther` | REQ, ILV, SF |
| `baro_make` / `baro_model` | Make / Model | Data | — | ILV / — |
| `baro_year` | Year | Int | — | — |
| `baro_status` | Fleet Status | Select | `Registered\nIn-Service\nTransferred\nRetired` | REQ, SF, DRV |
| `baro_current_assignment` | Current Assignment | Link | `Baro Device Assignment` | RO, DRV |
| `baro_current_device` | Current Device | Link | `Serial No` | RO, ILV, DRV (FF from current assignment's `serial_no`) |
| `baro_asset` | Fixed Asset | Link | `Asset` | — (only when capitalised) |
| `baro_registration_expiry` | Registration Expiry | Date | — | SF |
| `baro_speed_limiter_cert_no` | Speed Limiter Certificate | Data | — | — |
| `baro_cert_expiry` | Certificate Expiry | Date | — | SF (compliance automation input) |
| `baro_insurer` / `baro_policy_number` | Insurer / Policy | Data | — | — |
| `baro_insurance_expiry` | Insurance Expiry | Date | — | SF |
| `baro_fleet_group` | Fleet Group | Data | autocompleted from existing values in release 1 | SF — promotes to a master only if reporting needs it (Q6) |
| `baro_notes` | Notes | Small Text | — | — |
| `image` | Image | Attach Image | — | — |
| `company` | Company | Link | `Company` | REQ, default from session |

### 4.2 `Baro Device Assignment` — module `baro_field_service`
`is_submittable: 1` · naming series `BARO-ASSIGN-.####` · `track_changes: 1` · Workflow-gated (`40` §4)

| fieldname | label | type | options / link | flags |
|---|---|---|---|---|
| `naming_series` | Series | Select | `BARO-ASSIGN-.####` | REQ |
| `customer` | Customer | Link | `Customer` | REQ, ILV, SF |
| `baro_vehicle` | Vehicle | Link | `Baro Vehicle` | REQ, ILV, SF |
| `serial_no` | GPS Device | Link | `Serial No` | REQ, ILV, SF |
| `baro_device_item` | Device Model | Data | — | RO, ILV, FF `serial_no.item_code` |
| `baro_imei` | IMEI | Data | — | RO, ILV, FF `serial_no.baro_imei` |
| `baro_sim_card` | SIM Card | Link | `Baro SIM Card` | ILV, SF |
| `baro_assignment_type` | Assignment Type | Select | `Installation\nReplacement\nTransfer\nTrial\nTemporary Loan` | REQ, SF |
| `baro_status` | Assignment Status | Select | `Draft\nPending Approval\nActive\nEnded\nSuperseded` | REQ, ILV, SF, WF |
| `from_time` | Active From | Datetime | — | REQ, ILV, SF |
| `to_time` | Active To | Datetime | — | SF, OS (ending an assignment is an on-submit edit and re-runs the overlap check) |
| `baro_active_serial_key` | Active Device Key | Data | — | RO, hidden, **UQ-DRV** = `serial_no` while status Active, else NULL |
| `baro_active_vehicle_key` | Active Vehicle Key | Data | — | RO, hidden, **UQ-DRV** = `baro_vehicle` while status Active, else NULL |
| `baro_previous_assignment` | Supersedes | Link | `Baro Device Assignment` | — (replacement/transfer chain) |
| `baro_replaced_by` | Superseded By | Link | `Baro Device Assignment` | RO, DRV |
| `baro_installation_note` | Installation Note | Link | `Installation Note` | SF |
| `baro_technician` | Technician | Link | `Employee` | ILV, SF |
| `baro_appointment` | Appointment | Link | `Appointment` | SF (nullable in release 1) |
| `baro_activation_status` | Platform Activation | Select | `Not Verified\nVerified\nFailed` | SF, WF |
| `baro_project` | Rollout Project | Link | `Project` | SF |
| `baro_remarks` | Remarks | Small Text | — | — |
| `company` | Company | Link | `Company` | REQ |
| `amended_from` | Amended From | Link | `Baro Device Assignment` | RO |

### 4.3 `Baro SIM Card` — module `baro_connectivity`
`is_submittable: 1` · naming series `BARO-SIM-.####` · `track_changes: 1`

| fieldname | label | type | options / link | flags |
|---|---|---|---|---|
| `naming_series` | Series | Select | `BARO-SIM-.####` | REQ |
| `baro_iccid` | ICCID | Data | — | REQ, ILV, SF, SIDX, UQ |
| `baro_msisdn` | MSISDN (number) | Data | — | REQ, ILV, SF, SIDX, UQ |
| `supplier` | Connectivity Provider | Link | `Supplier` | REQ, ILV, SF |
| `baro_sim_status` | SIM Status | Select | `Provisioned\nActivated\nSuspended\nDeactivated\nExpired` | REQ, ILV, SF, WF |
| `baro_installed_device` | Installed In Device | Link | `Serial No` | RO, DRV (written by the assignment's `on_submit`; the assignment is the authority) |
| `baro_installed_vehicle` | Installed In Vehicle | Link | `Baro Vehicle` | RO, DRV |
| `baro_data_plan` | Data Plan | Data | — | ILV |
| `baro_plan_price` | Monthly Cost | Currency | — | — |
| `baro_billing_cycle` | Billing Cycle | Select | `Monthly\nAnnual\nPrepaid Top-up\nPostpaid` | SF |
| `baro_activation_date` | Activation Date | Date | — | SF |
| `baro_expiry_date` | Plan / SIM Expiry | Date | — | REQ, SF — drives the connectivity-expiry notification (`60` T7) |
| `baro_deactivation_date` | Deactivation Date | Date | — | — |
| `baro_apn` | APN | Data | — | — |
| `baro_replaces` / `baro_replaced_by` | Replacement chain | Link `Baro SIM Card` | — | — |
| `baro_pin` / `baro_puk` | PIN / PUK | **Password** | — | never exported as fixture, never logged |
| `baro_notes` | Notes | Small Text | — | — |
| `company` | Company | Link | `Company` | REQ |
| `amended_from` | Amended From | Link | `Baro SIM Card` | RO |

### 4.4 `Baro Platform Mapping` — module `baro_integrations`
`is_submittable: 0` · **`autoname: format:{baro_platform}-{platform_device_id}`** — this is how composite uniqueness (one external id per platform) is enforced with Frappe's PK, no DDL required · `track_changes: 1`

| fieldname | label | type | options / link | flags |
|---|---|---|---|---|
| `baro_platform` | GPS Platform | Link | `Baro GPS Platform` | REQ, ILV, SF |
| `serial_no` | Device | Link | `Serial No` | REQ, ILV, SF |
| `platform_device_id` | Platform Device ID | Data | — | REQ, ILV, SIDX |
| `baro_vehicle` | Vehicle | Link | `Baro Vehicle` | SF (denormalised for fast reconciliation) |
| `baro_customer_name` | Customer | Data | — | RO, ILV, FF `serial_no.customer` → resolved name |
| `baro_platform_status` | Platform Status | Select | `Unknown\nOnline\nOffline\nMoved\nStolen\nMaintenance` | SF, INT |
| `baro_last_comm_at` | Last Communication | Datetime | — | SF, RO, INT — per platform; `Serial No.baro_last_comm_at` is the max of these |
| `baro_sync_status` | Sync Status | Select | `Synced\nPending\nFailed` | SF, DRV |
| `baro_last_sync_at` | Last Sync | Datetime | — | RO, INT |
| `baro_enabled` | Enabled | Check | default 1 | SF |
| `company` | Company | Link | `Company` | REQ |

### 4.5 `Baro Firmware History` — module `baro_devices`
`is_submittable: 0` · naming series `BARO-FW-.####` · append-only by permission (no delete, edit restricted to `BARO Stock Manager`)

| fieldname | label | type | options / link | flags |
|---|---|---|---|---|
| `naming_series` | Series | Select | `BARO-FW-.####` | REQ |
| `serial_no` | Device | Link | `Serial No` | REQ, ILV, SF |
| `item_code` | Device Model | Data | — | RO, ILV, FF `serial_no.item_code` |
| `baro_firmware_version` | Firmware Version | Data | — | REQ, ILV |
| `baro_previous_version` | Previous Version | Data | — | — |
| `baro_update_date` | Update Date | Date | default Today | REQ, ILV, SF |
| `baro_updated_by` | Updated By | Link | `Employee` | — |
| `baro_update_source` | Source | Select | `Manual\nPlatform Sync\nRMA\nDealer\nBatch Import` | REQ, SF |
| `baro_release_notes` | Notes | Small Text | — | — |
| `company` | Company | Link | `Company` | REQ |

### 4.6 `Baro Device RMA` — module `baro_devices`
`is_submittable: 1` · naming series `BARO-RMA-.####` · `track_changes: 1` · Workflow-gated

| fieldname | label | type | options / link | flags |
|---|---|---|---|---|
| `naming_series` | Series | Select | `BARO-RMA-.####` | REQ |
| `serial_no` | Device | Link | `Serial No` | REQ, ILV, SF |
| `customer` | Customer | Link | `Customer` | REQ, ILV, SF (validated equal to `serial_no.customer`) |
| `baro_rma_type` | RMA Type | Select | `In-warranty\nOut-of-warranty\nGoodwill` | REQ, SF |
| `baro_rma_reason` | Reason | Select | `Hardware Fault\nNot Charging\nNo Network\nGNSS Drift\nSpeed Limiter Fault\nDamaged\nWrong Model\nCustomer Return\nEnd of Life` | REQ, ILV, SF |
| `baro_fault_description` | Fault Details | Text | — | — |
| `baro_warranty_claim` | Warranty Claim | Link | `Warranty Claim` | SF |
| `baro_rma_status` | RMA Status | Select | `Open\nAwaiting Return\nReceived\nInspected\nReplaced\nRefunded\nScrapped\nClosed` | REQ, ILV, SF, WF |
| `baro_disposition` | Disposition | Select | `Replace\nRepair\nScrap\nRefund\nRestock` | SF |
| `baro_replacement_serial` | Replacement Device | Link | `Serial No` | SF |
| `baro_old_assignment` | Ended Assignment | Link | `Baro Device Assignment` | RO, DRV |
| `baro_new_assignment` | New Assignment | Link | `Baro Device Assignment` | RO, DRV |
| `baro_received_date` | Received | Date | — | — |
| `baro_dispatched_date` | Dispatched | Date | — | SF |
| `baro_supplier_rma_no` | Supplier RMA No | Data | — | SIDX |
| `baro_tracking_id` | Carrier Tracking ID | Data | — | SIDX (`Shipment` reuse is later-phase) |
| `baro_inspection` | Inspection | Link | `Quality Inspection` | SF |
| `baro_purchase_invoice` | Supplier Credit | Link | `Purchase Invoice` | SF (financial effect requires Finance) |
| `baro_notes` | Notes | Small Text | — | — |
| `company` | Company | Link | `Company` | REQ |
| `amended_from` | Amended From | Link | `Baro Device RMA` | RO |

### 4.7 `Baro Integration Log` — module `baro_integrations`
`is_submittable: 0` · naming series `BARO-INTLOG-.####` · append-only · retention rule in `50` §7

| fieldname | label | type | options / link | flags |
|---|---|---|---|---|
| `naming_series` | Series | Select | `BARO-INTLOG-.####` | REQ |
| `baro_direction` | Direction | Select | `Inbound\nOutbound` | REQ, SF |
| `baro_platform` | Platform | Link | `Baro GPS Platform` | REQ, SF |
| `baro_endpoint` | Endpoint | Data | — | REQ |
| `baro_idempotency_key` | Idempotency Key | Data | — | REQ, SF, **UQ** (replay guard, `50` §4) |
| `baro_correlation_id` | Correlation ID | Data | — | SF |
| `ref_doctype` | Reference DocType | Link | `DocType` | SF |
| `ref_name` | Reference | Dynamic Link | `ref_doctype` | SF |
| `baro_log_status` | Status | Select | `Received\nProcessed\nFailed\nRetrying\nDead` | REQ, ILV, SF |
| `baro_attempt_count` | Attempts | Int | default 0 | — |
| `baro_max_attempts` | Max Attempts | Int | default 5 | — |
| `baro_next_retry_at` | Next Retry | Datetime | — | SF (retry-poller index) |
| `baro_http_status` | HTTP Status | Int | — | — |
| `baro_error_class` | Error Class | Select | `None\nTimeout\nAuth\nRateLimit\nPayload\nServer\nUnknown` | SF |
| `baro_error_message` | Error | Text | — | — |
| `baro_payload_ref` | Payload | Link | `File` | — (never an inline blob) |
| `baro_result_ref` | Result Record | Dynamic Link | `ref_doctype` | — (what the event created/updated) |
| `baro_processed_at` | Processed At | Datetime | — | — |
| `company` | Company | Link | `Company` | REQ |

### 4.8 `Baro GPS Platform` — module `baro_settings`
`is_submittable: 0` · **`autoname: field:baro_platform_name`** · one row per tracking platform

| fieldname | label | type | options / link | flags |
|---|---|---|---|---|
| `baro_platform_name` | Platform Name | Data | — | REQ, ILV (becomes `name`, so PK-unique) |
| `baro_base_url` | API Base URL | Data | — | REQ |
| `baro_adapter_module` | Connector Module | Data | dotted path, e.g. `baro_core.integrations.vendor_x` | REQ — the adapter is resolved from this string at runtime (`50` §3), so a platform is enabled or retired by configuration, not a code edit |
| `baro_auth_type` | Auth Type | Select | `API Key\nBearer Token\nBasic\nOAuth2\nHMAC Signature` | REQ, ILV |
| `baro_api_key` | API Key | **Password** | — | never a fixture, never in logs |
| `baro_api_secret` | API Secret | **Password** | — | — |
| `baro_webhook_secret` | Webhook Signing Secret | **Password** | — | inbound HMAC verification (`50` §5) |
| `baro_rate_limit_per_min` | Rate Limit / min | Int | default 60 | REQ (`50` §6) |
| `baro_timeout_secs` | Timeout (s) | Int | default 15 | REQ |
| `baro_max_retries` | Max Retries | Int | default 5 | REQ |
| `baro_pull_interval` | Poll Interval | Select | `Off\nEvery 15 min\nHourly\nEvery 6 hours\nDaily` | REQ, SF |
| `baro_enabled` | Enabled | Check | default 1 | REQ, SF |
| `baro_last_success_at` | Last Success | Datetime | — | RO, INT |
| `baro_last_failure_at` | Last Failure | Datetime | — | RO, INT, SF |
| `baro_last_error` | Last Error | Small Text | — | RO, INT |
| `baro_notes` | Notes | Small Text | — | — |
| `company` | Company | Link | `Company` | REQ |

### 4.9 `Baro Operations Settings` — module `baro_settings` (**Single**)
`is_submittable: 0` · `issingle: 1` · org-wide tuning knobs, so no rule in `21`/`31`/`60` hard-codes a number or a pattern

| fieldname | label | type | options / link | flags |
|---|---|---|---|---|
| `baro_plate_pattern` | Plate Regex | Data | python/JS-compatible pattern | REQ |
| `baro_msisdn_pattern` | MSISDN Regex | Data | — | REQ |
| `baro_device_item_groups` | GPS Device Item Groups | Table MultiSelect | child → `Item Group` | REQ — defines "is this serial a device?" and "must IMEI be filled?" |
| `baro_assignment_future_days` | Max Days Assignable Ahead | Int | default 0 | REQ |
| `baro_activation_sla_days` | Activation Verification SLA (days) | Int | default 2 | REQ — `Task.exp_end_date` offset (`21` §2) |
| `baro_warranty_override_allowed` | Allow Warranty Override | Check | — | paired with `BARO Approver` |
| `baro_expiry_notice_days` | Contract / Plan Expiry Notice (days) | Int | default 30 | REQ (`60` T3, T7) |
| `baro_cert_notice_days` | Certificate Expiry Notice (days) | Int | default 30 | REQ (`60` T8) |
| `baro_inactive_threshold_hours` | Device Inactive Threshold (hours) | Int | default 24 | REQ (`60` T6 reads `Serial No.baro_last_comm_at`) |
| `baro_reorder_notice_role` | Reorder Notice Role | Select | `BARO Stock Manager\nBARO Procurement Officer` | REQ (`60` T9) |
| `baro_log_retention_days` | Integration Log Retention (days) | Int | default 90 | REQ (`50` §7) |
| `baro_normalise_identifiers` | Normalise Plate/IMEI Case | Check | default 1 | REQ |
| `baro_reconciliation_cron` | Reconciliation Frequency | Select | `Hourly\nDaily\nWeekly` | REQ, default Daily |
| `baro_max_rows_per_run` | Reconciliation Row Cap | Int | default 20000 | REQ (`51` §2 bound; exceeding it marks the run `truncated`) |
| `baro_count_alert_threshold` | Count-Delta Escalation Threshold | Int | default 5 | REQ (`51` §4.4 — at or above it, a `Count mismatch` is owned by `BARO Approver`) |

Table MultiSelect generates one small child DocType automatically (`Baro Device Item Group Reference`); it is the only child DocType in release 1.

### 4.10 `Baro Reconciliation Exception` — module `baro_integrations`
`is_submittable: 0` · `track_changes: 1` · naming series `BARO-RECON-.####` · one row per mismatch bucket per run; the human inbox behind the three-way diff (`51-reconciliation-exception-design.md`)

Deliberately **not** a `Issue` (support ticket): system-generated noise would flood the support queue, break SLA reporting, and give customers visibility of internal data-quality problems. It is a work item for named BARO roles, resolved inside this DocType.

| fieldname | label | type | options / link | flags |
|---|---|---|---|---|
| `naming_series` | Series | Select | `BARO-RECON-.####` | REQ |
| `baro_run_id` | Run ID | Data | — | REQ, ILV, SF, SIDX (groups every row written by one reconciliation run; `51` §3) |
| `baro_exception_type` | Exception Type | Select | `ERP-only\nPlatform-only\nState mismatch\nCount mismatch\nBilling mismatch\nMapping missing\nDuplicate active device` | REQ, ILV, SF |
| `baro_platform` | Platform | Link | `Baro GPS Platform` | SF (null for billing-only exceptions) |
| `ref_doctype` | Reference DocType | Link | `DocType` | SF |
| `ref_name` | Reference | Dynamic Link | `ref_doctype` | SF |
| `serial_no` | Device (Serial No) | Link | `Serial No` | SF, SIDX |
| `baro_vehicle` | Vehicle | Link | `Baro Vehicle` | SF, SIDX |
| `customer` | Customer | Link | `Customer` | FF (`baro_vehicle.customer`, else `serial_no.customer`), ILV, SF |
| `baro_detected_at` | Detected At | Datetime | — | REQ, DRV (set by the run) |
| `baro_match_key` | Match Key | Data | — | DRV, SF (normalised identifier **+ check id**; suppresses repeats across runs and drives auto-clear, `51` §6) |
| `baro_details` | Details | Text | — | RO, DRV (what the diff compared, both sides' values) |
| `baro_status` | Status | Select | `Open\nAcknowledged\nIn Progress\nResolved\nWaived` | REQ, ILV, SF, DRV — role-checked writes; **`Waived` is the only Workflow-gated transition** (`40` §5, `51` §7) |
| `baro_assigned_role` | Assigned Role | Select | `BARO Integrator\nBARO Stock Manager\nBARO Service Supervisor\nBARO Connectivity Admin\nBARO Accounts User\nBARO Approver` | REQ, ILV, SF (drives the inbox filter; never a named person, so re-staffing does not orphan rows) |
| `baro_impact_billable` | Revenue At Risk | Check | — | DRV, ILV, SF (`51` §5 — only billing-affecting buckets set it) |
| `baro_waive_reason` | Waive Reason | Small Text | — | conditional REQ: mandatory when `baro_status = Waived` |
| `baro_resolution_notes` | Resolution | Small Text | — | conditional REQ when `Resolved` |
| `baro_resolved_at` | Resolved At | Datetime | — | RO, DRV |
| `baro_cleared_automatically` | Auto-Cleared | Check | — | RO, DRV (`51` §6: set when a later run no longer sees the mismatch) |
| `company` | Company | Link | `Company` | REQ |

Two rules that make this DocType safe:
- **Read-only to the integration path.** `BARO Integrator` may create and update these rows but may never change `baro_status` to `Resolved`/`Waived`, and may never touch `serial_no`, `baro_vehicle`, `ref_name` or any billing document (`41-role-permission-matrix.md` §3).
- **No cascading side effects.** Creating, resolving or waiving an exception writes no other DocType. Any corrective action is a separate, approved human edit through the normal workflow (`40-workflows-approvals.md` §1, "detection is not action").

## 5. Deferred schema (not created in release 1)

| Item | Trigger to build it |
|---|---|
| `Baro Subscription Asset` | Stakeholder Q4 confirms one subscription covers many devices (1:M). Otherwise a Custom Field on `Subscription` |
| `Baro Fleet Group` master | Fleet-group reporting or per-group pricing needs referential integrity |
| Speed-limiter certificate / compliance DocTypes | Compliance workspace (later phase); release 1 keeps the certificate fields on `Baro Vehicle` |
| `Baro Integration Batch` | If reconciliation history needs a first-class parent above the flat `Baro Reconciliation Exception.baro_run_id` / `Baro Integration Log.baro_correlation_id` keys (`51` §12) |

## 6. Enumerations (single definition each; `40` and `80` check closure)

| Enum | Values |
|---|---|
| Device status | `In-Stock, Reserved, Allocated, Installed, Active, Faulty, RMA, Returned, Disposed` |
| Vehicle status | `Registered, In-Service, Transferred, Retired` |
| Assignment status | `Draft, Pending Approval, Active, Ended, Superseded` |
| SIM status | `Provisioned, Activated, Suspended, Deactivated, Expired` |
| RMA status | `Open, Awaiting Return, Received, Inspected, Replaced, Refunded, Scrapped, Closed` |
| Activation status | `Not Verified, Verified, Failed` |
| Platform status | `Unknown, Online, Offline, Moved, Stolen, Maintenance` |
| Integration log status | `Received, Processed, Failed, Retrying, Dead` |
| Error class | `None, Timeout, Auth, RateLimit, Payload, Server, Unknown` |
| Exception type | `ERP-only, Platform-only, State mismatch, Count mismatch, Billing mismatch, Mapping missing, Duplicate active device` |
| Exception status | `Open, Acknowledged, In Progress, Resolved, Waived` |
| Assignment type | `Installation, Replacement, Transfer, Trial, Temporary Loan` |

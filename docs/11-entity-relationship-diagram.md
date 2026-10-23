# 11 — Entity Relationship Diagrams

**How to view:** each block below is Mermaid `erDiagram`. It renders in GitHub, VS Code (Markdown preview with Mermaid), Obsidian and Qoder's markdown preview with no installation — chosen deliberately because this machine has no Java/Python runtime for PlantUML. Entity names use `SNAKE_UPPER`; the real Frappe DocType name is in the label mapping (§5).

Relations tagged **[R1]** are release-1 (asset spine). **[later]** marks entities that exist in ERPNext but are not built out yet — they appear here so the spine does not paint itself into a corner.

## 1. The asset spine

```mermaid
erDiagram
  CUSTOMER ||--o{ BARO_VEHICLE : "registers [R1]"
  CUSTOMER ||--o{ SERIAL_NO : "owns after delivery [R1]"
  ITEM ||--o{ SERIAL_NO : "serialises units [R1]"
  WAREHOUSE ||--o{ SERIAL_NO : "stores [R1]"
  BARO_VEHICLE ||--o{ BARO_DEVICE_ASSIGNMENT : "assignment history [R1]"
  SERIAL_NO ||--o{ BARO_DEVICE_ASSIGNMENT : "fitted into [R1]"
  BARO_SIM_CARD |o--o{ BARO_DEVICE_ASSIGNMENT : "paired during [R1]"
  SERIAL_NO |o--o{ BARO_SIM_CARD : "current SIM (derived) [R1]"
  EMPLOYEE ||--o{ BARO_DEVICE_ASSIGNMENT : "installed by [R1]"
  INSTALLATION_NOTE ||--o| BARO_DEVICE_ASSIGNMENT : "raises [R1]"
  BARO_DEVICE_ASSIGNMENT ||--o{ INSTALLATION_NOTE : "evidenced by [R1]"
  BARO_DEVICE_ASSIGNMENT |o--|| QUALITY_INSPECTION : "inspected by [R1]"
  SERIAL_NO ||--o{ BARO_FIRMWARE_HISTORY : "version log [R1]"
  SERIAL_NO ||--o{ BARO_DEVICE_RMA : "returned under [R1]"
  BARO_DEVICE_RMA |o--|| WARRANTY_CLAIM : "raised from [R1]"
  WARRANTY_CLAIM }o--|| SERIAL_NO : "claims on [R1]"
  BARO_DEVICE_RMA |o--|| BARO_DEVICE_ASSIGNMENT : "ends (old) [R1]"
  BARO_DEVICE_RMA |o--|| BARO_DEVICE_ASSIGNMENT : "starts (new) [R1]"
  PROJECT ||--o{ BARO_DEVICE_ASSIGNMENT : "rollout [R1]"

  CUSTOMER {
    string name "PK = customer_name"
    string customer_group
    string territory
    string account_manager "standard owner field"
    bool   baro_fleet_account "custom field"
  }
  ITEM {
    string item_code "PK"
    bool   has_serial_no
    string serial_no_series
    int    warranty_period
    string quality_inspection_template
  }
  SERIAL_NO {
    string serial_no "PK = the unit's serial"
    string item_code
    string status "stock semantics only"
    string customer
    string warehouse
    string warranty_expiry_date
    string baro_imei "custom, UNIQUE + search_index"
    string baro_device_status "custom, 9-state"
    string baro_last_comm_at "custom, integration-write only"
  }
  BARO_VEHICLE {
    string name "BARO-VEH-.####"
    string baro_plate_no "UNIQUE, search_index"
    string baro_vin "UNIQUE where present"
    string customer
    string baro_status
    string baro_current_assignment "derived"
    string baro_cert_expiry
  }
  BARO_DEVICE_ASSIGNMENT {
    string name "BARO-ASSIGN-.####"
    string baro_vehicle
    string serial_no
    string baro_sim_card
    string baro_status "Draft..Superseded, workflow"
    datetime from_time
    datetime to_time
    string baro_active_serial_key "UQ while Active"
    string baro_active_vehicle_key "UQ while Active"
    string baro_activation_status
  }
  BARO_SIM_CARD {
    string name "BARO-SIM-.####"
    string baro_iccid "UNIQUE, search_index"
    string baro_msisdn "UNIQUE, search_index"
    string supplier
    string baro_sim_status
    string baro_installed_device "derived from assignment"
    date   baro_expiry_date
  }
  INSTALLATION_NOTE {
    string name "standard series"
    string customer
    datetime inst_date
    string status
    string baro_vehicle "custom"
    string baro_assignment "custom"
    string baro_customer_signature "custom (Signature)"
  }
  EMPLOYEE {
    string name "PK employee id"
    string employee_name
    string department
  }
  QUALITY_INSPECTION {
    string name "QC series"
    string reference_type
    string reference_name
    string item_serial_no
    string status
  }
  BARO_FIRMWARE_HISTORY {
    string name "BARO-FW-.####"
    string serial_no
    string baro_firmware_version
    date   baro_update_date
  }
  BARO_DEVICE_RMA {
    string name "BARO-RMA-.####"
    string serial_no
    string baro_rma_status
    string baro_disposition
    string baro_replacement_serial
  }
  WARRANTY_CLAIM {
    string name "support series"
    string serial_no
    string status
  }
  PROJECT {
    string name "project id"
    string customer
  }
  WAREHOUSE {
    string name "PK warehouse_name"
    string warehouse_type
    bool   is_rejected_warehouse
  }
```

## 2. Integration boundary

```mermaid
erDiagram
  BARO_GPS_PLATFORM ||--o{ BARO_PLATFORM_MAPPING : "names devices in [R1]"
  BARO_GPS_PLATFORM ||--o{ BARO_INTEGRATION_LOG : "exchanges [R1]"
  SERIAL_NO ||--o{ BARO_PLATFORM_MAPPING : "mapped as [R1]"
  BARO_VEHICLE ||--o{ BARO_PLATFORM_MAPPING : "reconciled by [R1]"
  BARO_PLATFORM_MAPPING |o--o{ BARO_INTEGRATION_LOG : "resolved to (Dynamic Link) [R1]"
  BARO_INTEGRATION_LOG }o--|| FILE : "payload stored as [R1]"
  GPS_PLATFORM_EXTERNAL ||--o{ BARO_PLATFORM_MAPPING : "pushes / polled [R1]"
  BARO_GPS_PLATFORM ||--o{ BARO_RECON_EXCEPTION : "diffed against [R1]"
  BARO_PLATFORM_MAPPING |o--o{ BARO_RECON_EXCEPTION : "compared as [R1]"
  BARO_INTEGRATION_LOG |o--o{ BARO_RECON_EXCEPTION : "shares run/correlation keys [R1]"
  BARO_DEVICE_ASSIGNMENT |o--o{ BARO_RECON_EXCEPTION : "state checked by [R1]"
  BARO_RECON_EXCEPTION }o--o| BARO_VEHICLE : "reports on (nullable) [R1]"
  BARO_RECON_EXCEPTION }o--o| SERIAL_NO : "reports on (nullable) [R1]"

  BARO_GPS_PLATFORM {
    string name "PK = baro_platform_name"
    string baro_base_url
    string baro_auth_type
    int    baro_rate_limit_per_min
    string baro_pull_interval
    bool   baro_enabled
  }
  BARO_PLATFORM_MAPPING {
    string name "format: platform-deviceId (composite unique via PK)"
    string baro_platform
    string serial_no
    string platform_device_id "search_index"
    string baro_platform_status
    datetime baro_last_comm_at "integration-write only"
    string baro_sync_status
  }
  BARO_INTEGRATION_LOG {
    string name "BARO-INTLOG-.####"
    string baro_direction
    string baro_idempotency_key "UNIQUE - replay guard"
    string baro_log_status "Received..Dead"
    int    baro_attempt_count
    datetime baro_next_retry_at
    string ref_doctype
    string ref_name
  }
  BARO_RECON_EXCEPTION {
    string name "BARO-RECON-.####"
    string baro_run_id "one diff run"
    string baro_exception_type "ERP-only..Duplicate active device"
    string baro_match_key "suppresses same-run duplicates"
    string baro_status "Open..Waived"
    string baro_assigned_role "inbox filter"
    bool   baro_impact_billable
    string ref_doctype
    string ref_name
  }
  FILE {
    string name "Frappe File = payload at rest"
  }  GPS_PLATFORM_EXTERNAL {
    string note "opaque: telemetry and track points stay here"
  }
```

## 3. Billing boundary (reuse only — no new schema in release 1)

```mermaid
erDiagram
  CUSTOMER ||--o{ CONTRACT : "signs [later]"
  CUSTOMER ||--o{ SUBSCRIPTION : "bills [later]"
  SUBSCRIPTION ||--|{ SUBSCRIPTION_PLAN_CHILD : "plan lines [later]"
  SUBSCRIPTION ||--o{ SALES_INVOICE : "generates recurring [later]"
  SALES_INVOICE ||--o{ PAYMENT_ENTRY : "settles [later]"
  SUBSCRIPTION |o--o{ BARO_SUBSCRIPTION_ASSET : "covers units (DEFERRED, see Q4)"
  BARO_SUBSCRIPTION_ASSET }o--|| SERIAL_NO : "device"
  BARO_SUBSCRIPTION_ASSET }o--|| BARO_VEHICLE : "vehicle"
  BARO_DEVICE_ASSIGNMENT ||--o{ BARO_SUBSCRIPTION_ASSET : "billable unit (deferred)"

  SUBSCRIPTION {
    string name "standard series"
    string party_type
    string party
    string status
    date   current_invoice_start
    date   current_invoice_end
    datetime generate_invoice_at
    string baro_service_level "custom"
  }
  CONTRACT {
    string name "standard series"
    string party
    date   start_date
    date   end_date
    string status
  }
  SUBSCRIPTION_PLAN_CHILD {
    string subscription_plan "child table 'plans'"
  }
  BARO_SUBSCRIPTION_ASSET {
    string note "not built unless 1 subscription covers many devices"
  }
```

## 4. Cardinality and authority rules

These are the constraints a reviewer should actually check; enforcement mechanisms live in `31-uniqueness-concurrency-design.md`.

| # | Rule | Cardinality | Authority (who may write) | Mechanism |
|---|---|---|---|---|
| R-01 | A Customer owns many Vehicles | 1:M | Sales/Fleet | `Baro Vehicle.customer` REQ Link |
| R-02 | A Vehicle may have **at most one Active** assignment | 1:0..1 active | Field Service via submit | `baro_active_vehicle_key` **UQ-DRV** |
| R-03 | A Device (Serial No) may have **at most one Active** assignment | 1:0..1 active | Field Service via submit | `baro_active_serial_key` **UQ-DRV** |
| R-04 | Assignments never overwrite history; they end or are superseded | append | Field Service + Approver | submittable + Workflow + `to_time` OS |
| R-05 | No two Active assignments may overlap in time on the same device | — | `before_submit` | Datetime-range query + Redis lock + `SELECT … FOR UPDATE` |
| R-06 | IMEI is unique across all devices | 1:1 | Stock Manager | `Serial No.baro_imei` **UQ** |
| R-07 | ICCID and MSISDN are each unique per SIM | 1:1 | Connectivity Admin | `baro_iccid` / `baro_msisdn` **UQ** |
| R-08 | A plate number identifies exactly one vehicle record | 1:1 | Fleet | `baro_plate_no` **UQ** |
| R-09 | A device's current SIM is derived, never typed | derived | Assignment `on_submit` | `Baro SIM Card.baro_installed_device` RO/DRV |
| R-10 | One platform device id maps to one serial per platform | 1:1 per platform | Integration | `autoname: format:{baro_platform}-{platform_device_id}` |
| R-11 | One integration event is processed once | 1:1 | Integration | `baro_idempotency_key` **UQ** |
| R-12 | Firmware history is append-only | 1:M | Integration + Stock Manager | no-delete permission, RO fields |
| R-13 | An RMA that replaces a device ends the old assignment and starts a new one | 1:1 pairs | Service Supervisor | `baro_old_assignment` / `baro_new_assignment` DRV |
| R-14 | Installation evidence attaches to the standard note, not a BARO copy | M:1 | Installer | `Installation Note` custom fields |
| R-15 | Every assignment belongs to exactly one Customer, consistent with its Vehicle | — | Validation | cross-check in `validate` |
| R-16 | A reconciliation exception references at least one of serial / vehicle / mapping, and never writes to them | M:0..1 | Job creates; named roles close | `validate` requires one reference + no `doc_events` on this DocType (`51` §7) |

## 5. Label mapping (Mermaid entity → Frappe DocType)

| Diagram entity | DocType | Module | New? |
|---|---|---|---|
| `CUSTOMER` | Customer | selling (ERPNext) | standard |
| `ITEM`, `WAREHOUSE`, `SERIAL_NO`, `QUALITY_INSPECTION` | Item, Warehouse, Serial No, Quality Inspection | stock (ERPNext) | standard + custom fields |
| `INSTALLATION_NOTE` | Installation Note (+ Installation Note Item) | selling (ERPNext) | standard + custom fields |
| `WARRANTY_CLAIM` | Warranty Claim | support (ERPNext) | standard |
| `SUBSCRIPTION`, `SALES_INVOICE`, `PAYMENT_ENTRY`, `SUBSCRIPTION_PLAN_CHILD` | Subscription, Sales Invoice, Payment Entry, Subscription Plan child | accounts (ERPNext) | standard |
| `CONTRACT` | Contract | crm (ERPNext) | standard |
| `PROJECT`, `TASK` | Project, Task | projects (ERPNext) | standard |
| `EMPLOYEE` | Employee | setup (ERPNext) / hrms | standard (partial) |
| `BARO_VEHICLE` | **Baro Vehicle** | baro_fleet | new |
| `BARO_DEVICE_ASSIGNMENT` | **Baro Device Assignment** | baro_field_service | new |
| `BARO_SIM_CARD` | **Baro SIM Card** | baro_connectivity | new |
| `BARO_FIRMWARE_HISTORY` | **Baro Firmware History** | baro_devices | new |
| `BARO_DEVICE_RMA` | **Baro Device RMA** | baro_devices | new |
| `BARO_PLATFORM_MAPPING` | **Baro Platform Mapping** | baro_integrations | new |
| `BARO_INTEGRATION_LOG` | **Baro Integration Log** | baro_integrations | new |
| `BARO_RECON_EXCEPTION` | **Baro Reconciliation Exception** | baro_integrations | new |
| `BARO_GPS_PLATFORM` | **Baro GPS Platform** | baro_settings | new |
| `BARO_SUBSCRIPTION_ASSET` | *Baro Subscription Asset* | baro_billing | **deferred** (Q4) |
| `FILE`, `CALENDAR_EVENT` | File, Calendar Event | frappe core | standard |
| `GPS_PLATFORM_EXTERNAL` | (no DocType) external system | — | out of ERP |

## 6. Deliberate absences

- **No telemetry entity.** Track points, speed and ignition history are not modelled at all (`01` §5). Only `baro_last_comm_at` and a platform status enum cross the boundary.
- **No `BARO Device`, `BARO Installation`, `BARO Service Inspection`, `BARO Contract`, `BARO Invoice`** — each would fork a fact ERPNext already owns (`03` §6).
- **No customer-portal or claims entities** — later phase (`90`).

# Appendix — Spot-check paths

Every standard-DocType claim in this package was read from the supplied ERPNext source, not from documentation or memory. This appendix lets a reviewer re-open any claim in about ten seconds, and records which claims came from a source tree **newer** than the v16 target and therefore carry `[verify-vs-v16]` debt (`04` §2).

---

## 1. The source under inspection

| | |
|---|---|
| Archive | `C:\Users\Lenovo\Desktop\Erp system\erpnext-develop.zip` |
| Contents | the **ERPNext app** only (7,273 files, prefix `erpnext-develop/`). The Frappe **framework** is not in it — `frappe/*` DocTypes (`File`, `Version`, `Workflow`, `Assignment Rule`, `Notification`, `Log`, `Password` fieldtype) are not verifiable from this archive |
| Branch | `develop`, i.e. **after** v16: `pyproject.toml` declares `requires-python = ">=3.14"` and `[tool.bench.frappe-dependencies] frappe = ">=17.0.0-dev,<18.0.0"` (`04` §1) |
| Also present, unused | `odoo-20.0.zip` (a different ERP; not referenced anywhere in this package), `BARO_Group_ERP360_Complete_Development_Plan.pdf` |

## 2. Reading a DocType without unpacking

Inside WSL2 or Git Bash:

```bash
Z="/c/Users/Lenovo/Desktop/Erp system/erpnext-develop.zip"

# where is it? (the module is not always where its name suggests)
unzip -Z1 "$Z" | grep '/doctype/serial_no/serial_no.json$'

# its field names and required flags
unzip -p "$Z" erpnext-develop/erpnext/stock/doctype/serial_no/serial_no.json \
  | grep -o '"fieldname": "[a-z_]*"' | sort -u

# does a specific field exist?
unzip -p "$Z" erpnext-develop/erpnext/stock/doctype/serial_no/serial_no.json \
  | grep -c '"fieldname": "imei"'      # -> 0 : there is no IMEI field, anywhere

# how many fields?
unzip -p "$Z" erpnext-develop/erpnext/accounts/doctype/subscription/subscription.json \
  | grep -c '"fieldname":'

# is field-level uniqueness a real Frappe feature? (it is: 102 uses in this tree)
unzip -p "$Z" "erpnext-develop/erpnext/**/doctype/*/*.json" | grep -c '"unique": 1'
```

PowerShell equivalent for the first two, if reviewing from Windows:

```powershell
Add-Type -A System.IO.Compression.FileSystem
$z=[IO.Compression.ZipFile]::OpenRead("C:\Users\Lenovo\Desktop\Erp system\erpnext-develop.zip")
$e=$z.Entries | ? { $_.FullName -like "*serial_no/serial_no.json" }
(new-object IO.StreamReader($e.Open())).ReadToEnd() | Select-String '"fieldname": "([a-z_]+)"' -AllMatches
$z.Dispose()
```

## 3. The paths actually used

`erpnext-develop/erpnext/` prefix omitted from every row for readability; all ten were opened and read in this session.

| # | Path | What it settled | Where it is used |
|---|---|---|---|
| 1 | `stock/doctype/serial_no/serial_no.json` | 36 fields, **no IMEI/ICCID field anywhere in the tree** — the entire custom gap. Has `serial_no, item_code, asset, location, employee, warranty_period, warranty_expiry_date, amc_expiry_date, maintenance_status, warehouse, batch_no, purchase_rate, status, customer, reference_doctype, reference_name` | `03` row 2 (the central extend-not-duplicate decision), `10` §2/§3, `11`, `31` U-1/U-6 |
| 2 | `selling/doctype/installation_note/installation_note.json` + `installation_note_item.json` | Installation Note lives in **selling**, not maintenance (a blueprint error). Fields: `naming_series, customer, customer_address, contact_person, territory, customer_group, inst_date, inst_time, status, project, items` | `03` row 9, `10` §3, `21`, `60` T1 |
| 3 | `maintenance/doctype/maintenance_visit.json` (+ `maintenance_visit_purpose`, `maintenance_visit_purpose_type`) | `item_code, serial_no, work_details, service_person, status` — usable service work records, no new BARO doctype | `03` row 10 |
| 4 | `support/doctype/warranty_claim/warranty_claim.json` | `serial_no, customer, complaint, issue_details, warranty_amc_status, warranty_expiry_date, resolution_details, service_address` — direct fit for RMA cross-reference | `03` row 12/18, `10` §2, `21` §6 |
| 5 | `accounts/doctype/subscription/subscription.json` | 40 fields incl. `plans, subscription_period, current_invoice_start/end, next_billing_period_start/end, generate_invoice_at, days_until_due, party_type/party, cancel_at_period_end, sales_tax_template, cost_center` → **recurring billing already exists** | `03` row 15, `60` T4, `51` RA-1…RA-6 |
| 6 | `crm/doctype/contract/contract.json` (+ `contract_template`) | `party_type, party, start_date, end_date, status, contract_terms, requires_fulfilment, fulfilment_deadline` — expiry automation hangs here | `03` row 14, `60` T3 |
| 7 | `stock/doctype/quality_inspection/quality_inspection.json` (+ `quality_inspection_template`) | `inspection_type, reference_type/reference_name, item_code, item_serial_no, quality_inspection_template, specification_details, readings, inspected_by, verified_by, status` — replaces the proposed `BARO Service Inspection` | `03` row 11, `10` §3 |
| 8 | `stock/doctype/item_barcode/item_barcode.json` | the DocType is **`item_barcode`** (child of Item), not `barcode` (a blueprint error) | `03` row 4 |
| 9 | `assets/doctype/asset_movement/asset_movement.json` | standard movement record; vehicle transfer does not need a BARO equivalent | `03` row 6, `90` |
| 10 | `projects/doctype/task/task.json` | the DocType is **`Task`**, not `project_task` (a blueprint error): `subject, project, issue_type, priority, depends_on_tasks, exp_start_date, act_start_date, completed_by, total_billing_amount` | `03` row 22, `21` §2, `60` T1 |

Supporting reads, same method: `stock/doctype/item/item.json` (`has_serial_no, serial_no_series, barcodes, quality_inspection_template, safety_stock, reorder_levels`), `stock/doctype/warehouse/warehouse.json` (`is_rejected_warehouse, warehouse_type`), `crm/doctype/appointment/appointment.json` + `appointment_booking_settings.json`, `support/doctype/issue/issue.json` (native SLA fields), `stock/doctype/shipment/shipment.json`, `manufacturing/doctype/job_card/job_card.json`, `setup/doctype/employee/employee.json` (`attendance_device_id` carries `"unique": 1` — the precedent for `31` layer 1), `stock/doctype/delivery_note/delivery_note.json` (`per_installed, installation_status`), `pyproject.toml`.

## 4. Negative findings (what is *absent*, and why that mattered)

| Searched for | Result | Consequence |
|---|---|---|
| `imei`, `iccid` as fieldnames across the whole tree | **0 hits** | the justification for `10` §3's custom fields; also means ERPNext gives BARO no device-identity model for free |
| an `hr` / `payroll` module inside ERPNext | **absent** | HR is the separate `frappe/hrms` app → `02` §5, `04` §3, `90` §2 |
| a `helpdesk` module inside ERPNext | absent as such; `support/doctype/issue` exists with SLA fields | the reuse-vs-app decision in `90` §2 |
| a dedicated "Reserved Stock" DocType | **absent** (reservation is expressed via `Serial No.status` / un-issued delivery notes) | `01` §2.1's reservation note: reservation stays a *device state*, not a new record |
| any partial/filtered unique index support | not a DocType property | `31` §3's UQ-DRV design instead of a database feature |

## 5. Claims that must be re-checked against real v16

These came from the post-v16 tree and are load-bearing, so they are the first things to verify once a bench exists (`04` §5's protocol). The list is reproduced in `04` §4; a reviewer should treat this row order as the verification queue:

1. `Serial No` field set still contains every field `03` row 2 relies on — if `status`/`maintenance_status` semantics changed, `10` §3's device-status enum mapping changes.
2. `Installation Note` still submittable and still in `selling`, and `Delivery Note.per_installed` still present (`01` §2.1 reservation note).
3. `Subscription` still owns the billing-date fields `60` T4 depends on; if v16 renamed `generate_invoice_at`, T4's row text changes but not its behaviour.
4. `Quality Inspection.reference_type` still a Dynamic Link able to point at `Baro Vehicle` — the whole `03` row 11 verdict depends on it.
5. Field-level `"unique": 1` exists in the v16 Frappe release (framework, not this archive) and behaves as a real UNIQUE index on a nullable column.
6. `frappe.cache().lock()` exists in v16 Frappe, and `GET_LOCK` as the fallback (`31` §5.2).
7. `Employee` still lives in ERPNext `setup` (so `baro_technician` can Link to it without `hrms` installed).
8. `Appointment` / `Appointment Booking Settings` exist in v16 `crm` (`03` row 23).
9. `Contract` in v16 `crm` still exposes `status` + `end_date` as the T3 scan reads them.
10. Naming-series behaviour for `format:{field}-{field}` on two Data fields (`Baro Platform Mapping` PK trick, `30` §3).

## 6. How to keep this appendix honest

If a future revision of this package cites a standard DocType field, it must add a row to §3 or §4 in the same change. A claim with no path is a guess, and `80-verification-checklist.md` treats it as a defect.

# 04 — Version Compatibility Matrix and Verification Debt

## 1. The contradiction this package resolves first

BARO supplied `C:\Users\Lenovo\Desktop\Erp system\erpnext-develop.zip` and chose **ERPNext v16 stable** as the target. Those are not the same codebase.

Evidence read directly from the supplied archive (`erpnext-develop/pyproject.toml`):

```toml
requires-python = ">=3.14"
[tool.bench.frappe-dependencies]
frappe = ">=17.0.0-dev,<18.0.0"
```

So the downloaded tree is the **post-v16 development line** (Frappe v17-dev, Python 3.14). It is the right place to learn ERPNext's structure, and the wrong place to assert what v16 contains.

**Consequence:** every standard-DocType field claim in this package was read from that tree and is tagged `[verify-vs-v16]`. The tag is not hedging — it marks a specific, cheap verification step to perform the moment v16 source is available, listed in §5.

## 2. Target stack for release 1

| Component | Target | Why | Verify before install |
|---|---|---|---|
| Frappe framework | v16 stable line | Framework of ERPNext v16 | `bench init --frappe-branch version-16` |
| ERPNext | v16 stable | Business modules reused here | `bench get-app erpnext --branch version-16` |
| Python | whatever v16's `pyproject.toml` declares (≤ the 3.14 that develop demands) | develop requires 3.14, which Ubuntu LTS does not ship; a v16 pin should be installable on Ubuntu 24.04 | read v16 `pyproject.toml` |
| MariaDB | v16-supported series | ERPNext is tuned to MariaDB; Postgres support is uneven | v16 docs |
| Redis | cache + queue instances | `scheduler_events`, named locks (§6) | standard |
| Node | ≥ the version v16's `package.json` requires — **this machine has Node 16.20.2, which will be too old** for a current ERPNext asset build | `bench build` fails on old Node | check, then install via nvm in WSL2 |
| `baro_core` (custom) | develop against v16, never against develop | prevents inheriting v17-only APIs | pin in app `pyproject.toml` |
| `hrms` | only when the HR workspace is built (later phase) | separate app, separate release cadence | compat matrix at install time |
| `helpdesk` | optional; ERPNext `support/doctype/issue` already carries SLA fields | avoid a dependency that release 1 does not need | compat matrix at install time |

## 3. Structural facts confirmed from the supplied tree (safe to rely on)

These are long-standing and cross-version, so they inform the design regardless of v16 details:

- ERPNext has **no HR/payroll module** (module list contains `accounts, assets, banking, buying, crm, maintenance, manufacturing, projects, quality_management, selling, stock, support, telephony, utilities…` and no `hr`/`payroll`). HRMS is a separate app.
- `Subscription` + `Subscription Plan` provide recurring billing end to end.
- Recurring stock identity is `Serial No`, with stock movements expressed through `Serial and Batch Bundle` (`stock/doctype/serial_and_batch_bundle`, with `voucher_type, voucher_no, entries, type_of_transaction, warehouse`) — modern ERPNext routes serials through bundles rather than free-form serial text. `installation_note_item` carries both `serial_no` **and** `serial_and_batch_bundle`.
- Field-level uniqueness is a real Frappe capability: `"unique": 1` appears 102 times across this tree. Precedents worth citing to a reviewer: `Item.item_code`, `Customer.alias`, `Customer.represents_company`, `Supplier.alias`, and **`Employee.attendance_device_id`** — an external device identifier constrained unique on a master record, which is exactly BARO's IMEI/ICCID case.
- `Serial No` sets `search_index: 1` on `serial_no`, `maintenance_status`, `company` — precedent for indexing BARO's scan keys.
- A dedicated `Reserved Stock` DocType is **absent** from this tree. Reservation semantics therefore hang on open Sales Order / un-issued Delivery Note, not on that doctype (`01-architecture-overview.md` §2.1).

## 4. Version-sensitive claims (the `[verify-vs-v16]` list)

Each of these must be re-checked against v16 source; none of them should be written into app code before that check.

| Claim | Used in | Risk if v16 differs |
|---|---|---|
| `Serial No` field set (`warranty_expiry_date, amc_expiry_date, maintenance_status, status, customer, warehouse, location, employee`) | `10`, `21`, `31` | Low. Stable for many versions. |
| `Installation Note` lives in `selling` and links items with `serial_no` / `serial_and_batch_bundle` | `03`, `20` | Medium in v15 (bundle migration); verify child-table fields. |
| `Delivery Note.per_installed` / `installation_status` | `01` §2.1 | Low–medium. |
| `Subscription` 40-field set incl. `generate_invoice_at`, `plans`, `cancel_at_period_end` | `03`, `60` | Low. |
| `Issue` SLA timer fields (`service_level_agreement, response_by, avg_response_time, on_hold_since, total_hold_time`) | `02`, `90` | Medium — v16 support/Helpdesk boundaries shifted; verify before promising SLA metrics. |
| `Item.safety_stock` / `reorder_levels` producing reorder recommendations | `60` | Low. |
| `Appointment` + `Appointment Booking Settings` in `crm` | `03` | Low–medium. |
| `Quality Inspection.reference_type/reference_name` accepting a custom DocType | `03`, `20` | Low, but confirm Link targets allow `Baro Device Assignment`. |
| `frappe.cache().lock()` availability and semantics | `31` | Medium — API surface differs across frappe major versions. |
| Generated-column / DDL approach as fallback | `31` | Medium — depends on MariaDB version and Frappe's schema sync behaviour. |

## 5. Verification protocol (run once a v16 bench exists)

```bash
# inside WSL2 Ubuntu, in the bench directory
bench --version
python3 --version
grep -A3 "frappe-dependencies" apps/erpnext/pyproject.toml
grep "requires-python" apps/erpnext/pyproject.toml apps/frappe/pyproject.toml

# confirm each [verify-vs-v16] field exists in the pinned version
for f in warranty_expiry_date amc_expiry_date maintenance_status; do
  grep -o "\"fieldname\": \"$f\"" apps/erpnext/erpnext/stock/doctype/serial_no/serial_no.json
done
grep -o '"fieldname": "serial_and_batch_bundle"' apps/erpnext/erpnext/selling/doctype/installation_note_item/installation_note_item.json
grep -o '"fieldname": "per_installed"' apps/erpnext/erpnext/stock/doctype/delivery_note/delivery_note.json
grep -o '"fieldname": "generate_invoice_at"' apps/erpnext/erpnext/accounts/doctype/subscription/subscription.json
ls apps/erpnext/erpnext/ | grep -E "^(hr|payroll|hrms)$"   # must be empty
```

Until then, the spot-check commands against the supplied archive in `appendix/spot-check-paths.md` are the reference.

## 6. Environment reality for the WSL2 install (future step, recorded now)

Not part of this deliverable, but the design depends on it being feasible, so the constraints are recorded here:

- WSL2 is enabled on this machine at default version 2, **with no distribution installed**. `wsl --install -d Ubuntu-24.04` needs elevation and a reboot.
- No Python, no Docker, no MariaDB/Redis, no yarn; Node is **16.20.2** (too old for a current ERPNext build). All of this is installed inside WSL2, not on Windows.
- Frappe's official playbook is a native Ubuntu bench; Docker is the alternative. The blueprint's "Ubuntu Server / Docker or Bench" line stays valid — choose bench-in-WSL2 to mirror the eventual Ubuntu Server production host.
- Windows-native development is not supported by Frappe and is rejected: MariaDB/Redis/wkhtmltopdf/service-manager integration is where projects like this fail slowly.

## 7. Upgrade policy implied by this design

1. **Never patch ERPNext core.** All BARO behaviour lives in `baro_core` as Custom Fields, Property Setters, Workflows and controllers on BARO DocTypes. This is what makes the v16 → v17 step cheap and is why the blueprint's own advice ("do not modify ERPNext's core source") is restated as a hard rule.
2. Custom Field names are prefixed `baro_` so an upstream addition can never silently collide with one.
3. Every standard-Doctype assumption above is documented with a file path, so an upgrade diff can be reviewed in minutes instead of discovered in production.
4. Test suite (§ `80-verification-checklist.md`) must include the uniqueness and overlap cases as automated tests, because they are the acceptance criteria most likely to break on an upgrade.

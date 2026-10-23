# 02 — App Boundary Decision

**Decision: release 1 ships ONE custom Frappe app, provisionally `baro_core`, internally partitioned into modules that mirror the six boundaries the revised blueprint proposed.** The six-app layout is recorded as a valid *future* decomposition, not a starting condition.

## 1. What the blueprint proposed

```
apps/ ├── frappe/ ├── erpnext/ ├── hrms/ ├── helpdesk/
      ├── baro_core/ ├── baro_fleet/ ├── baro_devices/
      ├── baro_field_service/ ├── baro_subscriptions/ └── baro_integrations/
```

Plus a correct instinct the blueprint states: *"we should not build everything from scratch… concentrate development effort on BARO's specialized workflows"* — this design honours that instinct more aggressively than the app list does.

## 2. Why six apps now is the wrong call

| # | Coupling cost | What actually happens in Frappe |
|---|---|---|
| 1 | **DocType → module is baked in** | A DocType's `module` is stored on the `DocType` record and drives where its JSON/controller live. Re-parenting `Baro Vehicle` from `baro_fleet` to `baro_core` later means migrating `tabDocType`, `tabDocField` and every `Link` field that points at it, in every environment including production. Getting a boundary wrong in one app is a rename; getting it wrong across six apps is a schema migration. |
| 2 | **Six patch chains, cross-app ordering** | Each app owns `patches.txt`. A `baro_devices` patch that assumes a `baro_core` DocType already exists only works if `bench migrate` happens to apply them in a safe order. One app = one ordered list. |
| 3 | **One scheduler, six `hooks.py`** | `scheduler_events`, `doc_events`, `fixtures` and `override_doctype_class` are process-wide. Six apps registering the same daily reconciliation job produces duplicate runs or a silent race; the fix is to centralise them, which is exactly what one app does for free. |
| 4 | **Permission/role fixture drift** | Roles and permission levels are app-scoped fixtures. Six apps each shipping role JSON can overwrite one another on `bench --site all reload-docs`, and the resulting permission set differs from any single app's intent. |
| 5 | **Compatibility matrix explosion** | Every upgrade must be tested across `frappe × erpnext × hrms × helpdesk × N custom apps`. Four standard apps plus six custom ones is a ten-variable matrix for a team the roadmap assumes is small. |
| 6 | **The boundaries are untestable today** | No BARO workflow has run yet. Splitting an app before the schema has been used is guessing where the seams are; the spine's real seam — device identity vs stock vs billing — is already drawn by ERPNext itself. |

## 3. Where the split lines still matter

The internal module partition is deliberate and is what later makes a split cheap. Every DocType in `10-data-dictionary.md` carries an `owning module` column with these values:

| Module (inside `baro_core`) | Owns | Future app if split |
|---|---|---|
| `baro_fleet` | `Baro Vehicle` | baro_fleet |
| `baro_devices` | `Baro Firmware History`, `Baro Device RMA`, Custom Fields on `Serial No` | baro_devices |
| `baro_connectivity` | `Baro SIM Card` | baro_devices or its own app |
| `baro_field_service` | `Baro Device Assignment`, Custom Fields on `Installation Note` | baro_field_service |
| `baro_billing` | `Baro Subscription Asset` (deferred) | baro_subscriptions |
| `baro_integrations` | `Baro Platform Mapping`, `Baro Integration Log`, connector jobs | baro_integrations |
| `baro_settings` | `Baro GPS Platform` (one row per platform, holds `Password`-type secrets), `Baro Operations Settings` (Single: thresholds, regexes, notice windows), numbering rules | baro_core |

## 4. Conditions that justify splitting later

Split **only** when at least one is true:

1. A subset needs to be installed alone (e.g. the integrations connector sold to another group company without the fleet schema).
2. Two teams ship on genuinely independent release cadences with separate test owners.
3. An app's patch/fixture surface has grown enough that its upgrade risk is measurably different from the rest.

Split mechanics are documented so they are not discovered under pressure: rename module on the DocType record + move JSON/controller + re-point links + one patch per environment, done for **one** module at a time, never all six in one release.

## 5. Consequences for this document package

- `21-custom-doctype-fields.md` names DocTypes with the `Baro ` prefix but assigns them to the modules in §3, so a later split is a packaging exercise, not a redesign.
- `41-role-permission-matrix.md` defines roles as BARO-wide, not per-app, so fixtures live in one place.
- `50-integration-contracts-gps.md` keeps the connector behind an internal module boundary with no direct writes to other modules' tables — the seam that would become an app interface.
- `90-later-phase-backlog.md` re-lists the six-app proposal as deferred, with these conditions as the gate.

## 6. Standard apps and their status

| App | Role | Version gate |
|---|---|---|
| `frappe` | Framework, RBAC, queues, `Calendar Event` | Pin to v16 line; **verify actual pin** — the downloaded ERPNext tree requires `frappe >=17.0.0-dev,<18.0.0`, which is *newer* than v16 |
| `erpnext` | Stock, selling, accounts, maintenance, support, crm, quality, projects, assets | v16 stable |
| `hrms` | Employees, attendance, leave, payroll, appraisal ("Performance Evaluation" workspace) | **Not in ERPNext** — confirmed: no `hr`/`payroll` module in the ERPNext tree. Separate app, separate compatibility pin. Out of release-1 scope. |
| `helpdesk` | Modern ticketing/SLA workspace | Frappe's dedicated Helpdesk app is a separate project with fast-moving versioning. Note that ERPNext's own `support/doctype/issue` already carries full SLA fields (`service_level_agreement, response_by, first_responded_on, avg_response_time, resolution_time, on_hold_since, total_hold_time`) `[verify-vs-v16]` — release 1 needs neither app for the spine. |

## 7. Counter-arguments, addressed

- *"Modular apps are cleaner."* Modularity is delivered by Python packages and module boundaries; separate Frappe apps buy isolation you do not need until a second consumer exists, and cost migration coupling you cannot undo cheaply.
- *"Six apps matches the org chart."* The org chart maps to **workspaces and roles** (`41-role-permission-matrix.md`), which are configuration, not deployment units.
- *"Integrations code should be isolated because it's riskiest."* Isolate it by module and by a documented internal interface; if it later needs isolation for real, it is the first module to split out — it has the fewest inbound `Link` fields.

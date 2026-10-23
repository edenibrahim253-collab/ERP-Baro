# 41 — Role and Permission Matrix

Permissions are the design's enforcement layer: the blueprint's own requirement is that access is "enforced on the server and at the record level, not merely by hiding workspace menus". Everything below is DocPerm / User Permission / Permission Query Condition configuration, shipped as fixtures (`30` §8). Client-side hiding is cosmetic only.

## 1. Role inventory

| Role | Department | Headcount guess | Holds approver rights? | Notes |
|---|---|---|---|---|
| `BARO Sales Officer` | Sales | 5–15 | no | Customer, Contract, Quotation drafting |
| `BARO Fleet Officer` | Fleet / Technical | 2–5 | no | Vehicle registry, owner transfers |
| `BARO Installer` | Technical (field) | 10–40 | no | Maker for assignments; record-scoped |
| `BARO Service Supervisor` | Technical | 2–8 | partial | Submits; approves within ops limits |
| `BARO Approver` | Management / Technical lead | 2–6 | **yes (ops)** | Assignment approval, scrap, overrides |
| `BARO Stock Manager` | Warehouse | 2–6 | no (stock rights only) | Device registration, IMEI, transfers, dispositions |
| `BARO Connectivity Admin` | Technical / SIM | 1–3 | no | SIM lifecycle; sole reader of PIN/PUK |
| `BARO Support Agent` | Customer Care | 3–15 | no | Issue, Warranty Claim, RMA creation |
| `BARO Accounts User` | Finance | 2–8 | no | Invoices, subscriptions, supplier credit |
| `BARO Finance Approver` | Finance manager | 1–3 | **yes (money)** | Suspension-for-payment, write-offs, discounts |
| `BARO Procurement Officer` | Procurement | 1–4 | no | Purchase flow, reorder recommendations |
| `BARO Report Viewer` | All staff (read-only) | everyone | no | Dashboard/list read for non-operators |
| `BARO Integrator` | IT (bot, non-interactive) | 1–2 users | **no — cannot submit anything** | API-only service user (`30` §10) |
| `BARO System Manager` | IT | 1–3 | emergency only | Configuration, forced transitions (audited) |

Plus standard ERPNext roles (`Stock User`, `Stock Manager`, `Accounts User`, `Sales User`, `Support Team`, `HR User`…) — granted **as needed alongside** BARO roles, never instead of them, so BARO role membership stays the single source of duty assignment.

## 2. Document-level matrix (release-1 DocTypes)

Legend: **C**reate **R**ead **W**rite **S**ubmit **Ca**ncel **A**mend **D**elete **P**rint **I**mport **E**xport. Blank = no access at all (not merely read-denied).

| DocType | Sales Officer | Fleet Officer | Installer | Service Supervisor | Approver | Stock Manager | Connectivity Admin | Support Agent | Accounts User | Finance Approver | Integrator | System Manager |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Baro Vehicle | C R W P E | C R W S* P I E | R | R W P | R W Ca | R | R | R | R | R | R | R W D |
| Baro Device Assignment | R | R W | C R W P I* | C R W S Ca A P | R S Ca A | R | R | R | R | R | R | R D† |
| Baro SIM Card | — | R | R | R W | R | R | C R W S Ca A P I | R | R | R | R | R |
| Baro Platform Mapping | — | R | R | R | R | R | R | R | — | — | C R W I | C R W D |
| Baro Firmware History | — | R | R | R | R | C R W | R | R | — | — | C R W | R D† |
| Baro Device RMA | — | R | C R W | C R W S P | R S Ca A | R W | R | C R W P | R | R | R | R |
| Baro Integration Log | — | — | — | — | — | R | R | R | — | — | C R W | R E D‡ |
| Baro Reconciliation Exception | R | R W | — | R W | R W (Waive) | R W | R W | R | R W | R | C R W ◊ ★ | C R W D E |
| Baro GPS Platform | — | — | — | — | — | — | R | — | — | — | R (secrets hidden) | C R W D |
| Baro Operations Settings | — | — | — | — | — | — | — | — | — | — | R | C R W |
| Serial No (standard) | R | R | R W(imei only§) | R | R | C R W S P I | R | R W (status read) | R | R | R W(baro_*, last_comm) | R W D |
| Installation Note (standard) | — | R | C R W S P | R S Ca A P | R | R | R | R | R | R | R W(activation) | R |
| Quality Inspection (standard) | — | R | C R W | R W S P | R | R W S | R | R | — | — | R | R |
| Warranty Claim (standard) | — | R | R | R | R | R | R | C R W S P | — | — | R | R |
| Issue (standard) | R | R | R | R | R | R | R | C R W S P | R | R | C R W | R |
| Stock Entry / Delivery Note / Purchase Receipt | — | R | R | R | R | C R W S Ca A P I | R | R | R | R | — | R |
| Sales Order / Quotation / Contract | C R W S P I | R | R | R | R | R | — | R | R | R | — | R |
| Subscription / Sales Invoice | R | — | — | — | — | — | — | R | C R W S P I | R S Ca A | — | R |
| Project / Task | R | R | R W(task close) | R W S | R | R | R | R | R | R | — | R |

`S*` = submit of a master-status change (Retire/Transfer) only.
`I*` = import allowed because historical assignments arrive by CSV (`20` §8) — the same `validate`/`before_submit` guards apply (`31` §8 T-9).
`†` = delete only for never-transacted records; a document that ever reached Active is retired by cancel/amend, not deleted.
`‡` = delete occurs only through the documented archive job (`50` §7), never interactively.
`§` = IMEI entry on a GPS serial is Write-allowed for Installer-supervised roles via **field-level permissions**, not by granting whole-document write.
`◊` = `BARO Integrator` may Create/Read/Write an exception because the reconciliation job runs as that user, but `baro_status` is a **permlevel-1 field for it**: the bot may set `Open`/`Acknowledged`/`In Progress` and `baro_cleared_automatically`; it may never set `Resolved` or `Waived` (`51` §7).
`★` = Delete is `BARO System Manager` only and only for rows the run itself re-created; a human-closed exception is never deleted, so the audit trail of "we knew and fixed it" survives.

## 3. Field-level permissions (Permlevel)

Frappe permission levels gate fields, which is how a document stays broadly readable while its sensitive parts do not:

| Field(s) | Permlevel 0 (everyone with R) | Permlevel 1 (restricted) | Who holds level 1 |
|---|---|---|---|
| `Baro SIM Card.baro_pin`, `.baro_puk` | hidden | readable | `BARO Connectivity Admin`, `BARO System Manager` |
| `Baro GPS Platform.baro_api_key`, `.baro_api_secret`, `.baro_webhook_secret` | hidden | readable | `BARO System Manager` only |
| `Serial No.baro_last_comm_at`, `Baro Platform Mapping.baro_last_comm_at`, `.baro_platform_status` | visible read-only | writable | `BARO Integrator` (and System Manager) |
| `Baro Vehicle.baro_current_device`, `.baro_current_assignment`; `Baro SIM Card.baro_installed_device` | visible read-only | writable | controller/`doc_events` only |
| `Baro Device Assignment.baro_active_*_key` | hidden | writable | controller only — never granted to a human role |
| `Baro Reconciliation Exception.baro_status`, `.baro_waive_reason` | readable | writable | business roles for `Open`→`In Progress`→`Resolved`; `BARO Approver` only for `Waived`; `BARO Integrator` blocked from `Resolved`/`Waived` (`51` §7) |
| `Installation Note.baro_customer_signature` | readable | — | readable by Support/Supervisor; never in public print formats |

Location data rule: the blueprint requires restricted access to vehicle location. Because no telemetry is stored (`01` §5), what BARO exposes is *presence metadata* — last communication time and platform status. Those fields sit at permlevel 1 as above, so a role that legitimately needs the device record does not automatically gain surveillance-adjacent detail.

## 4. Submit / cancel authority is permission-based, workflow-driven

A Workflow state controls *which transition is offered*; the ability to submit or cancel at all comes from DocPerm (`S`/`Ca` columns). Both must line up:

| Document | May submit | May approve transition to Active/Approved | May cancel |
|---|---|---|---|
| Baro Device Assignment | Installer (creates), Supervisor (submits) | **Approver only**, never the owner | Supervisor (pre-activation), System Manager (audited) |
| Baro SIM Card | Connectivity Admin | Approver (suspension/reactivation) | Connectivity Admin |
| Baro Device RMA | Support Agent / Installer / Supervisor | Approver (scrap, out-of-warranty override) | Supervisor |
| Installation Note | Installer | Supervisor (activation verified, jointly with the connector's status) | Supervisor |
| Subscription / Sales Invoice | Accounts User | Finance Approver | Finance Approver |

The "never the owner" check is implemented server-side in the transition handler (`40` §6), not only as a workflow condition.

## 5. Record-level access

### 5.1 User Permissions (link-based scoping)

Applied per user or per role-with-default; `apply_user_permissions` **enabled** on the DocType where scoping matters:

| User Permission doctype | Scopes | Typical holder |
|---|---|---|
| `Customer` | vehicles, assignments, invoices, tickets | account managers, branch staff |
| `Warehouse` | device stock views, stock entries | storekeepers per site |
| `Company` | everything financial | group vs branch staff |
| `Employee` | tasks, technician-filtered lists | supervisors |
| `Territory` / `Item Group` | reporting slices | analysts |

`Baro Vehicle` and `Baro SIM Card` are not default User-Permission targets, so the app must (a) enable `apply_user_permissions` on them, and (b) add `customer`, `company` and `baro_technician` as allowed link doctypes via the customised DocType (`User Permission` for `DocType` allow-list). Without that, branch scoping silently leaks across the fleet register — the single most common way a "role-based" ERP leaks data.

### 5.2 Permission Query Conditions (SQL-level row filters, per role)

| Role | DocType | Condition |
|---|---|---|
| `BARO Installer` | Baro Device Assignment | `tabBaro Device Assignment.baro_technician = <login employee>` — sees own jobs plus their own drafts |
| `BARO Service Supervisor` | Baro Device Assignment | branch scope via `company`/`customer` User Permissions (no hard-coded SQL) |
| `BARO Support Agent` | Baro Vehicle, Serial No | customer set they serve; no condition needed if User Permissions are applied |
| `BARO Integrator` | all | `enabled = 1` style restrictions via role; **no** condition that hides documents it must write |
| `BARO Report Viewer` | all BARO docs | read-only, full set (management reporting) |

Conditions are stored as fixtures and reviewed with the role matrix; they are the last line of defence when a list report is built by someone else.

### 5.3 Reports, pages and workspaces

| Item | Access |
|---|---|
| `BARO - Assignment History`, `BARO - Pending Activations` | Role Permission for Report: Supervisor, Approver, Fleet Officer, Support, Accounts, Report Viewer |
| `BARO - Fleet Reconciliation` | Supervisor, Approver, System Manager, Report Viewer (`51` §10) |
| `BARO - Revenue Assurance` | Accounts User, Finance Approver, Approver, System Manager — **not** Report Viewer or Support Agent; it names money the customer has not paid (`51` §10) |
| `BARO - Reconciliation Inbox` (list view on `Baro Reconciliation Exception`) | filtered by `baro_assigned_role`; each role sees its own queue, Approver and System Manager see all |
| Device 360 / Customer 360 pages | follow the underlying document permissions (they read through Frappe, never raw SQL) — `30` §10 |
| One-Scan Lookup page | any authenticated BARO role; returns "no result" rather than "not permitted" so scanning is not an oracle for enumerating other customers' devices |
| Workspaces (`BARO Fleet`, `BARO Devices`, `BARO Installations`) | role-restricted menus, explicitly **not** the security boundary |

### 5.4 Unmapped inbound devices (`Mapping missing`)

A platform event that references an unknown `platform_device_id` or IMEI does **not** create a `Serial No` and does **not** create a mapping — the connector has no Create permission on `Serial No` (`2` above) precisely so a bot cannot mint inventory records. It writes one `Baro Reconciliation Exception` of type `Mapping missing` assigned to `BARO Stock Manager`, and stops.

Closing it is a human decision with two legitimate outcomes, both recorded on the exception:
- the device is genuinely BARO's and was never registered → Stock Manager registers the `Serial No` (+ `Baro Platform Mapping`), then sets `Resolved`;
- the device is not BARO's (stale platform record, customer-owned hardware, wrong platform account) → `BARO Approver` sets `Waived` with `baro_waive_reason`, and `50` §5 records the release decision (`release_device`) separately.

This keeps "who is allowed to make a device exist" a single answer: a human with Serial No Create, under the stock role.

## 6. Segregation of duties

| Duty pair | Conflict | Control |
|---|---|---|
| Register IMEI ↔ approve assignment | Stock Manager could push a device live | Approver role separate; supervisor submits, approver approves |
| Raise RMA ↔ approve Scrap | Support could dispose inventory | Scrap requires `BARO Approver` + a stock entry only Stock Manager can make |
| Suspend service ↔ credit note | One person both cuts and refunds | suspension requires Finance Approver; Accounts User cannot approve |
| Configure platform secrets ↔ approve business transitions | an integrator-role human could self-approve | secrets are System Manager only; System Manager is not granted Approver by default |
| Import data ↔ approve assignments | import bypasses maker-checker | `I`mport rights limited to Fleet Officer/Supervisor/Stock Manager, and imported assignments land as Draft unless the approver executes the transition (`31` §8 T-9) |
| Emergency force-transition ↔ normal operation | audit evasion | allowed only for System Manager with mandatory reason; every instance appears in the daily forced-transition report (`40` §6) |

## 7. Privileged-access and identity controls

1. **MFA** required for `BARO System Manager`, `BARO Approver`, `BARO Finance Approver`, and any account holding Password-perlevel fields. Enforced via Frappe two-factor setup; role-based enforcement is a documented gap in standard Frappe, so onboarding must gate it manually and `80` lists it as a control check.
2. **Service users** (`BARO Integrator`) use API token or token-scoped auth, no UI login, IP-restricted where the platform supports it, token rotation ≤ 12 months, and they can never be granted `Submit` on any business document (`2` matrix columns show no `S`).
3. No shared accounts. Branch kiosks use `BARO Installer` users named per technician; performance reporting depends on this (`21` §2 `baro_technician`).
4. Quarterly **access review** report: role membership × record scope × last login; offboarding checklist disables the user, reassigns open drafts/tasks, and revokes API tokens.
5. Vehicle-location and communication presence detail is treated as sensitive personal data for compliance purposes (Q1 governs the retention/consent position), and is why those fields sit at permlevel 1.

## 8. Audit expectations

| Event | Where it lands |
|---|---|
| Any field change on a BARO DocType | `Version` (from `track_changes: 1`) |
| Workflow transition (who, when, reason) | `Workflow Action` rows |
| Forced/emergency transition | Workflow Action + forced-transition daily report |
| Data import | Data Import log with row-level results |
| Integration side effects | `Baro Integration Log` (with correlation id) |
| Permission or role change | `Version` on `Role`/`DocPerm`/`User Permission` + Activity Log |
| Login failures, token use | Activity Log / Auth log |

`BARO Report Viewer` cannot see audit tables; audit review belongs to `BARO System Manager` and, for financial changes, `BARO Finance Approver`.

## 9. Department → workspace defaults (configuration, not security)

| Department | Workspaces | Roles granted |
|---|---|---|
| Management | Dashboard, Approvals, Analytics | Approver, Report Viewer |
| Sales | CRM, Fleet (read), Contracts | Sales Officer |
| Warehouse | Devices, Stock, Procurement | Stock Manager, Procurement Officer |
| Technical | Installations, Fleet, SIM, Quality | Installer, Supervisor, Connectivity Admin |
| Customer Care | Helpdesk, Fleet, Devices (read) | Support Agent |
| Finance | Billing, Accounting, Claims | Accounts User, Finance Approver |
| IT | Administration, Integrations, Audit | System Manager, Integrator (bot) |

This table drives workspace menus and onboarding bundles. It does **not** substitute for §2–§5, and the docs say so in the workspace footer so nobody mistakes a hidden menu for a permission.

## 10. Tests

`test_permissions.py` (`30` §14) must assert at minimum:
- installer reads only own assignments (5.2), and a second installer's record raises `PermissionDoesNotExist`
- owner cannot approve their own submission (6, `40` §6)
- Support Agent cannot read `baro_pin`/`baro_puk` (3)
- Integrator cannot submit an assignment (`docstatus` attempt raises)
- branch-scoped Fleet Officer cannot read another branch's vehicle (5.1)
- Report Viewer cannot write anything (2)
- One-Scan lookup returns no result rather than a permission error for an out-of-scope IMEI (5.3)

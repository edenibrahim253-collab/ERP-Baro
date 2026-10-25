# BARO ERP 360° — Architecture & Schema Design Package

The design documents below are the approved artefact, and they have been **built**: `baro_core/`
is the Frappe app generated from them (11 DocTypes, 9 fixture files, integration layer, scheduler,
patches, tests). There is still no runtime here — no Python, no MariaDB, no bench — so the app is
verified structurally, not executed. `docs/80-verification-checklist.md` §11 lists the 13 checks
`tools/validate-structure.mjs` runs and what they cannot prove.

Scope is the **asset spine** — customers, inventory/warehouse, GPS devices, SIM cards, vehicles, device assignments, installations — targeted at **ERPNext v16 stable**, to be run later on WSL2 Ubuntu + bench.

## Status

| | |
|---|---|
| Release-1 boundary | fixed: the spine; every other module is named, deferred and given an unlock condition (`docs/90-later-phase-backlog.md`) |
| Built | `baro_core/` — 11 DocTypes, controllers, 9 fixture files (3 are documented placeholders), integration layer, scheduler, 4 patches, 3 test modules (`baro_core/README.md`) |
| Custom schema proposed | 9 business DocTypes + 1 Single + 15 Custom Fields on 6 standard DocTypes (`docs/03-standard-vs-custom-decision-table.md` §2) |
| Verified against | the supplied `erpnext-develop.zip` source (`docs/appendix/spot-check-paths.md`) |
| Verification debt | every standard-DocType claim from that tree is tagged `[verify-vs-v16]` — the archive is post-v16 (frappe v17-dev, Python ≥3.14) (`docs/04-version-compatibility-matrix.md`) |
| Blocking stakeholder questions | 7 of 19 (`docs/70-open-questions-stakeholders.md`) |
| Open defects | listed in `docs/80-verification-checklist.md` §8 — including one that cannot be closed on this machine: Mermaid blocks have not been render-validated |

## Read in this order

| # | Document | Decides |
|---|---|---|
| 1 | [`docs/01-architecture-overview.md`](docs/01-architecture-overview.md) | what release 1 is, boundaries, the no-telemetry rule |
| 2 | [`docs/02-app-boundary-decision.md`](docs/02-app-boundary-decision.md) | one custom app now, not six — and the criteria for splitting later |
| 3 | [`docs/03-standard-vs-custom-decision-table.md`](docs/03-standard-vs-custom-decision-table.md) | per entity: reuse / extend / build. **The spine every other doc reconciles against** |
| 4 | [`docs/04-version-compatibility-matrix.md`](docs/04-version-compatibility-matrix.md) | version pins, and what must be re-verified against v16 |
| 5 | [`docs/10-data-dictionary.md`](docs/10-data-dictionary.md) | **single source of truth for every field name** |
| 6 | [`docs/11-entity-relationship-diagram.md`](docs/11-entity-relationship-diagram.md) | three Mermaid ERDs + 16 cardinality/authority rules |
| 7 | [`docs/20-module-spec-asset-spine.md`](docs/20-module-spec-asset-spine.md) | areas, screens, imports, 15 UAT scenarios |
| 8 | [`docs/21-custom-doctype-fields.md`](docs/21-custom-doctype-fields.md) | per-DocType behaviour, hook maps, error messages |
| 9 | [`docs/30-schema-conventions.md`](docs/30-schema-conventions.md) | naming, prefix, fixtures, APIs, jobs, testing |
| 10 | [`docs/31-uniqueness-concurrency-design.md`](docs/31-uniqueness-concurrency-design.md) | how "no duplicate active IMEI" is actually enforced — 3 layers, 13 tests |
| 11 | [`docs/40-workflows-approvals.md`](docs/40-workflows-approvals.md) | "detection is not action": state machines and approvals |
| 12 | [`docs/41-role-permission-matrix.md`](docs/41-role-permission-matrix.md) | 14 roles, server-side and record-level enforcement |
| 13 | [`docs/50-integration-contracts-gps.md`](docs/50-integration-contracts-gps.md) | platform client contract, idempotency, retries, dead letters |
| 14 | [`docs/51-reconciliation-exception-design.md`](docs/51-reconciliation-exception-design.md) | three-way diff, 5 buckets, revenue assurance, circuit breaker |
| 15 | [`docs/60-automation-trigger-catalog.md`](docs/60-automation-trigger-catalog.md) | all 14 automated behaviours, and the 7 rejected ones |
| 16 | [`docs/70-open-questions-stakeholders.md`](docs/70-open-questions-stakeholders.md) | what only BARO can answer |
| 17 | [`docs/90-later-phase-backlog.md`](docs/90-later-phase-backlog.md) | the deferred 24 workspaces, AI assistant, mobile offline, HRMS, portals |
| 18 | [`docs/80-verification-checklist.md`](docs/80-verification-checklist.md) | the plan's eight structural checks, run as ten automated ones, with results and residual debt |
| — | [`docs/appendix/spot-check-paths.md`](docs/appendix/spot-check-paths.md) | how to re-open any standard-DocType claim in the source |

## Viewing the diagrams

All diagrams are **Mermaid** inside fenced code blocks — 12 blocks across six documents: 3 `erDiagram` (`11`), 3 `flowchart` (`01`, `50`, `20`), 5 `stateDiagram-v2` (`40` ×4, `51` ×1) and 1 `sequenceDiagram` (`50`). They render in GitHub, VS Code's Markdown preview, Obsidian and Qoder's preview with nothing installed.

Mermaid was chosen over PlantUML deliberately: PlantUML needs a JRE plus a jar or a server, and this machine has neither. No Python, Docker, MariaDB, Redis or WSL distro is installed here either, which is why the deliverable is documents rather than a running instance (`04` §5).

## The five things a reviewer should actually check

1. **`03` §2** — is the reuse/extend/build verdict right for BARO's operation? Everything downstream is derived from it.
2. **`31` §3–§5** — does BARO accept that `validate` alone *cannot* meet "no duplicate active IMEI", and that the mechanism is a Python-maintained unique key plus a lock plus `SELECT … FOR UPDATE`? This is the headline acceptance criterion, and the design says plainly what makes it true.
3. **`40` §1 and `60` §7** — the rule that no scheduled job may suspend a service, post an invoice, or auto-resolve a mismatch. It comes from BARO's own written invariant.
4. **`41` §2–§5** — permissions enforced server-side and at record level, not by hiding menus. Again BARO's own requirement.
5. **`70` §1** — the seven blocking questions. `70` §4 shows the spine can be finished with only Q4, Q6, Q12, Q13, Q16, Q17 and Q18 answered; the rest land in configuration, an adapter, or a later phase.

## What changed relative to the two blueprints

| Blueprint said | This package says | Why |
|---|---|---|
| six custom apps | one app, seven internal modules, with explicit split criteria | a DocType's module is baked into its metadata and every Link pointing at it; six apps means six patch chains, six `hooks.py` competing for one scheduler job, and a compatibility matrix of 5 apps × 6 instead of 5 × 1 |
| `BARO Device`, `BARO Installation`, `BARO Service Inspection` as new DocTypes | extend `Serial No`, `Installation Note`, reuse `Quality Inspection` | a parallel device record forks stock truth; the first reconciliation report finds them disagreeing |
| recurring billing to be built | reuse `Subscription` / `Subscription Plan` | it already ships with plans, periods, next-billing dates and proration |
| `project_task`, `barcode` | `Task`, `item_barcode` | those are the real DocType names; wrong names in a spec become failed fixtures at import |
| Installation under maintenance | `selling` | verified from source |
| 24 workspaces | 11 views for release 1 | a workspace is a menu; menus over unpopulated records are decoration |
| 32-week / 8-phase roadmap | unchanged in shape, but phase 1 is this package | the roadmap is a staffing plan, not a design |

## Not in scope

Frappe app code · DocType JSON files · bench or WSL2 installation · an ERPNext runtime · the six-app split as an implementation · data migration execution · UAT facilitation.

## Approval

Approving this package means agreeing to: the `03` §2 verdicts, the `10` field inventory as the naming authority, the `31` enforcement layers as the answer to "no duplicate active IMEI", the `40`/`60` automation boundary, and the `41` role model. It does **not** answer `70`'s questions — those need BARO's finance, legal, technical and management input, and the seven blocking ones gate the start of the build.

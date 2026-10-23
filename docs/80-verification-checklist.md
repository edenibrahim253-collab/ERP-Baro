# 80 — Verification Checklist and Results

A documents-only deliverable cannot be tested, so it must be **checked**. This document records the plan's eight structural checks, implemented as ten automated ones (C1–C10), how each was executed, what it found, and what remains genuinely open. It is written so a reviewer can re-run the whole verification without trusting any number here.

**Re-run:** `bash docs/appendix/consistency-checks.sh` from the package root. It prints one line per check and exits with the number of failures, so it can gate a docs commit. Mermaid rendering (§8) is the one check the script cannot do on this machine.

As of this writing: **10 checks, 0 failures, 2 recorded warnings, 1 residual manual task.**

---

## 1. What was verified and how

| # | Check | Method | Result |
|---|---|---|---|
| C1 | Field-name coverage — every `baro_*` identifier used anywhere is defined in `10` | extract all identifiers from the package, diff against `10`; this document is excluded by design because it quotes superseded names as findings | **pass.** 173 field rows in `10`; 15 Custom Fields confirmed by counting Section B's rows |
| C2 | Cross-document reference integrity — every `NN` §M citation resolves to a real heading | extract all such references package-wide and match each against the target file's headings; the run prints the count (124 at last execution) rather than this table hard-coding it | **pass** (after fixing three, §2) |
| C3 | Naming-series uniformity | collect every `BARO-*-.####` literal, assert each is declared in `10` | **pass** — 7 series (`VEH`, `ASSIGN`, `SIM`, `RMA`, `FW`, `INTLOG`, `RECON`); `Baro Platform Mapping` and `Baro GPS Platform` intentionally use `format:`/`field:` autoname instead (`30` §3) |
| C4 | Job-name equality between `30` §11 (deployment) and `60` §3 (behaviour) | set diff | **pass** — 11 identical job names, no drift |
| C5 | Role references resolve to the `41` §1 inventory | match every cited `BARO <Role>` against the 14 defined roles | **pass** — 14 roles, no orphan citation |
| C6 | State closure — every status value compared in prose is a declared enum value | diff `baro_*status = X` occurrences against `10` §6's enums | **pass** |
| C7 | Markdown structure | balanced code fences across all 20 files | **pass** |
| C8 | Convention lint | forbidden blueprint misnames appear only in correction context; no rejected parallel DocType reappears as new | **pass with warning** — `project_task` appears 3× and each is explicitly a correction (`03` §6, `README`, `appendix` §3 row 10) |
| C9 | DocType inventory | count `10` §4's DocTypes against `03` §2's claim | **pass** — 9 business DocTypes + 1 Single |
| C10 | Trigger-id resolution | every `Tn` cited outside `60` exists as a row in `60` §1 | **pass** — 14 triggers; notification names use the zero-padded form (`T03`) by the rule stated in `60` §4 |

**The checker had its own defects.** The first full run reported three failures that were the harness's fault, not the package's, and they are fixed in `appendix/consistency-checks.sh`: C5 word-split unquoted role names on spaces, so every multi-word role failed its own backtick match; C1 flagged the superseded names this document quotes as findings, so doc 80 is now excluded from the *use* side of the diff while remaining the defect log; C10 read the padded notification titles (`T03`) as unknown trigger ids and now normalises the padding. A green harness is only meaningful if its bugs are admitted — a check that cannot fail is not a check.

---

## 2. Defects found by verification and fixed in the same pass

These are recorded rather than silently corrected, because a design package that hides its own mistakes is not reviewable.

| # | Defect | Where | Fix |
|---|---|---|---|
| D-1 | `Baro Reconciliation Exception` was referenced by `40` §8 and `50` §5/§10 but did not exist in the schema | forward reference to an unwritten document | added as `10` §4.10, `03` row 26, `11` §2 entity + R-16 + label map, `30` §2/§6, `41` §2/§3/§5.4 — then the count claim in `03` §2 moved from eight to nine business DocTypes |
| D-2 | Two config fields were cited by `51` (§2 row cap, §4.4 escalation threshold) but absent from `Baro Operations Settings` | `10` §4.9 | added `baro_max_rows_per_run`, `baro_count_alert_threshold` |
| D-3 | `21` §7 cited `baro_retention_days`; the real field is `baro_log_retention_days` on the Settings Single | `21` §7 | corrected with the owning DocType named inline |
| D-4 | `70` Q7 invented a `baro_provider` Link to a provider master; the SIM provider is the standard `Supplier` link | `70` §2 | rewritten to name the actual model (`21` §3) — the answer to Q7 changes supplier data, not schema |
| D-5 | `01` still carried pre-revision statements: "7 new DocTypes", app named `Baro Core`, secrets in "`Baro Platform Settings` as a Single" | `01` §3 mermaid, §3 layer table, §6 | corrected to `baro_core`, 9 + 1, and `Baro GPS Platform` with `Password` fields |
| D-6 | `30` §11 listed a `rebuild_reconciliation_snapshot` job and described `sync_platform_fleet` as performing the diff — contradicting `51` §1/§2, where reconciliation is its own locked run | `30` §11 | renamed to `run_platform_reconciliation`, sync job restricted to mapping/last-comm upsert, and the four missing flag jobs added so C4 could pass |
| D-7 | `30` §11's `sync_platform_fleet` row and `60` §3 disagreed about whether the poller reconciles | both | `60` §3's job table is now the single list; C4 asserts equality |
| D-8 | Fixture filters would have exported nothing: `Custom Field` filtered on `name like "baro-%"` (its name is `<dt>-<fieldname>`) and `Property Setter` filtered on a `dt`-style name match (its column is `doc_type`, and its name is a hash) | `30` §8 | filters rewritten to `fieldname like baro_%` and `doc_type in [...]`; tagged `[verify-vs-framework]` because both are Frappe columns and the framework is not in the inspected archive (`appendix` §1) |
| D-9 | `51` §6.1 originally put the bucket inside `baro_match_key`, which would have made the event-driven `Mapping missing` and the run-driven `Platform-only` two open rows for one device | `51` §6.1 | key now carries a *check id*, with the documented `unmapped` collapse rule; `10` §4.10's field note updated to match |
| D-10 | `40` §3's device state machine used bare identifiers (`InStock`, `RMA`) so the rendered diagram would not show the actual option values, and `RMA` is not a valid bare Mermaid identifier for the enum `In-Stock` | `40` §3 | added `state "In-Stock" as InStock` / `state "RMA" as RmaState` aliases so the diagram labels equal `10` §6's strings |
| D-11 | `51` used `In Progress` in prose and `InProgress` in its state diagram | `51` §7 | alias declaration added; prose normalised to the enum spelling |
| D-12 | `20` §7 listed a "Fleet Reconciliation" report while `51` §10 defined three surfaces | `20` §7, `30` §12 | views table extended to 11 and `30` §12's stale count ("seven views") corrected |
| D-13 | `41` §5.3's report list omitted the two new reports and their restricted audiences | `41` §5.3 | added `BARO - Fleet Reconciliation`, `BARO - Revenue Assurance` (explicitly *not* Report Viewer/Support), and the inbox view |
| D-14 | `50` §12's test row cited `51` §5 for the diff buckets; the buckets are §4 | `50` §12 | corrected |
| D-15 | `01` §8's reading order omitted `70`, `80`, `90` and the appendix | `01` §8 | table completed |

D-1 through D-9 were schema- or behaviour-visible. D-10 onward are documentation-hygiene catches that the automated checks exist precisely to keep from recurring.

---

## 3. Traceability matrices

### 3.1 Automation traceability (the plan's check 1)

Every trigger in `60` §1 resolves on all three axes:

| Axis | Result |
|---|---|
| DocType defined in `10`/`21`? | 14/14 — the DocTypes touched are `Installation Note`, `Baro Device Assignment`, `Serial No`, `Contract`, `Subscription`, `Sales Invoice`, `Baro SIM Card`, `Baro Vehicle`, `Item`, `Baro Device RMA`, `Baro Reconciliation Exception`, `Issue`, `Task`, plus `Baro GPS Platform` / `Baro Operations Settings` for their config values |
| Guard role present in `41` §1? | 14/14 |
| Mechanism named in `40` §2? | 14/14 — each is one of Workflow / controller Python / Property Setter / scheduler-notify / reuse-standard |
| Blueprint coverage | 12/12 original triggers mapped (`60` §2), 2 added by this design (T8 certificates, T14 event-driven unmapped) |

### 3.2 Field coverage (the plan's check 2)

`10` is the only place a field is defined; C1 enforces that mechanically. The 15 Custom Fields land on exactly six standard DocTypes: `Serial No` (4), `Installation Note` (6), `Customer` (2), `Subscription` (1), `Quality Inspection` (1), `Issue` (1).

### 3.3 Cross-reference integrity

105 distinct `NN` §M citations, all resolving. Two of them point at this document (`80` §3, §6) and one at `51` §12; they were dangling until D-1 and the `Baro Integration Batch` reference correction landed.

### 3.4 Job and trigger equality

C4 compares `30` §11's job table with `60` §3's job table. This check matters operationally: the conventions doc is what an integrator deploys from, and the catalogue is what a reviewer approves. If they diverge, a job ships that nobody approved, or an approved behaviour is never scheduled. **Equal: 11 job names, both directions.**

---

## 4. State-closure results (the plan's check 3)

| Machine | States | Closure |
|---|---|---|
| Device `baro_device_status` | 9 (`In-Stock`…`Disposed`) | every transition in `40` §3's table and `21` §2's hooks uses a declared value; `Reserved` correctly sourced from an open order hint, not a lock (`01` §2.1) |
| Assignment | 5 (`Draft`, `Pending Approval`, `Active`, `Ended`, `Superseded`) | `11` R-04's append-only rule and `31`'s UQ-DRV keys agree on which two states are "live" |
| SIM | 5 | `Expired` is a human act from a flagged list (`21` §3); the job only flags — T7 and `40` §7 concur |
| RMA | 8 | `40` §5's diagram has no `Restocked` state (that was a disposition, caught before this pass) |
| Vehicle | 4 | no workflow on the master; transitions of consequence live on assignment/RMA (`40` §5) |
| Activation | 3 | gates `Installed → Active` in both `40` §3 and `50` §9 |
| Integration log | 5 | `Received`/`Processed`/`Failed`/`Retrying`/`Dead` — `50` §7's retry ladder visits exactly these |
| Exception | 5 | `40` §5 documents that only `Waived` is workflow-gated; `51` §7's state machine renders with the `In Progress` alias |

No orphan states, no unreachable terminals, no value used that `10` §6 does not declare.

---

## 5. Invariant → mechanism map (the plan's check 4)

| Invariant (named in the blueprints) | Where stated | Mechanism that enforces it | Test |
|---|---|---|---|
| Historical start/end timestamps on every assignment | `10` §4.2, `11` R-04 | `from_time`/`to_time` with `to_time` as the only `allow_on_submit` business field; submittable document; amend instead of edit | T-6, T-7, U4 |
| Unique IMEI | `11` R-06 | `unique: 1` on `Serial No.baro_imei` + Luhn/format validation + normalisation before compare | T-1, T-2 |
| Unique ICCID / MSISDN | `11` R-07 | `unique: 1` on `Baro SIM Card` | U-series import |
| Unique plate number | `11` R-08 | `unique: 1` on `Baro Vehicle.baro_plate_no` + `baro_plate_pattern` from Settings | T-2 |
| **No overlapping ACTIVE assignment per device or vehicle** | `11` R-02/R-03/R-05, `31` U-2/U-6 | three layers: `unique: 1`, UQ-DRV NULL-when-inactive keys, Redis lock + `SELECT … FOR UPDATE` range query | **T-3, T-4, T-5** |
| Customer → Vehicles → Assignments → Serial + SIM chain | `11` §1, `03` §2 | required Links + `fetch_from` denormalisation + `validate` cross-check (R-15) | U11 |
| Customer → Contract → Subscription → Invoices chain | `11` §3 | standard ERPNext links, untouched; `baro_service_level` is the only addition | RA-1…RA-3 |
| One platform device id per platform | `11` R-10 | `autoname: format:{baro_platform}-{platform_device_id}` — PK does the work | `50` §12 |
| One integration event processed once | `11` R-11 | `baro_idempotency_key` `unique: 1`, log-first contract | T-11 |
| Derived fields have exactly one writer | `30` §7 | FF/DRV/INT classes + permlevel 1; `frappe.db.set_value` on UQ-DRV keys is prohibited | T-10 + `after_migrate` audit |
| No telemetry in the ERP | `01` §5, `11` §6 | design boundary; `PlatformDevice` reducer contract in `50` §3 | contract-stub test |

The package states plainly in `31` §2 that **validation alone cannot meet the headline criterion** — that sentence is the point a reviewer should push on, and T-4 is the test that settles it.

---

## 6. Acceptance-criteria trace (the plan's check 5)

| Acceptance criterion | Served by | Status |
|---|---|---|
| No duplicate active IMEI assignments | `31` §3–§5 (UQ-DRV + lock + `FOR UPDATE`); `51` §4.5 as the after-the-fact net; T-1/T-3/T-4 | **designed, unproven until a runtime exists** |
| Accurate stock reconciliation | standard `Serial No`/`Stock Entry`/stock reports (`03` rows 2–5, `20` A2); `51` §4.1/§4.2 keep ERP and platform honest | designed |
| Correct recurring invoices | reuse of `Subscription`/`Subscription Plan` (`03` row 15, `60` T4); revenue-assurance checks RA-1…RA-6 (`51` §5) | designed; Q1/Q3/Q5 gate the numbers |
| Documented synchronisation error handling | `50` §4–§8 (idempotency, retry ladder, dead letters, rate limits) + `51` §8 (platform-down circuit breaker) | complete |
| Successful recovery from backup | **not covered by this package** — an ops deliverable, listed as a residual in §8 | open, assigned |
| UAT surface | `20` §9's 15 scenarios (U1–U15) + `31` §8's 13 tests (T-1…T-13) + `50` §12's 10 integration tests + `41` §10's 7 permission tests | 45 named checks, all mapping to a criterion above |

---

## 7. Open placeholders (`70` §5's promise)

The plan's check 6 — source spot-checks against the archive — is executed in `appendix/spot-check-paths.md` §3, not here; its residue is the debt row below.

A reviewer should be able to see which parts of the design are provisional. Active placeholders:

| Placeholder | Awaiting | Effect when answered |
|---|---|---|
| `[verify-vs-v16]` debt — the authoritative list is `04` §4, with the re-verification queue in `appendix` §5; the tag also appears inline in `01` §2, `02` §6, `03` §intro, `10` §2, `31` §5.2, `51` §1 | a real v16 bench | re-check field lists; every version-sensitive claim is one grep away (`appendix` §2's commands) |
| `Baro Subscription Asset` deferred | Q4 | new DocType, or one Custom Field — nothing else moves |
| `Baro Fleet Group` deferred | Q6 | master data promotion, additive |
| Compliance DocTypes deferred | Q1 | new module, `21`-style field tables to be written |
| `baro_expiry_notice_days`, `baro_cert_notice_days`, `baro_inactive_threshold_hours`, `baro_reorder_notice_role`, `baro_count_alert_threshold`, `baro_max_rows_per_run`, `baro_plate_pattern`, `baro_msisdn_pattern` | Q3, Q14 | values in Settings; no design change |
| Vendor enum maps in `50` §8 | Q2 | adapter + mapping rows only |
| Ethiopian print/tax behaviour | Q1 | print formats and tax templates, outside the spine |
| `Assignment Rule` fixtures marked "later phase" in `30` §8 | dispatch/SLA phase | fixture added, filter already written |
| Backup/restore procedure | Q11 | separate ops document, §8 residual |

Blocking questions remain **unanswered by design** (`70` §1): the package proposes no defaults for tax, dunning, suspension authority, hosting, or the subscription bundling model.

---

## 8. Residual items this environment cannot close

| Item | Why | Handover |
|---|---|---|
| **Mermaid render validation** | 12 blocks (3 `erDiagram`, 3 `flowchart`, 5 `stateDiagram-v2`, 1 `sequenceDiagram`) are balanced and syntactically written to the current Mermaid grammar, but no renderer could be executed here: no Java for PlantUML, no Python, and Node 16.20.2 is too old for the current Mermaid CLI. Fences and diagram types are checked (C7); glyphs are not | open each file in a Mermaid-capable preview (GitHub, VS Code, Obsidian) and confirm 12 diagrams render. A single bad `erDiagram` attribute line would show here and nowhere else |
| Re-execution of the source spot-checks | the archive is the *only* ERPNext artefact available and it is post-v16 | `appendix` §2 gives the commands; run them against v16 once a bench exists |
| Any runtime proof of `31` | T-4 (concurrent submit) needs two processes and a database | the test is specified in `31` §8 precisely so it can be run unchanged on WSL2 |
| Permission matrix proof | `41` §10's 7 tests need a logged-in site | same |
| Backup/restore | ops scope | assign with Q11 |

**Do not read this document as "verified therefore buildable."** It records that the package is internally consistent and traceable to the source. Consistency is a necessary condition for the design to be right, not a sufficient one — the two things that can still sink it are a `[verify-vs-v16]` surprise (`04` §4) and an unanswered blocking question (`70` §1).

---

## 9. Convention lint results (the plan's check 7)

| Rule | Result |
|---|---|
| Single field prefix `baro_` | **pass** — C1 finds no competing prefix; `barc_`/`bg_`/`x_` variants appear nowhere |
| Uniform `BARO-*-.####` series | **pass** — 7 series, all declared in `10`; two DocTypes intentionally use `format:`/`field:` autoname for composite-key reasons (`30` §3) |
| DocType names spelled consistently | **pass** — 15 name variants in use, all matching `10` §4; `Baro Platform Settings` (a name this design abandoned mid-package) no longer appears |
| No blueprint misnames live | **warning** — `project_task` appears 3× in correction context only |
| No duplicated `Serial No` | **pass** — `C8` asserts no `BARO Device`/`BARO Installation`/`BARO Service Inspection` is proposed as new; `03` §3 and §6 keep the rejection documented |
| Error messages quoted exactly | `21`'s hook maps name the message text; those strings are the ones `31` §8's tests assert on |
| Secrets never in fixtures, never in `Data` fields | `30` §8 rule 1, `10` §4.8 `Password` types; no fixture filter touches a Password field |
| Every RO/DRV/INT field names its writer | **pass** — `10`'s flag column carries the authority for each, and `30` §7 defines the classes |

---

## 10. How to review this package in one sitting

1. `03` §2 — nine build verdicts, one page. Agree or reject here first; everything else is downstream.
2. `31` §3 and §5 — the mechanism behind "no duplicate active IMEI". Read the six race scenarios in `31` §2 before believing the `unique: 1` claim.
3. `40` §1 + `60` §7 — the automation boundary. This is where BARO's own written invariant is either honoured or quietly eroded, so check that no row in `60` §1 submits anything.
4. `41` §2–§5 — permissions as enforcement, not menu-hiding.
5. `70` §1 — the seven blocking questions. Then decide who owes each answer and by when.
6. This document §2 — the fifteen defects, to judge whether the package was checked or merely written.

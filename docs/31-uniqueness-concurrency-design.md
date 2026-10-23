# 31 — Uniqueness and Concurrency Design

This document carries BARO's two hardest acceptance criteria: **"no duplicate active IMEI assignments"** and **accurate, non-overlapping assignment history**. Everything here is stated as a mechanism, because a rule enforced only in application code is a rule that fails under load.

## 1. What must be unique, and at what level

| # | Invariant | Scope | Layer | Mechanism |
|---|---|---|---|---|
| U-1 | One device unit | global | DB PK | `Serial No.name` (standard) |
| U-2 | One IMEI per device | global | **DB unique index** | `Serial No.baro_imei` with `unique: 1` |
| U-3 | One ICCID, one MSISDN per SIM | global | DB unique index | `Baro SIM Card.baro_iccid`, `.baro_msisdn` |
| U-4 | One plate per vehicle | global | DB unique index | `Baro Vehicle.baro_plate_no` (normalised before compare) |
| U-5 | One VIN where recorded | global | DB unique index (NULL-tolerant) | `Baro Vehicle.baro_vin` |
| U-6 | **At most one Active assignment per device** | live state | DB unique index on a derived key | `Baro Device Assignment.baro_active_serial_key` (**UQ-DRV**) |
| U-7 | **At most one Active assignment per vehicle** | live state | DB unique index on a derived key | `baro_active_vehicle_key` (**UQ-DRV**) |
| U-8 | No two assignment **time windows** overlap for the same device or vehicle | temporal | app check + row lock | `before_submit` under named lock + `SELECT … FOR UPDATE` |
| U-9 | One platform device id per platform | composite | DB primary key | `autoname: format:{baro_platform}-{platform_device_id}` |
| U-10 | One integration event processed once | global | DB unique index | `Baro Integration Log.baro_idempotency_key` |
| U-11 | One current mapping/firmware/derived pointer | derived | single writer | `30` §7 DRV/INT discipline |

U-2…U-5, U-9 and U-10 are **outright** uniqueness: the value is always unique, so a plain unique index expresses it fully.
U-6 and U-7 are **conditional** uniqueness ("unique *while active*") — the interesting half of the problem.
U-8 is **range** uniqueness — no index can express it, so it needs the lock+check.

## 2. Why validation alone is not enough

A `validate()` duplicate check reads, decides, and writes. Between the read and the commit, another transaction can insert the same value. The window is milliseconds, and BARO's realistic trigger set makes it routine rather than exotic:

| Scenario | Frequency | Naive check outcome |
|---|---|---|
| Two warehouse staff register the same batch of devices on two laptops | daily | both pass, duplicate IMEI stored |
| CSV import of 1,000 historical assignments alongside live installs | every migration | interleaved duplicates |
| Field technician on mobile submits an install while the office amends the same vehicle | daily | both pass |
| Connector replays a webhook while a human assigns the same device | common (retries are normal) | double assignment |
| Browser double-click on Save/Submit | constant | two documents |
| Two workers (`bench --site x retry` + scheduler) claim the same log row | occasional | double side effect |

So the design is: **the database enforces what it can express; the application enforces what it cannot, under a lock.**

## 3. Layer 1 — outright uniqueness (`unique: 1`)

Frappe supports a field-level unique index. Precedent in the shipped ERPNext tree: `Employee.attendance_device_id`, `Item.item_code`, `Supplier.alias`, `Customer.alias`. `attendance_device_id` is the exact analogue of BARO's case — an externally-assigned hardware identifier constrained unique on a master record — which is the argument to use when someone proposes inventing a new mechanism.

Implementation notes:
- Apply via DocType JSON for BARO DocTypes; apply as a **Custom Field with `unique: 1`** for `Serial No.baro_imei`.
- Normalise **before** the index compares: `validate` uppercases and strips separators for plate, ICCID, MSISDN and IMEI. A unique index on un-normalised text guarantees nothing.
- NULL semantics: MariaDB permits unlimited NULLs in a unique index, so optional-but-unique fields (VIN) work without special handling; empty string does **not** — an empty string is a value and collides. Therefore "not provided" must be stored as NULL, never `""`. In Frappe that means `self.baro_vin = None` (not `""`) when clearing.
- Duplicate-on-import: Data Import runs validations, and the unique index raises `DuplicateEntryError`; the import must map that to the row number so the operator knows which line failed.

## 4. Layer 2 — conditional uniqueness (UQ-DRV), the core trick

MariaDB has no filtered/partial unique index, and Frappe exposes no "unique where" option. The pattern:

> Add a Python-maintained column whose value is **the constrained key while the row is active, and NULL otherwise**, and put a plain unique index on it.

Because NULLs are unconstrained, all inactive rows coexist; all active rows are forced apart.

### 4.1 The fields

| Field | Value when `baro_status = Active` and `docstatus = 1` | Value otherwise | Index |
|---|---|---|---|
| `baro_active_serial_key` | `serial_no` | `NULL` | `unique: 1` |
| `baro_active_vehicle_key` | `baro_vehicle` | `NULL` | `unique: 1` |

Both are `read_only`, hidden from lists and print formats — they are index machinery.

### 4.2 Maintenance rule (single source of truth)

```python
def set_active_keys(doc):
    live = doc.docstatus == 1 and doc.baro_status == "Active"
    doc.baro_active_serial_key  = doc.serial_no   if live else None
    doc.baro_active_vehicle_key = doc.baro_vehicle if live else None
```

Called from **every** path that can change liveness — this is the discipline that makes the trick safe:

| Path | Call site |
|---|---|
| New draft / edit | `validate` (computes NULL; harmless before submit) |
| Submit + approval to Active | `before_submit` / workflow action handler, then the index guards the race |
| `to_time` set / status → Ended or Superseded | `on_update_after_submit` → keys become NULL |
| Cancel | `on_cancel` → keys NULL (and `on_cancel` is only legal pre-activation, `21` §2) |
| Amend | the new document starts with NULL keys until it is itself approved Active |
| Data Import | import runs `validate` + submit hooks; UQ-DRV enforcement is identical (U10) |
| Connector/API | must call the same controller method — no direct `db_set` on these columns |

A **hard rule**: no code may write these columns with `frappe.db.set_value`. They are derived, and a bypass turns the unique index into a false guarantee. `after_migrate` runs an integrity audit (§7.3) to catch drift.

### 4.3 Alternative rejected: generated column

`ALTER TABLE … ADD COLUMN active_serial VARCHAR GENERATED ALWAYS AS (IF(status='Active', serial_no, NULL)) STORED, ADD UNIQUE(active_serial)` is attractive because the database, not Python, maintains it. Rejected as the primary mechanism because:
1. Frappe's schema sync owns that table's columns; an unmanaged column is a documented risk on `bench migrate` and on DocType JSON edits.
2. It couples to the exact spelling of `baro_status`, so a state rename silently breaks uniqueness.
3. Liveness is not one boolean: it is `docstatus = 1 AND baro_status = 'Active' AND (to_time IS NULL OR to_time > NOW())`. A generated expression encoding that is unmaintainable and version-specific.

It remains the **fallback** if §8 tests ever show Python maintenance of the key drifting in production, applied through a patch with a migrate-survival test.

## 5. Layer 3 — temporal overlap (U-8), the check no index can do

UQ-DRV proves only one assignment is *currently* Active. It cannot prove that a back-dated historical range does not overlap another range. That needs a query, and the query needs serialisation:

```python
def before_submit(self):
    with self.active_locks():                       # Redis named locks (see 5.2)
        self.lock_source_rows()                     # SELECT ... FOR UPDATE
        self.assert_no_overlap()                    # range query
        set_active_keys(self)                       # then let the index have the last word

def assert_no_overlap(self):
    for key_field, value in (("serial_no", self.serial_no), ("baro_vehicle", self.baro_vehicle)):
        rows = frappe.db.sql("""
            select name, from_time, to_time
            from `tabBaro Device Assignment`
            where {kf} = %s
              and docstatus = 1
              and baro_status in ('Active', 'Ended', 'Superseded')
              and name != %s
              and (to_time is null or to_time > %s)
              and from_time < coalesce(%s, '2999-12-31')
            for update""".format(kf=key_field),
            (value, self.name or "", self.from_time, self.to_time or self.from_time), as_dict=1)
        if rows:
            frappe.throw(_("{0} {1} already has assignment {2} covering this period").format(
                label_for(key_field), value, rows[0].name),
                frappe.DuplicateEntryError)
```

Design decisions worth defending:

| Decision | Reason |
|---|---|
| Ended/Superseded rows **are** checked for overlap | History is the audit trail; a back-dated install must not silently collide with a previous unit's period |
| Draft (`docstatus = 0`) rows are **not** checked | Drafts are intentions; blocking them makes parallel work impossible. The check fires at submit |
| `for update` inside the same transaction as the insert | Without it, two readers both see "no overlap" and both write |
| Lock *before* check, not after | Locking after the check is the bug this design exists to prevent |
| Error type `DuplicateEntryError` | Gives a retryable, machine-distinguishable failure for the API/import/connector paths |

### 5.2 Locking

```python
@contextmanager
def active_locks(self):
    keys = [f"baro:assign:serial:{self.serial_no}", f"baro:assign:vehicle:{self.baro_vehicle}"]
    with frappe.cache().lock("baro:assign", expiry=30):   # coarse lock first
        for k in keys:
            handle = frappe.cache().lock(k, expiry=30)
            handle.acquire()
        try: yield
        finally: release in reverse order
```

Rules: one coarse namespace lock plus one lock per contested key; every lock has an expiry so a crashed worker cannot deadlock assignments forever; locks are acquired in a deterministic order (sorted key names) to avoid deadlock; the retry poller for the integration log uses the same lock namespace so a webhook replay and a human submit cannot interleave.

`frappe.cache().lock()` availability across frappe versions is a `[verify-vs-v16]` item (`04` §4). If the pinned version lacks it, fall back to `frappe.db.sql("SELECT GET_LOCK(%s, %s)")`, which MariaDB supports natively — and record the substitution here rather than discovering it during a fire drill.

## 6. Race analysis

| Interleaving | Outcome with only `validate` | Outcome with this design |
|---|---|---|
| A and B both read "no active assignment", both submit for the same serial | both succeed → two active rows (criterion broken) | A commits and takes the UQ-DRV slot; B hits the unique index → `DuplicateEntryError`, or blocks on the Redis lock and then fails the range check |
| A submits Active; B back-dates an Ended historical range that overlaps | both succeed | B's `before_submit` range query sees A's committed window → rejected with the assignment name |
| Connector replays a webhook for an install a technician just submitted | second side effect applied | `baro_idempotency_key` unique → replay returns the stored result (`50` §4); no new document |
| Import runs while live users submit | silent duplicates | import rows go through the same controller hooks; failures are reported per row |
| Worker 1 and worker 2 both pick the same `Retrying` log row | double outbound call | retry poller claims the row under a lock and bumps `baro_attempt_count` conditionally |
| User double-clicks Submit | two documents or two effects | first wins; second sees the workflow state already transitioned (`40` §4 idempotent transitions) |

## 7. Migration and integrity mechanics

### 7.1 Adding the indexes (patch, ordered)

```
patches = [
  "baro_core.patches.v1_create_baro_doctypes",
  "baro_core.patches.v1_add_unique_custom_fields",          # Serial No.baro_imei etc.
  "baro_core.patches.v1_add_active_key_columns_and_indexes", # UQ-DRV
  "baro_core.patches.v1_backfill_active_keys_from_history",
  "baro_core.patches.v1_audit_derived_pointers",
]
```

`v1_add_active_key_columns_and_indexes` does, in order: add the two columns → backfill from existing submitted+Active rows → **pre-flight duplicate scan** → create the unique indexes. Index creation is deliberately last so the failure mode is a readable report, not an opaque `bench migrate` crash.

### 7.2 Pre-flight: what if existing data already violates the rule

Realistic in a first migration from spreadsheets. The patch must not "fix" data silently:

```sql
select serial_no, count(*) c
from `tabBaro Device Assignment`
where docstatus = 1 and baro_status = 'Active'
group by serial_no having c > 1;
```

If any row returns, the patch **stops with a report**: the offending vehicles/devices are listed, an exception is created for the Reconciliation Center, and a human ends or supersedes the duplicates. Auto-ending would erase billing-affecting history — the same principle that keeps schedulers from making financial changes (`01` §6).

### 7.3 Post-migrate integrity audit (`after_migrate` hook)

Three cheap queries, run on every migrate, logged as a warning and surfaced in the Admin workspace:

1. Rows where the key columns disagree with `docstatus`/`baro_status` (drift from a bad bypass).
2. Submitted Active assignments whose `to_time` is in the past (should have been ended).
3. Active assignments referencing a device whose `Serial No.status` says it is still in a stock warehouse (fork between BARO state and stock truth).

## 8. Test plan (this is where the criteria are actually proven)

| Test | Method | Expect |
|---|---|---|
| T-1 duplicate IMEI | two `Serial No` saves | second raises duplicate, message names the first serial |
| T-2 normalisation bypass | `412-ABC` vs `412ABC` plate | blocked — proves the index sees the normalised value |
| T-3 one active per device | submit A, submit B same device | B blocked by UQ-DRV |
| T-4 **concurrent** submit | two threads/processes, same device, `bench execute` script, no sleep | exactly one committed active row; the other raises a retryable error |
| T-5 historical overlap | submit back-dated Ended assignment over an existing window | blocked with the conflicting document name |
| T-6 end then reassign | A → Ended, B → Active | allowed; history contiguous, no overlap |
| T-7 amend path | amend an Active assignment to overlap | blocked at re-submit |
| T-8 cancel path | cancel before activation; cancel after activation | first allowed, second refused with the "amend instead" message |
| T-9 import | 1,000-row CSV with 3 deliberate violations | 997 imported, 3 reported by row number, zero index crashes |
| T-10 key drift | `frappe.db.set_value` a key to NULL behind the model, run audit | §7.3 check 1 reports it (proves the audit works, and documents why direct writes are banned) |
| T-11 webhook replay | same idempotency key twice | one effect; second returns the stored result |
| T-12 patch pre-flight | seed a duplicate active pair, run migrate | patch stops with a readable report, no data destroyed |
| T-13 failover | kill the worker holding a lock mid-submit | lock expires; a later submit is not permanently blocked |

T-4 and T-9 are the two reviewers should insist on running themselves: they are where "no duplicate active IMEI" is either true or a slide.

## 9. Failure modes and user experience

| Failure | What the user sees | Required response |
|---|---|---|
| Unique index hit | `IMEI 3569… is already registered on serial SN-00231` | never a raw traceback — map `DuplicateEntryError` per field to a named message |
| Overlap | `Device … already assigned to plate AAA1234 from 2026-09-01` | names the document, links it |
| Lock busy (two people, same device) | `This device is being edited right now. Try again in a few seconds.` | retryable; distinguish from a real conflict so the UI does not alarm |
| Migration pre-flight block | A report listing duplicate active pairs | human resolution, never auto-ending |
| Connector replay | silent no-op returning prior result | visible in the Integration Log as `Processed (replay)` |

## 10. Rejected alternatives

| Alternative | Why rejected |
|---|---|
| `validate`-only checks | The exact failure BARO's acceptance criterion forbids (§2) |
| IMEI/plate as document `name` | External identifiers get re-issued; renaming a `name` rewrites every link and breaks history |
| MySQL `CHECK` constraints | Cannot express cross-row conditions; Frappe's schema sync does not manage them |
| DB triggers | Invisible in the app, unsupported by Frappe's migration model, hostile to review and testing |
| Redis-only "reservation" without a DB constraint | Redis is not the system of record; a flush or failover erases the guarantee |
| Single-parent design (device under vehicle, no assignment record) | Destroys history, cannot express replacement or transfers, and would force the fleet register to fork device identity (`03` §3) |
| Generated columns as primary (§4.3) | Frappe-managed schema coupling; kept as a documented fallback |

## 11. Traceability

| Blueprint requirement | Where satisfied |
|---|---|
| "Unique identifiers should be enforced in the database" | §3, §4 (index-level, not app-level) |
| "Additional validation preventing overlapping active assignments" | §5 |
| "Each assignment must retain historical start/end timestamps" | `Baro Device Assignment.from_time/to_time`, `30` §6 (`allow_on_submit` on `to_time`), report `BARO - Assignment History` |
| Acceptance: "no duplicate active IMEI assignments" | U-2, U-6, tests T-1, T-3, T-4 |
| Acceptance: "accurate stock reconciliation" | §7.3 audit check 3 + `03` A2/A5 reuse of stock records |
| Acceptance: "documented synchronization error handling" | `50` §4–7, `Baro Integration Log` |

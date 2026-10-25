# BARO Core (`baro_core`)

The Frappe app that implements the BARO ERP 360° **asset spine**: vehicles, GPS devices, SIMs,
device assignments, installations, RMA, and the GPS platform integration boundary.

The design package it is built from lives in `../docs/` — `10-data-dictionary.md` is the field
authority, `31-uniqueness-concurrency-design.md` carries the acceptance criteria,
`40-workflows-approvals.md` the automation boundary, `50`/`51` the integration contracts.
Read those before changing controllers.

## The rule this app is written around

> An automated job may **detect, flag, notify and create draft work**. It may not **submit,
> cancel, suspend, reprice or terminate** anything.

`jobs.py` and `integrations/*` obey it literally: scheduler entrypoints write flags, Notification
Log rows, digest emails, draft `Issue`/`Task` records and `Baro Reconciliation Exception` rows.
Every state change that affects a customer's service or a ledger amount is a Workflow transition
executed by a named human. A code review that finds a `.submit()`, `.cancel()` or a billing write
under `jobs.py` or `integrations/` has found a defect.

## Layout

```
baro_core/
  baro_core/
    hooks.py                 doc_events, scheduler, fixtures, permission query conditions
    api.py                   whitelisted endpoints (scan resolve, device 360, inbound webhook)
    jobs.py                  scheduler entrypoints (docs/60 trigger catalog)
    derive.py                derived pointers + UQ-DRV key computation (the only writer of those columns)
    locks.py                 named Redis locks with GET_LOCK fallback
    settings.py              typed access to Baro Operations Settings - no threshold literals in code
    permissions.py           permission_query_conditions / has_permission per docs/41 §5
    baro_fleet/              Baro Vehicle
    baro_devices/            Baro Device RMA, Baro Firmware History, Serial No/Quality Inspection handlers
    baro_connectivity/       Baro SIM Card
    baro_field_service/      Baro Device Assignment (+ Installation Note handlers) - the core invariant carrier
    baro_integrations/       Platform Mapping, Integration Log, Reconciliation Exception
    baro_settings/           Baro GPS Platform, Baro Operations Settings
    baro_billing/            reserved: Subscription/service-level glue (docs/90 phase 2)
    integrations/            base adapter contract, webhook, sync, retry ladder, ratelimit, payload store,
                             reconciliation, vendor_template.py (copy per platform)
    fixtures/                role / custom_field / property_setter / workflow / workspace / report
                             (+ notification / print_format / baro_operations_settings as empty
                             placeholders - see "After install")
    patches/v1/              unique indexes, UQ-DRV columns + backfill, integrity audit
    tests/                   unittest-style Frappe tests
```

## Install

```bash
bench --site <site> install-app baro_core
bench --site <site> migrate          # re-applies the UQ-DRV indexes via after_migrate
```

`bench migrate` runs DocType sync → patches → fixtures. The UQ-DRV generated columns and their
unique indexes are created by `patches/v1/*`, which **refuse to create an index over duplicates**
and abort with a readable report instead of silently ending active assignments
(`docs/31` §7.2 pre-flight).

## After install, before go-live

1. **Baro Operations Settings** — set the plate and MSISDN regexes and pick the GPS device Item
   Groups. The current values are permissive placeholders: the Ethiopian plate format is an open
   stakeholder question (`docs/70` Q3/Q14) and stays configuration, never code.
2. **Baro GPS Platform** — one row per vendor, credentials at permlevel 2 (System Manager only),
   `baro_adapter_module` pointing at a copy of `integrations/vendor_template.py`.
3. **User Permissions** — branch/warehouse/customer scopes; `BARO Integrator` is a desk-less bot
   and holds no submit right on any business document (`docs/41` §7.2, enforced in `install.py`).
4. **Regenerate fixtures** — `bench export-fixtures`, then review the diff.
   `notification.json`, `print_format.json` and `baro_operations_settings.json` ship empty:
   - the Single cannot be exported before someone fills it, and its `baro_device_item_groups`
     must reference Item Groups that exist on the target site, so a fixture value would be a
     lie on every other site;
   - Notification/Print Format records are authored on the staging site. Their DocType belongs to
     the Frappe framework, which is **not** in the reference archive this build was checked
     against (`docs/appendix/spot-check-paths.md`), so shipping guessed field names would be
     worse than shipping none. The eight notification trigger points of `docs/40` §8 are
     implemented in code (`jobs.py`) in the meantime.

## Tests

```bash
bench --site test_site run-tests --app baro_core
```

`tests/test_uniqueness.py` is the one that matters: it asserts the headline acceptance criterion
— two live assignments on one device, one vehicle, or one plate cannot exist, including through
the Data Import path and a concurrent `before_submit`. The modules were written on a machine with
no Python runtime, so the first `bench run-tests` on WSL2 is the real check; expect to fix imports
before logic.

## Unverified against v16

Every `frappe/*` interaction and this list are tagged `[verify-vs-v16]` in the source. The
reference archive was post-v16 (frappe ≥17-dev, Python ≥3.14) and contained the ERPNext app only.

- `frappe.cache().lock()` / `get_value` / `set_value(expires_in_sec=…)` shapes
- `frappe.db.get_singles_dict`, fixture import order for Single doctypes
- `Search Index` / `barman`-era search behaviour on `search_index: 1`
- generated-column (`VIRTUAL` vs `STORED`) support in the MariaDB version bench installs

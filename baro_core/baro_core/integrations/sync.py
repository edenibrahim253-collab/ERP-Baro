# Copyright (c) 2026 BARO Group
# License: MIT. See license.txt
"""Outbound pull dispatch (`50` §5, `51` §1).

A pull run is deliberately boring. It asks the platform for its current view of the devices ERP
already maps, copies three fields onto those mappings (platform status, last communication, sync
state), refreshes the derived `Serial No.baro_last_comm_at`, and stops. It does **not**:

* create `Serial No` rows - a bot minting inventory records is exactly what `41` §5.4 forbids;
* create or delete `Baro Platform Mapping` rows - a mapping is a human decision about which
  device belongs to which platform;
* raise reconciliation exceptions - the diff belongs to `run_platform_reconciliation`, and doing
  it here too would mean two schedulers disagreeing about the truth (`51` §1);
* touch assignment, billing, or device status.

Per-platform cadence lives on `Baro GPS Platform.baro_pull_interval` and is compared against this
platform's last completed pull log, so one 15-minute cron entry can serve platforms on 15-minute,
hourly, or daily intervals without a cron entry per platform.
"""

import frappe
from frappe.utils import add_to_date, get_datetime, now_datetime

from baro_core import locks
from baro_core.integrations import base
from baro_core.integrations.ratelimit import consume_for_platform

SYNCED = "Synced"
LOG_DONE = "Processed"
ENDPOINT = "fleet/list"

STATUS_MAP = {
	"online": "Online",
	"offline": "Offline",
	"moved": "Moved",
	"stolen": "Stolen",
	"maintenance": "Maintenance",
}


def pull_enabled_platforms() -> list[dict]:
	"""One entry per enabled platform that is due. A platform failure never stops the others."""
	results = []
	for platform in frappe.get_all("Baro GPS Platform", filters={"baro_enabled": 1}, pluck="name", order_by="asc"):
		with locks.acquired([locks.platform_lock(platform)]):
			if not due(platform):
				results.append({"platform": platform, "skipped": "not due"})
				continue
			results.append(pull_platform(platform))
	return results


def due(platform: str) -> bool:
	"""Has this platform's own interval elapsed since its last successful pull?"""
	interval = int(frappe.db.get_value("Baro GPS Platform", platform, "baro_pull_interval") or 15)
	last = frappe.db.get_value(
		"Baro Integration Log",
		{"baro_platform": platform, "baro_endpoint": ENDPOINT, "baro_log_status": LOG_DONE},
		"baro_processed_at",
		order_by="baro_processed_at desc",
	)
	if not last:
		return True
	return now_datetime() >= add_to_date(get_datetime(str(last)), minutes=interval)


def pull_platform(platform: str) -> dict:
	"""Fetch the platform's fleet view and copy it onto the mappings that already exist."""
	log = start_log(platform)
	if not consume_for_platform(platform):
		return finish(log, base.RATE_LIMIT, "token budget exhausted for this minute")
	try:
		adapter = base.resolve(platform)
		fleet = adapter.list_fleet()
	except Exception as error:  # noqa: BLE001 - a broken connector is a logged failure, not a crashed scheduler
		return finish(log, base.classify(error), str(error)[:900])
	if not isinstance(fleet, base.AdapterResult):
		# Third-party code at a boundary: a bare return is a contract violation, recorded as one.
		return finish(log, base.PAYLOAD, f"adapter {type(fleet).__name__} did not return AdapterResult")
	if not fleet.ok:
		return finish(log, fleet.error_class, str(fleet.error)[:900])

	summary = apply_fleet_view(platform, fleet.data or [])
	return finish(log, None, summary)


def apply_fleet_view(platform: str, rows: list[dict]) -> dict:
	"""Write platform state onto existing mappings only. Returns counts."""
	from baro_core import derive

	updated, unmapped, serials = 0, 0, set()
	for row in rows:
		mapping = find_mapping(platform, row)
		if not mapping:
			# Silence here is the design: the reconciler owns the diff (`51` §1).
			unmapped += 1
			continue
		frappe.db.set_value(
			"Baro Platform Mapping",
			mapping,
			{
				"baro_platform_status": status_of(row),
				"baro_last_comm_at": comm_at(row),
				"baro_sync_status": SYNCED,
				"baro_last_sync_at": now_datetime(),
			},
			update_modified=False,
		)
		serial_no = frappe.db.get_value("Baro Platform Mapping", mapping, "serial_no")
		if serial_no:
			serials.add(serial_no)
		updated += 1
	for serial_no in serials:
		derive.recompute_last_comm(serial_no)
	return {"updated": updated, "unmapped": unmapped}


def find_mapping(platform: str, row: dict) -> str | None:
	"""Locate the mapping by platform device id, falling back to the IMEI the platform reports."""
	name = frappe.db.get_value(
		"Baro Platform Mapping", {"baro_platform": platform, "platform_device_id": row["platform_device_id"]}, "name"
	)
	if name:
		return name
	imei = str(row.get("imei") or "").strip()
	if imei:
		serial_no = frappe.db.get_value("Serial No", {"baro_imei": imei}, "name")
		if serial_no:
			return frappe.db.get_value("Baro Platform Mapping", {"baro_platform": platform, "serial_no": serial_no}, "name")
	return None


def status_of(row: dict) -> str:
	return STATUS_MAP.get(str(row.get("status") or "").lower(), "Unknown")


def comm_at(row: dict):
	"""The platform's own timestamp when it parses, otherwise this moment. Never a fabricated past."""
	value = row.get("last_comm_at")
	if not value:
		return now_datetime()
	try:
		return get_datetime(str(value)[:19].replace("T", " ").rstrip("Z"))
	except (ValueError, TypeError):
		return now_datetime()


def start_log(platform: str):
	"""Log first, then call: a crash mid-pull still leaves a row a human can retry (`50` §4)."""
	return frappe.get_doc(
		{
			"doctype": "Baro Integration Log",
			"baro_direction": "Outbound",
			"baro_platform": platform,
			"baro_endpoint": ENDPOINT,
			"baro_idempotency_key": f"sync|{platform}|{now_datetime().strftime('%Y%m%d%H%M%S')}",
			"baro_log_status": "Received",
			"baro_max_attempts": int(frappe.db.get_value("Baro GPS Platform", platform, "baro_max_retries") or 5),
			"company": frappe.db.get_value("Baro GPS Platform", platform, "company"),
		}
	).insert(ignore_permissions=True)


def finish(log, error_class: str = None, result=None):
	"""Close the pull log; a failure enters the same ladder an inbound failure uses."""
	from baro_core.integrations.payload import store_payload

	message = result if isinstance(result, str) else None
	if error_class:
		log.baro_log_status = "Failed"
		log.baro_error_class = error_class
		log.baro_error_message = message
		log.baro_processed_at = now_datetime()
		log.save(ignore_permissions=True)
		health(log.baro_platform, ok=False, error=f"{error_class}: {message}")
		from baro_core.integrations.retry import register_failure

		return register_failure(log.name, error_class, message)

	log.baro_log_status = LOG_DONE
	log.baro_processed_at = now_datetime()
	log.baro_error_class = "None"
	log.baro_payload_ref = store_payload(log, result or {})
	log.save(ignore_permissions=True)
	health(log.baro_platform, ok=True)
	return {"platform": log.baro_platform, "status": LOG_DONE, "log": log.name, **(result or {})}


def health(platform: str, ok: bool, error: str = None) -> None:
	"""INT fields, written only through this path (`30` §7). A success clears the error, not the history."""
	values = {"baro_last_error": None if ok else (error or "")[:900]}
	if ok:
		values["baro_last_success_at"] = now_datetime()
	else:
		values["baro_last_failure_at"] = now_datetime()
	frappe.db.set_value("Baro GPS Platform", platform, values, update_modified=False)

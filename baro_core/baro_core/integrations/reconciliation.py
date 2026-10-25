# Copyright (c) 2026 BARO Group
# License: MIT. See license.txt
"""Three-way reconciliation (`51`). ERP view vs platform view, bucketed into exceptions.

The rules that make this safe to run unattended:

* **It writes only `Baro Reconciliation Exception` rows.** No document is edited, no assignment
  is ended, no device is registered - the corrective action is a separate human edit under the
  normal workflow (`41` §5.4).
* **A failed platform read proves nothing.** The run aborts without writing rows. Treating an
  outage as "the platform reports zero devices" would raise a `Platform-only`-shaped storm of
  `ERP-only` exceptions and, worse, make the inbox untrustworthy (circuit breaker, `51` §8).
* **Match keys suppress repeats.** A row is `(identifier | check id)`, so the same unresolved
  mismatch does not create a new exception every hour, and a later run that no longer sees it
  sets `baro_cleared_automatically` - which is a flag, not a status change, because the bot may
  not close its own findings (`51` §7).
"""

import frappe
from frappe.utils import now_datetime, today

from baro_core import settings

ERP_ONLY = "ERP-only"
PLATFORM_ONLY = "Platform-only"
STATE_MISMATCH = "State mismatch"
COUNT_MISMATCH = "Count mismatch"
MAPPING_MISSING = "Mapping missing"

ROLE_FOR_TYPE = {
	ERP_ONLY: "BARO Stock Manager",
	PLATFORM_ONLY: "BARO Stock Manager",
	STATE_MISMATCH: "BARO Service Supervisor",
	COUNT_MISMATCH: "BARO Service Supervisor",
	MAPPING_MISSING: "BARO Stock Manager",
}

BILLABLE_TYPES = ("Billing mismatch", ERP_ONLY)


def run_id(platform: str) -> str:
	return f"{platform}-{now_datetime().strftime('%Y%m%d%H%M%S')}"


def reconcile_platform(platform: str) -> dict:
	"""Diff one platform. Returns a summary the caller can log; writes exceptions only."""
	from baro_core.integrations.base import resolve

	platform_read = resolve(platform).list_fleet()
	if not platform_read.ok:
		# Circuit breaker: never infer absence from a failed read.
		return {"platform": platform, "aborted": True, "error_class": platform_read.error_class, "written": 0}

	company = frappe.db.get_value("Baro GPS Platform", platform, "company")
	cap = settings.int_value("baro_max_rows_per_run")
	erp = erp_view(platform)
	remote = index_remote(platform_read.data or [])
	remote_total = len(remote)
	summary = {"platform": platform, "run_id": run_id(platform), "erp": len(erp), "platform_rows": remote_total, "written": 0, "truncated": False}

	for serial_no, row in erp.items():
		if summary["written"] >= cap:
			summary["truncated"] = True
			break
		device_id = row.get("platform_device_id")
		if not device_id:
			summary["written"] += write(
				platform=platform, company=company, exception_type=MAPPING_MISSING,
				serial_no=serial_no, vehicle=row.get("baro_vehicle"),
				details=f"Active assignment on {serial_no} has no mapping for {platform}",
				match_key=f"{serial_no}|mapping-missing",
			)
			continue
		remote_row = remote.pop(device_id, None)
		if remote_row is None:
			summary["written"] += write(
				platform=platform, company=company, exception_type=ERP_ONLY,
				serial_no=serial_no, vehicle=row.get("baro_vehicle"),
				details=f"ERP reports an active assignment; {platform} does not list device {device_id}",
				match_key=f"{serial_no}|erp-only",
			)
			continue
		if states_differ(row, remote_row):
			summary["written"] += write(
				platform=platform, company=company, exception_type=STATE_MISMATCH,
				serial_no=serial_no, vehicle=row.get("baro_vehicle"),
				details=f"ERP state {row.get('baro_device_status')} vs platform {remote_row.get('status')}",
				match_key=f"{serial_no}|state",
			)

	for device_id, remote_row in remote.items():
		if summary["written"] >= cap:
			summary["truncated"] = True
			break
		summary["written"] += write(
			platform=platform, company=company, exception_type=PLATFORM_ONLY,
			serial_no=remote_row.get("serial_hint"),
			details=f"{platform} reports device {device_id} that ERP does not assign",
			match_key=f"{device_id}|platform-only",
		)

	summary["written"] += count_delta(platform, company, len(erp), remote_total)
	mark_cleared(platform, summary["run_id"])
	return summary


def erp_view(platform: str) -> dict:
	"""ERP's claim about what should be reporting right now, keyed by serial."""
	rows = frappe.db.sql(
		"""
		select a.serial_no, a.baro_vehicle, a.customer, s.baro_device_status,
			(select m.platform_device_id from `tabBaro Platform Mapping` m
				where m.serial_no = a.serial_no and m.baro_platform = %s and m.baro_enabled = 1
				limit 1) as platform_device_id
		from `tabBaro Device Assignment` a
		left join `tabSerial No` s on s.name = a.serial_no
		where a.docstatus = 1 and a.baro_status = 'Active'""",
		(platform,),
		as_dict=True,
	)
	return {r.serial_no: r for r in rows}


def index_remote(payload_rows) -> dict:
	"""Key the platform's view by its own device id (`50` §3 PlatformDevice)."""
	out = {}
	for row in payload_rows or []:
		key = str(row.get("platform_device_id") or "").strip()
		if key:
			out[key] = row
	return out


def states_differ(erp_row, remote_row) -> bool:
	status = str(remote_row.get("status") or "").lower()
	device_status = (erp_row.get("baro_device_status") or "").lower()
	if status in ("offline", "") and device_status == "active":
		return True
	if status in ("stolen", "moved") and device_status not in ("faulty", "rma"):
		return False
	if status == "maintenance" and device_status not in ("rma", "faulty"):
		return True
	return False


def count_delta(platform: str, company: str, erp_count: int, platform_count: int) -> int:
	"""`51` §4.4: a small delta is noise, a large one is an Approver's problem."""
	threshold = settings.int_value("baro_count_alert_threshold")
	delta = abs(erp_count - platform_count)
	if delta < threshold:
		return 0
	return write(
		platform=platform, company=company, exception_type=COUNT_MISMATCH,
		details=f"ERP reports {erp_count} active devices, platform reports {platform_count} (delta {delta})",
		match_key=f"{platform}|count|{today()}",
		assigned_role="BARO Approver",
	)


def write(platform=None, company=None, exception_type=None, details=None, match_key=None, serial_no=None,
		  vehicle=None, assigned_role=None, ref_doctype=None, ref_name=None, run=None):
	"""Insert one exception, or return 0 when an open row for the same match key already exists."""
	if match_key and frappe.db.exists(
		"Baro Reconciliation Exception",
		{"baro_match_key": match_key, "baro_status": ["in", ["Open", "Acknowledged", "In Progress"]]},
	):
		return 0
	doc = frappe.get_doc(
		{
			"doctype": "Baro Reconciliation Exception",
			"baro_run_id": run or run_id(platform or "billing"),
			"baro_exception_type": exception_type,
			"baro_platform": platform if platform and frappe.db.exists("Baro GPS Platform", platform) else None,
			"serial_no": serial_no,
			"baro_vehicle": vehicle,
			"company": company,
			"ref_doctype": ref_doctype,
			"ref_name": ref_name,
			"baro_detected_at": now_datetime(),
			"baro_match_key": match_key,
			"baro_details": details,
			"baro_status": "Open",
			"baro_assigned_role": assigned_role or ROLE_FOR_TYPE.get(exception_type, "BARO Service Supervisor"),
			"baro_impact_billable": 1 if exception_type in BILLABLE_TYPES else 0,
		}
	)
	doc.insert(ignore_permissions=True)
	return 1


def raise_exception(exception_type=None, company=None, assigned_role=None, details=None, match_key=None,
					serial_no=None, vehicle=None, platform=None, ref_doctype=None, ref_name=None):
	"""Public entry for non-reconciliation detectors (RA-5 billing, dead letters, activation gaps)."""
	return write(
		platform=platform, company=company, exception_type=exception_type, details=details,
		match_key=match_key or f"{exception_type}|{serial_no or vehicle or today()}",
		serial_no=serial_no, vehicle=vehicle, assigned_role=assigned_role,
		ref_doctype=ref_doctype, ref_name=ref_name,
	)


def mark_cleared(platform: str, this_run: str) -> int:
	"""Flag open rows this run no longer reproduces (`51` §6). A flag, never a closure."""
	rows = frappe.get_all(
		"Baro Reconciliation Exception",
		filters={
			"baro_platform": platform,
			"baro_status": ["in", ["Open", "Acknowledged", "In Progress"]],
		},
		pluck="name",
		limit=settings.int_value("baro_max_rows_per_run"),
	)
	count = 0
	for name in rows:
		row = frappe.db.get_value("Baro Reconciliation Exception", name, ["baro_match_key", "baro_cleared_automatically"], as_dict=True)
		if not row.baro_match_key or row.baro_cleared_automatically:
			continue
		# A row survives when this run reproduced the same match key.
		still_open = frappe.db.exists(
			"Baro Reconciliation Exception",
			{"baro_match_key": row.baro_match_key, "baro_run_id": this_run},
		)
		if still_open:
			continue
		frappe.db.set_value("Baro Reconciliation Exception", name, "baro_cleared_automatically", 1, update_modified=True)
		count += 1
	return count

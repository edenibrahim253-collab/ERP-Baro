# Copyright (c) 2026 BARO Group
# License: MIT. See license.txt
"""Whitelisted endpoints (`30` §10).

Rules that hold for every function here: `@frappe.whitelist()` with explicit `methods`, a
server-side `frappe.has_permission` check, no state change that bypasses a workflow transition,
and no raw SQL fragment accepted from the caller.

The scan resolver answers "not found" rather than "not permitted": an attacker holding a scanner
must not be able to enumerate other customers' devices by watching for permission errors
(`41` §5.3).
"""

import frappe
from frappe import _

from baro_core import settings, utils

SCAN_TARGETS = (
	("Serial No", "baro_imei", "Serial No"),
	("Serial No", "name", "Serial No"),
	("Baro SIM Card", "baro_iccid", "Baro SIM Card"),
	("Baro SIM Card", "baro_msisdn", "Baro SIM Card"),
	("Baro Vehicle", "baro_plate_no", "Baro Vehicle"),
	("Baro Vehicle", "baro_vin", "Baro Vehicle"),
	("Baro Platform Mapping", "platform_device_id", "Baro Platform Mapping"),
)


@frappe.whitelist(methods=["GET"])
def resolve_scan(query: str = None):
	if not query:
		return {"found": False}
	normalised = utils.normalise_identifier(query)
	candidates = {query, normalised, utils.imei(query), utils.iccid(query), utils.msisdn(query)}
	for doctype, fieldname, _ in SCAN_TARGETS:
		for value in {c for c in candidates if c}:
			name = frappe.db.get_value(doctype, {fieldname: value}, "name")
			if name and frappe.has_permission(doctype, doc=name):
				return {"found": True, "doctype": doctype, "name": name}
	return {"found": False}


@frappe.whitelist(methods=["GET"])
def get_device_360(serial_no: str = None, plate: str = None, imei: str = None):
	"""Aggregated read. Nothing here mutates, so it is safe for the portal and the kiosk app."""
	serial_no = _resolve_serial(serial_no, plate, imei)
	if not serial_no:
		frappe.throw(_("Device not found"), frappe.DoesNotExistError)
	if not frappe.has_permission("Serial No", doc=serial_no):
		frappe.throw(_("Device not found"), frappe.DoesNotExistError)
	return {
		"serial_no": serial_no,
		"device": frappe.db.get_value(
			"Serial No",
			serial_no,
			["name", "item_code", "customer", "baro_imei", "baro_device_status", "baro_firmware_version", "baro_last_comm_at", "warranty_expiry_date"],
			as_dict=True,
		),
		"assignments": frappe.get_all(
			"Baro Device Assignment",
			filters={"serial_no": serial_no},
			fields=["name", "baro_vehicle", "baro_status", "from_time", "to_time", "baro_activation_status", "customer"],
			order_by="from_time desc",
			limit=50,
		),
		"vehicles": _vehicles_for(serial_no),
		"firmware": frappe.get_all(
			"Baro Firmware History",
			filters={"serial_no": serial_no},
			fields=["baro_firmware_version", "baro_update_date", "baro_update_source"],
			order_by="baro_update_date desc",
			limit=20,
		),
		"rma": frappe.get_all(
			"Baro Device RMA",
			filters={"serial_no": serial_no},
			fields=["name", "baro_rma_status", "baro_rma_reason", "baro_disposition", "modified"],
			order_by="modified desc",
			limit=10,
		),
		"mappings": frappe.get_all(
			"Baro Platform Mapping",
			filters={"serial_no": serial_no},
			fields=["baro_platform", "platform_device_id", "baro_platform_status", "baro_last_comm_at", "baro_enabled"],
		),
		"sim": _sim_for(serial_no),
		"issues": frappe.get_all(
			"Issue", filters={"customer": frappe.db.get_value("Serial No", serial_no, "customer")},
			fields=["name", "subject", "status"], order_by="creation desc", limit=10,
		),
		"inactive_threshold_hours": settings.int_value("baro_inactive_threshold_hours"),
	}


def _resolve_serial(serial_no, plate, imei):
	if serial_no:
		return serial_no
	if imei:
		return frappe.db.get_value("Serial No", {"baro_imei": utils.imei(imei)}, "name")
	if plate:
		vehicle = frappe.db.get_value("Baro Vehicle", {"baro_plate_no": utils.plate(plate)}, "name")
		return frappe.db.get_value("Baro Device Assignment", {"baro_vehicle": vehicle, "baro_status": "Active", "docstatus": 1}, "serial_no")
	return None


def _vehicles_for(serial_no):
	rows = frappe.get_all(
		"Baro Device Assignment", filters={"serial_no": serial_no}, fields=["baro_vehicle", "baro_status", "from_time", "to_time"], order_by="from_time desc", limit=20
	)
	out = []
	for row in rows:
		plate = frappe.db.get_value("Baro Vehicle", row.baro_vehicle, "baro_plate_no")
		out.append({**row, "baro_plate_no": plate})
	return out


def _sim_for(serial_no):
	sim = frappe.db.get_value("Baro SIM Card", {"baro_installed_device": serial_no}, "name")
	if not sim:
		return None
	row = frappe.db.get_value(
		"Baro SIM Card", sim, ["name", "baro_iccid", "baro_msisdn", "baro_sim_status", "baro_expiry_date"], as_dict=True
	)
	return row


@frappe.whitelist(methods=["POST"], allow_guest=False)
def webhook_gps(platform: str = None, event: str = None, payload: str = None, idempotency_key: str = None):
	"""Inbound platform event: verify HMAC, log first, then apply (`50` §4-5).

	The log row is inserted **before** any mutation and its idempotency key is unique, so a replay
	returns the stored result instead of applying the side effect twice.
	"""
	from baro_core.integrations.webhook import verify_and_handle

	if not platform or payload is None:
		frappe.throw(_("platform and payload are required"))
	body = frappe.request.get_data() if frappe.request else frappe.as_json(payload)
	signature = frappe.request.headers.get("X-BARO-Signature") if frappe.request else None
	return verify_and_handle(platform=platform, event=event, body=body, signature=signature, payload=payload, idempotency_key=idempotency_key)


@frappe.whitelist(methods=["GET"])
def get_assignments(customer: str = None, status: str = None, page_length: int = 100, start: int = 0):
	"""Outbound feed for internal tools - paginated and permission-filtered (`30` §10)."""
	filters = {"docstatus": 1}
	if customer:
		filters["customer"] = customer
	if status:
		filters["baro_status"] = status
	rows = frappe.get_list(
		"Baro Device Assignment",
		filters=filters,
		fields=["name", "customer", "baro_vehicle", "serial_no", "baro_status", "from_time", "to_time", "baro_activation_status"],
		order_by="from_time desc",
		limit_page_length=int(page_length),
		start=int(start),
		ignore_permissions=False,
	)
	return rows


@frappe.whitelist(methods=["POST"])
def run_reconciliation(platform: str = None):
	"""The manual "Run now" behind `51` §2 - same implementation the cron calls."""
	from baro_core.integrations.reconciliation import reconcile_platform

	if not frappe.has_permission("Baro Reconciliation Exception", "create"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	allowed = {"BARO System Manager", "BARO Integrator"}
	if not (allowed & set(frappe.get_roles())):
		frappe.throw(_("Only a System Manager or the integration service may start a run"), frappe.PermissionError)
	platforms = [platform] if platform else frappe.get_all("Baro GPS Platform", filters={"baro_enabled": 1}, pluck="name")
	return {p: reconcile_platform(p) for p in platforms}

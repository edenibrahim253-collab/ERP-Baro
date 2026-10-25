# Copyright (c) 2026 BARO Group
# License: MIT. See license.txt
"""Inbound event handling (`50` §4-5). Log first, then apply - never the reverse.

Order matters: if the mutation happened first and the log write failed, a platform retry would
apply the same event twice. Writing the log with its unique `baro_idempotency_key` first means a
replay hits the key, reads the stored result, and returns without touching a document.

An unknown `platform_device_id` creates **no** `Serial No` and **no** mapping. The connector role
has no Create right on `Serial No` precisely so a bot cannot mint inventory records (`41` §5.4);
it raises a `Mapping missing` exception and stops, and only a human with stock rights decides
whether the device is BARO's.
"""

import frappe
from frappe.utils import now_datetime

from baro_core import locks
from baro_core.integrations import base

INBOUND = "Inbound"

# event name -> mutator. A mutator receives (mapping|None, payload) and returns a short result dict.
EVENT_HANDLERS = {}


def _register(name):
	def deco(fn):
		EVENT_HANDLERS[name] = fn
		return fn

	return deco


def verify_and_handle(platform=None, event=None, body=None, signature=None, payload=None, idempotency_key=None):
	from baro_core.integrations.base import resolve

	adapter = resolve(platform)
	if not adapter.verify_signature(body, signature):
		log = create_log(platform, event, idempotency_key or f"unsigned|{now_datetime()}", None)
		complete(log, ok=False, error_class=base.AUTH, message="webhook signature verification failed")
		frappe.throw(frappe._("Signature verification failed"), frappe.AuthenticationError)

	data = payload if isinstance(payload, dict) else frappe.parse_json(body or "{}")
	key = idempotency_key or natural_key(platform, event, data)
	existing = frappe.db.get_value("Baro Integration Log", {"baro_idempotency_key": key}, ["name", "baro_log_status"], as_dict=True)
	if existing:
		return {"log": existing.name, "status": existing.baro_log_status, "replay": True}

	log = create_log(platform, event, key, data)
	try:
		result = apply_event(platform, event, data, log)
	except Exception as error:  # noqa: BLE001 - the log must record any failure, then re-raise
		complete(log, ok=False, error_class=base.classify(error), message=str(error)[:900])
		raise
	complete(log, ok=True)
	return {"log": log.name, "status": "Processed", "replay": False, **result}


def natural_key(platform: str, event: str, data: dict) -> str:
	"""Deterministic key for platforms that do not send one: platform + event + device + timestamp."""
	device = str(data.get("deviceid") or data.get("device_id") or data.get("imei") or data.get("id") or "")
	stamp = str(data.get("gmt") or data.get("timestamp") or data.get("utc_time") or "")[:13]
	return f"{platform}|{event or 'unknown'}|{device}|{stamp}"


def create_log(platform, event, key, data):
	from baro_core.integrations.payload import store_payload

	doc = frappe.get_doc(
		{
			"doctype": "Baro Integration Log",
			"baro_direction": INBOUND,
			"baro_platform": platform,
			"baro_endpoint": f"webhook/{event or 'unknown'}",
			"baro_idempotency_key": key,
			"baro_correlation_id": key.split("|")[-1] if key else None,
			"baro_log_status": "Received",
			"baro_max_attempts": frappe.db.get_value("Baro GPS Platform", platform, "baro_max_retries") or 5,
			"company": frappe.db.get_value("Baro GPS Platform", platform, "company"),
		}
	).insert(ignore_permissions=True)
	doc.baro_payload_ref = store_payload(doc, data)
	doc.save(ignore_permissions=True)
	return doc


def apply_event(platform, event, data, log):
	with locks.acquired([f"webhook:{platform}"]):
		handler = EVENT_HANDLERS.get(event) or EVENT_HANDLERS.get("default")
		result = handler(platform, event, data, log)
		log.ref_doctype, log.ref_name = result.get("ref_doctype"), result.get("ref_name")
		return result


def complete(log, ok: bool, error_class: str = "None", message: str = None):
	"""Close the log row. Success is terminal; failure hands the ladder to `retry` (`50` §6)."""
	if ok:
		log.baro_log_status = "Processed"
		log.baro_processed_at = now_datetime()
		log.baro_error_class = "None"
		log.save(ignore_permissions=True)
		return
	log.baro_log_status = "Failed"
	log.baro_error_message = message
	log.save(ignore_permissions=True)
	from baro_core.integrations.retry import register_failure

	register_failure(log.name, error_class, message)


@_register("device_status")
def handle_device_status(platform, event, data, log):
	mapping = find_mapping(platform, data)
	if not mapping:
		return unmapped(platform, data, log)
	frappe.db.set_value(
		"Baro Platform Mapping",
		mapping.name,
		{"baro_platform_status": status_of(data), "baro_last_comm_at": now_datetime(), "baro_sync_status": "Synced", "baro_last_sync_at": now_datetime()},
		update_modified=False,
	)
	from baro_core import derive

	derive.recompute_last_comm(mapping.serial_no)
	return {"ref_doctype": "Baro Platform Mapping", "ref_name": mapping.name, "serial_no": mapping.serial_no}


@_register("activation_confirmed")
def handle_activation(platform, event, data, log):
	"""The connector, not a human, writes `Verified` on the Installation Note (`21` §2)."""
	mapping = find_mapping(platform, data)
	if not mapping:
		return unmapped(platform, data, log)
	assignment = frappe.db.get_value(
		"Baro Device Assignment",
		{"serial_no": mapping.serial_no, "docstatus": 1, "baro_status": "Active"},
		["name", "baro_installation_note"],
		as_dict=True,
	)
	if not assignment:
		return {"ref_doctype": "Baro Platform Mapping", "ref_name": mapping.name, "ignored": "no active assignment"}
	if assignment.baro_installation_note:
		frappe.db.set_value(
			"Installation Note", assignment.baro_installation_note, "baro_activation_status", "Verified", update_modified=True
		)
	frappe.db.set_value("Baro Device Assignment", assignment.name, "baro_activation_status", "Verified", update_modified=True)
	from baro_core import derive

	derive.set_device_status(mapping.serial_no, "Active")
	return {"ref_doctype": "Baro Device Assignment", "ref_name": assignment.name}


@_register("default")
def handle_unknown(platform, event, data, log):
	return {"ignored": f"no handler for event {event}"}


def find_mapping(platform, data):
	platform_device_id = str(data.get("deviceid") or data.get("device_id") or data.get("id") or "").strip()
	imei = str(data.get("imei") or "").strip()
	if platform_device_id:
		name = frappe.db.get_value("Baro Platform Mapping", {"baro_platform": platform, "platform_device_id": platform_device_id}, "name")
		if name:
			return frappe.get_doc("Baro Platform Mapping", name)
	if imei:
		serial = frappe.db.get_value("Serial No", {"baro_imei": imei}, "name")
		if serial:
			name = frappe.db.get_value("Baro Platform Mapping", {"baro_platform": platform, "serial_no": serial}, "name")
			return frappe.get_doc("Baro Platform Mapping", name) if name else None
	return None


def unmapped(platform, data, log):
	"""`41` §5.4: raise an exception for a human; create no device, no mapping."""
	from baro_core.integrations.reconciliation import raise_exception

	identifier = str(data.get("deviceid") or data.get("imei") or data.get("id") or "unknown")
	raise_exception(
		exception_type="Mapping missing",
		platform=platform,
		company=frappe.db.get_value("Baro GPS Platform", platform, "company"),
		assigned_role="BARO Stock Manager",
		details=f"Inbound event references unknown platform device {identifier}",
		match_key=f"mapping-missing|{platform}|{identifier}",
	)
	log.baro_result_ref = None
	return {"exception": "Mapping missing", "identifier": identifier}


def status_of(data) -> str:
	raw = str(data.get("status") or data.get("state") or "").lower()
	return {
		"online": "Online",
		"offline": "Offline",
		"moved": "Moved",
		"stolen": "Stolen",
		"maintenance": "Maintenance",
	}.get(raw, "Unknown")

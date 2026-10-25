"""BARO error messages.

docs/31-uniqueness-concurrency-design.md #9: a unique-index hit must reach the user as a
named message, never a traceback. Each helper maps one machine failure to the sentence an
operator can act on, and keeps `DuplicateEntryError` as the exception type so the API,
Data Import and the connector can distinguish "retry me" from "you lost the race".
"""

import frappe


def duplicate_imei(imei: str, serial_no: str) -> None:
	frappe.throw(
		frappe._("IMEI {0} is already registered on serial {1}").format(imei, serial_no),
		frappe.DuplicateEntryError,
	)


def duplicate_plate(plate: str, vehicle: str) -> None:
	frappe.throw(
		frappe._("Plate {0} is already registered as vehicle {1}").format(plate, vehicle),
		frappe.DuplicateEntryError,
	)


def duplicate_vin(vin: str, vehicle: str) -> None:
	frappe.throw(
		frappe._("VIN {0} is already registered as vehicle {1}").format(vin, vehicle),
		frappe.DuplicateEntryError,
	)


def duplicate_iccid(iccid: str, sim: str) -> None:
	frappe.throw(
		frappe._("ICCID {0} is already registered as SIM {1}").format(iccid, sim),
		frappe.DuplicateEntryError,
	)


def duplicate_msisdn(msisdn: str, sim: str) -> None:
	frappe.throw(
		frappe._("MSISDN {0} is already registered as SIM {1}").format(msisdn, sim),
		frappe.DuplicateEntryError,
	)


def device_busy() -> None:
	"""Redis lock held by another worker - retryable, and deliberately calmer than a conflict."""
	frappe.throw(
		frappe._("This device is being edited right now. Try again in a few seconds."),
		frappe.DuplicateEntryError,
	)


def overlap(key_label: str, value: str, assignment: str, plate: str, from_time) -> None:
	frappe.throw(
		frappe._("{0} {1} already has assignment {2} covering this period ({3} from {4})").format(
			key_label, value, assignment, plate, frappe.utils.format_datetime(from_time, "dd-MM-yyyy HH:mm")
		),
		frappe.DuplicateEntryError,
	)


def cannot_cancel_with_history(doctype: str, name: str) -> None:
	frappe.throw(
		frappe._("{0} {1} has produced service or billing history; amend it instead of cancelling").format(
			doctype, name
		)
	)


def self_approval_forbidden() -> None:
	frappe.throw(frappe._("You cannot approve a document you created. Ask another approver."))


def integrator_may_not_resolve() -> None:
	frappe.throw(
		frappe._("The integration service may not resolve or waive a reconciliation exception.")
	)


def platform_disabled(platform: str) -> None:
	frappe.throw(frappe._("GPS platform {0} is disabled; enable it before mapping devices").format(platform))

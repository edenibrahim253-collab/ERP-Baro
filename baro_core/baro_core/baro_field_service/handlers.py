# Copyright (c) 2026 BARO Group
# License: MIT. See license.txt
"""Side effects for the field-service module (`21` §9 write matrix).

Everything in here writes *another* DocType, which is why it is a `doc_events` handler and not
controller code (`30` §1): the connector must be able to run the identical path when a platform
confirms an activation, without a human opening the form.

Two rules are visible in the shape of this file. Derived pointers are written through
`baro_core.derive`, so exactly one module touches them. And nothing here submits or cancels a
document: an activation verified by the platform writes a status field, never a new workflow
transition on a business record.
"""

import frappe
from frappe import _
from frappe.utils import add_days, now

from baro_core import derive, settings, utils

DEVICE_ACTIVE = "Active"
DEVICE_INSTALLED = "Installed"
DEVICE_RETURNED = "Returned"
DEVICE_RMA = "RMA"

VERIFIED = "Verified"
NOT_VERIFIED = "Not Verified"
FAILED = "Failed"


def after_assignment_submit(doc, method=None):
	"""`21` §2 on_submit: device Installed, vehicle/SIM pointers, activation Task, firmware row."""
	derive.set_device_status(doc.serial_no, DEVICE_INSTALLED)
	derive.touch_vehicle_pointers(doc.baro_vehicle, doc.name, doc.serial_no)
	if doc.baro_sim_card:
		derive.touch_sim_pointers(doc.baro_sim_card, doc.serial_no, doc.baro_vehicle)
	create_activation_task(doc)
	record_known_firmware(doc)
	backfill_installation_note(doc)


def after_assignment_cancel(doc, method=None):
	"""Cancel is only legal pre-activation (`21` §2), so reverting derived state is complete."""
	derive.set_device_status(doc.serial_no, DEVICE_RETURNED)
	derive.touch_vehicle_pointers(doc.baro_vehicle, None, None)
	if doc.baro_sim_card:
		derive.touch_sim_pointers(doc.baro_sim_card, None, None)
	close_activation_task(doc)


def after_assignment_update(doc, method=None):
	"""An ended or superseded assignment hands the device and vehicle back."""
	if doc.baro_status in (derive.ENDED, derive.SUPERSEDED):
		derive.set_device_status(doc.serial_no, device_state_after_end(doc))
		derive.touch_vehicle_pointers(doc.baro_vehicle, None, None)
		if doc.baro_sim_card:
			derive.touch_sim_pointers(doc.baro_sim_card, None, None)
	elif doc.baro_status == derive.ACTIVE:
		derive.touch_vehicle_pointers(doc.baro_vehicle, doc.name, doc.serial_no)


def device_state_after_end(doc):
	if frappe.db.exists("Baro Device RMA", {"serial_no": doc.serial_no, "docstatus": ["!=", 2]}):
		return DEVICE_RMA
	return DEVICE_RETURNED


def create_activation_task(doc):
	"""One Task per activation, owned by the technician, due on the SLA (`60` T2)."""
	plate = frappe.db.get_value("Baro Vehicle", doc.baro_vehicle, "baro_plate_no") or doc.baro_vehicle
	subject = _("Verify activation - {0} ({1})").format(plate, doc.name)
	if frappe.db.exists("Task", {"subject": subject, "status": ["!=", "Cancelled"]}):
		return
	frappe.get_doc(
		{
			"doctype": "Task",
			"subject": subject,
			"issue_type": "Task",
			"status": "Open",
			"project": doc.baro_project,
			"_assign": json_assign(doc.baro_technician),
			"exp_start_date": doc.from_time or now(),
			"exp_end_date": add_days(doc.from_time or now(), settings.int_value("baro_activation_sla_days")),
			"description": task_description(doc),
		}
	).insert(ignore_permissions=True, ignore_mandatory=True)


def task_description(doc):
	return _(
		"Confirm the device is reporting to the platform, then set the Installation Note "
		"activation status. Assignment {0}, vehicle {1}, device {2}, SIM {3}."
	).format(doc.name, doc.baro_vehicle, doc.serial_no, doc.baro_sim_card or "-")


def json_assign(employee):
	"""`Task._assign` stores a JSON list of user ids; the technician's login, if resolvable."""
	import json

	if not employee:
		return None
	user = frappe.db.get_value("Employee", employee, "user_id")
	return json.dumps([user]) if user else None


def close_activation_task(doc):
	"""A cancelled assignment leaves no dangling activation work."""
	plate = frappe.db.get_value("Baro Vehicle", doc.baro_vehicle, "baro_plate_no") or doc.baro_vehicle
	subject = _("Verify activation - {0} ({1})").format(plate, doc.name)
	for name in frappe.get_all("Task", filters={"subject": subject, "status": "Open"}, pluck="name", limit=5):
		frappe.db.set_value("Task", name, "status", "Closed", update_modified=True)


def record_known_firmware(doc):
	"""A device with a known firmware version gets a history row at the moment of install."""
	if not doc.serial_no:
		return
	version = frappe.db.get_value("Serial No", doc.serial_no, "baro_firmware_version")
	if not version:
		return
	from frappe.utils import getdate

	exists = frappe.db.exists(
		"Baro Firmware History",
		{
			"serial_no": doc.serial_no,
			"baro_firmware_version": version,
			"baro_update_date": getdate(doc.from_time or now()),
		},
	)
	if exists:
		return
	frappe.get_doc(
		{
			"doctype": "Baro Firmware History",
			"serial_no": doc.serial_no,
			"baro_firmware_version": version,
			"baro_update_date": getdate(doc.from_time or now()),
			"baro_update_source": "Manual",
			"company": doc.company,
		}
	).insert(ignore_permissions=True)


def backfill_installation_note(doc):
	"""The note may exist before the assignment is approved; then the link is written here."""
	note = frappe.db.get_value(
		"Installation Note", {"baro_assignment": doc.name}, "name"
	) or frappe.db.get_value(
		"Installation Note",
		{"baro_vehicle": doc.baro_vehicle, "docstatus": ["in", (0, 1)]},
		"name",
	)
	if note and not frappe.db.get_value("Installation Note", note, "baro_assignment"):
		frappe.db.set_value("Installation Note", note, "baro_assignment", doc.name, update_modified=True)


def validate_installation_note(doc, method=None):
	"""`21` §2: the note cannot claim a vehicle or assignment that contradicts the spine."""
	if not doc.baro_vehicle and not doc.baro_assignment:
		return
	assignment = doc.baro_assignment
	if assignment:
		row = frappe.db.get_value(
			"Baro Device Assignment", assignment, ["baro_vehicle", "customer", "docstatus"], as_dict=True
		)
		if not row:
			frappe.throw(_("Assignment {0} does not exist").format(assignment))
		if doc.baro_vehicle and row.baro_vehicle and doc.baro_vehicle != row.baro_vehicle:
			frappe.throw(
				_("Vehicle {0} does not match assignment {1}").format(doc.baro_vehicle, assignment)
			)
		if row.docstatus == 0:
			frappe.throw(_("Assignment {0} is a draft; submit it before installing").format(assignment))
	if doc.baro_vehicle and doc.customer:
		owner = frappe.db.get_value("Baro Vehicle", doc.baro_vehicle, "customer")
		if owner and owner != doc.customer:
			frappe.throw(
				_("Vehicle {0} belongs to {1}, not {2}").format(doc.baro_vehicle, owner, doc.customer)
			)


def after_installation_submit(doc, method=None):
	if not doc.baro_assignment:
		return
	frappe.db.set_value(
		"Baro Device Assignment", doc.baro_assignment, "baro_installation_note", doc.name, update_modified=True
	)


def after_installation_update(doc, method=None):
	"""Platform verification promotes the device; the installer never sets this field."""
	if doc.baro_activation_status == VERIFIED and doc.baro_assignment:
		serial = frappe.db.get_value("Baro Device Assignment", doc.baro_assignment, "serial_no")
		if frappe.db.get_value("Serial No", serial, "baro_device_status") == DEVICE_INSTALLED:
			derive.set_device_status(serial, DEVICE_ACTIVE)
		derive.touch_vehicle_pointers(doc.baro_vehicle, doc.baro_assignment, serial)
	elif doc.baro_activation_status == FAILED and doc.baro_assignment:
		serial = frappe.db.get_value("Baro Device Assignment", doc.baro_assignment, "serial_no")
		flag_mapping_missing(doc, serial)


def flag_mapping_missing(doc, serial_no):
	"""Activation failed usually means the platform does not know this device yet (`51` §4)."""
	from baro_core.integrations.reconciliation import raise_exception

	raise_exception(
		exception_type="Mapping missing",
		serial_no=serial_no,
		vehicle=doc.baro_vehicle,
		company=doc.company,
		assigned_role="BARO Stock Manager",
		details=_("Installation {0} could not be verified against the platform").format(doc.name),
	)

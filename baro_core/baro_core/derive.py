"""The single writer for derived state (docs/31-uniqueness-concurrency-design.md #4.2).

`set_active_keys` is the whole conditional-uniqueness mechanism: the UQ-DRV columns carry the
constrained key while the assignment is live and NULL otherwise, so MariaDB's "many NULLs are
allowed in a unique index" behaviour gives BARO a filtered unique index it cannot express in DDL.

Every path that can change liveness calls this - draft edit, submit, approval, ending, cancel,
amend, Data Import and the connector. A path that forgets it turns the unique index into a false
guarantee, which is why `patches.v1.integrity_audit` re-checks the state after every migrate.

Hard rule: no other module may write these columns with `frappe.db.set_value`.
"""

import frappe

ACTIVE = "Active"
ENDED = "Ended"
SUPERSEDED = "Superseded"
DRAFT = "Draft"
PENDING = "Pending Approval"

# Device states a unit may be issued from (docs/21 #2). Active is excluded - it is exactly
# what U-6 prevents - and In-Stock/Disposed are not field-serviceable.
ISSUABLE_DEVICE_STATES = ("Reserved", "Allocated", "Returned", "Faulty")


def is_live(doc) -> bool:
	return int(doc.docstatus or 0) == 1 and doc.baro_status == ACTIVE


def set_active_keys(doc) -> None:
	"""The maintenance rule, verbatim from docs/31 #4.2."""
	live = is_live(doc)
	doc.baro_active_serial_key = doc.serial_no if live else None
	doc.baro_active_vehicle_key = doc.baro_vehicle if live else None


def set_device_status(serial_no: str | None, status: str) -> None:
	"""Write `Serial No.baro_device_status`. The assignment and RMA controllers are the authority."""
	if not serial_no or not frappe.db.exists("Serial No", serial_no):
		return
	frappe.db.set_value("Serial No", serial_no, "baro_device_status", status, update_modified=True)


def touch_vehicle_pointers(vehicle: str | None, assignment: str | None, serial_no: str | None) -> None:
	"""Set or clear the vehicle's derived current pointers, and the fleet status that follows."""
	if not vehicle:
		return
	frappe.db.set_value("Baro Vehicle", vehicle, "baro_current_assignment", assignment, update_modified=False)
	frappe.db.set_value("Baro Vehicle", vehicle, "baro_current_device", serial_no, update_modified=False)
	if assignment:
		frappe.db.set_value("Baro Vehicle", vehicle, "baro_status", "In-Service", update_modified=False)
	elif frappe.db.get_value("Baro Vehicle", vehicle, "baro_status") == "In-Service":
		frappe.db.set_value("Baro Vehicle", vehicle, "baro_status", "Registered", update_modified=False)


def touch_sim_pointers(sim: str | None, serial_no: str | None, vehicle: str | None) -> None:
	if not sim:
		return
	frappe.db.set_value("Baro SIM Card", sim, "baro_installed_device", serial_no, update_modified=False)
	frappe.db.set_value("Baro SIM Card", sim, "baro_installed_vehicle", vehicle, update_modified=False)


def recompute_last_comm(serial_no: str | None) -> None:
	"""`Serial No.baro_last_comm_at` is the max over enabled mappings for that device (docs/21 #4)."""
	if not serial_no:
		return
	latest = frappe.db.sql(
		"""
		select max(baro_last_comm_at)
		from `tabBaro Platform Mapping`
		where serial_no = %s and baro_enabled = 1""",
		(serial_no,),
	)[0][0]
	frappe.db.set_value("Serial No", serial_no, "baro_last_comm_at", latest, update_modified=False)


def recompute_firmware_version(serial_no: str | None) -> None:
	"""`Serial No.baro_firmware_version` follows the newest Firmware History row (docs/21 #5)."""
	if not serial_no:
		return
	version = frappe.db.get_value(
		"Baro Firmware History",
		filters={"serial_no": serial_no},
		fieldname="baro_firmware_version",
		order_by="baro_update_date desc, creation desc",
	)
	frappe.db.set_value("Serial No", serial_no, "baro_firmware_version", version, update_modified=False)


def supersede_assignment(name: str | None, replaced_by: str | None = None) -> None:
	"""End an Active assignment as a *replacement*, not a cancellation.

	The only cross-DocType state write the RMA path makes (`21` §6). It goes through the
	assignment document so `set_active_keys` runs here and nowhere else: a superseded row
	must hand its UQ-DRV slot back or the next install is blocked by a ghost.

	`ignore_validate_update_after_submit` is the flag the workflow engine itself uses for
	state fields; `[verify-vs-v16]` the flag name still exists in the pinned Frappe.
	"""
	if not name or not frappe.db.exists("Baro Device Assignment", name):
		return
	doc = frappe.get_doc("Baro Device Assignment", name)
	if doc.docstatus != 1 or doc.baro_status != ACTIVE:
		return
	doc.flags.ignore_validate_update_after_submit = True
	doc.baro_status = SUPERSEDED
	if replaced_by:
		doc.baro_replaced_by = replaced_by
	set_active_keys(doc)
	doc.save(ignore_permissions=True)
	touch_vehicle_pointers(doc.baro_vehicle, None, None)
	set_device_status(doc.serial_no, "Returned")

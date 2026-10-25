# Copyright (c) 2026 BARO Group
# License: MIT. See license.txt
"""Device-module effects (`21` §9, docs/10 §3).

`Serial No` is ERPNext's record of the physical unit; BARO only adds identity and state on top
of it (`03` D2). These handlers are where the two meet, and they are written so the connector
and the UI cannot diverge:

* IMEI is required *conditionally* - a GPS device Item Group demands it, a tyre does not - which
  is why the field is not `reqd` in the Custom Field but enforced here.
* A serial with a live assignment cannot be moved back into a stock warehouse by hand. That
  fork between BARO state and stock truth is integrity-audit check 3 (`31` §7.3); refusing it at
  write time is cheaper than reporting it after.
"""

import frappe
from frappe import _
from frappe.utils import getdate, now

from baro_core import derive, exceptions, settings, utils

DEVICE_STATES = (
	"In-Stock",
	"Reserved",
	"Allocated",
	"Installed",
	"Active",
	"Faulty",
	"RMA",
	"Returned",
	"Disposed",
)
STOCK_SIDE_STATES = ("In-Stock", "Reserved", "Allocated")


def validate_serial_no(doc, method=None):
	if not is_device(doc):
		return
	normalise_imei(doc)
	require_imei(doc)
	assert_unique_imei(doc)
	set_default_device_status(doc)
	assert_no_stock_pull_while_active(doc)


def is_device(doc) -> bool:
	return settings.is_device_item_group(getattr(doc, "item_code", None) and frappe.db.get_value(
		"Item", doc.item_code, "item_group"
	))


def normalise_imei(doc):
	if doc.baro_imei:
		doc.baro_imei = utils.imei(doc.baro_imei) or doc.baro_imei


def require_imei(doc):
	if not doc.baro_imei:
		frappe.throw(
			_("IMEI is required for devices in the GPS Item Groups ({0})").format(
				", ".join(settings.device_item_groups())
			)
		)


def assert_unique_imei(doc):
	existing = frappe.db.get_value("Serial No", {"baro_imei": doc.baro_imei}, "name")
	if existing and existing != doc.name:
		exceptions.duplicate_imei(doc.baro_imei, existing)


def set_default_device_status(doc):
	if not doc.baro_device_status:
		doc.baro_device_status = "In-Stock"
	if doc.baro_device_status not in DEVICE_STATES:
		frappe.throw(_("Unknown BARO device status {0}").format(doc.baro_device_status))


def assert_no_stock_pull_while_active(doc):
	if doc.is_new():
		return
	previous = frappe.db.get_value("Serial No", doc.name, "baro_device_status")
	if previous not in ("Installed", "Active") or doc.baro_device_status not in STOCK_SIDE_STATES:
		return
	active = frappe.db.get_value(
		"Baro Device Assignment",
		{"serial_no": doc.name, "docstatus": 1, "baro_status": "Active"},
		"name",
	)
	if active and doc.baro_device_status in STOCK_SIDE_STATES:
		frappe.throw(
			_("Device is assigned by {0}; end that assignment before returning it to stock").format(active)
		)


def after_serial_update(doc, method=None):
	"""The firmware pointer always follows the newest history row (`30` §7 DRV)."""
	if not doc.get("baro_firmware_version"):
		return
	newest = frappe.db.get_value(
		"Baro Firmware History",
		{"serial_no": doc.name},
		"baro_firmware_version",
		order_by="baro_update_date desc, creation desc",
	)
	if newest and newest != doc.baro_firmware_version:
		derive.recompute_firmware_version(doc.name)


def after_quality_inspection(doc, method=None):
	"""An inspection that records a firmware read becomes a history row, source Manual (`21` §5)."""
	version = inspection_firmware(doc)
	if not version or not doc.serial_no:
		return
	if frappe.db.exists(
		"Baro Firmware History",
		{
			"serial_no": doc.serial_no,
			"baro_firmware_version": version,
			"baro_update_date": getdate(doc.date_of_inspection or now()),
		},
	):
		return
	frappe.get_doc(
		{
			"doctype": "Baro Firmware History",
			"serial_no": doc.serial_no,
			"baro_firmware_version": version,
			"baro_update_date": getdate(doc.date_of_inspection or now()),
			"baro_update_source": "Manual",
			"baro_release_notes": _("Captured by inspection {0}").format(doc.name),
			"company": doc.company,
		}
	).insert(ignore_permissions=True)


def inspection_firmware(doc):
	for row in doc.get("quality_inspection_template_details") or []:
		value = (getattr(row, "value", "") or getattr(row, "result", "") or "").strip()
		if (row.parameter or "").lower().startswith("firmware") and value:
			return value
	return None


def validate_warranty_claim(doc, method=None):
	"""`21` §6 keeps the claim and the asset register telling the same story."""
	if not doc.serial_no:
		return
	owner = frappe.db.get_value("Serial No", doc.serial_no, "customer")
	if owner and doc.customer and owner != doc.customer:
		frappe.throw(
			_("Serial {0} belongs to {1}, not {2}").format(doc.serial_no, owner, doc.customer)
		)
	status = frappe.db.get_value("Serial No", doc.serial_no, "baro_device_status")
	if status == "RMA" and not frappe.db.exists(
		"Baro Device RMA", {"serial_no": doc.serial_no, "docstatus": ["!=", 2]}
	):
		frappe.throw(
			_("Serial {0} is marked RMA but no RMA document exists - register it first").format(doc.serial_no)
		)


def after_firmware_row(doc, method=None):
	derive.recompute_firmware_version(doc.serial_no)

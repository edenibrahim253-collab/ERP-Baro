# Copyright (c) 2026 BARO Group
# License: MIT. See license.txt
"""`Baro Firmware History` — append-only device version timeline (`21` §5).

Two rules give the table its value: a duplicate `(serial_no, version, date)` is rejected
because a re-delivered platform sync is the realistic cause, and `Serial No.baro_firmware_version`
always follows the *newest* row rather than the row just written, so a back-filled historical
record cannot silently downgrade a device's reported firmware.
"""

import frappe
from frappe.model.document import Document
from frappe import _

from baro_core import derive, settings


class BaroFirmwareHistory(Document):
	def validate(self):
		self.validate_serial_is_device()
		self.assert_not_duplicate()

	def validate_serial_is_device(self):
		item_code = frappe.db.get_value("Serial No", self.serial_no, "item_code")
		if not item_code:
			frappe.throw(_("Serial {0} does not exist").format(self.serial_no))
		group = frappe.db.get_value("Item", item_code, "item_group")
		if not settings.is_device_item_group(group):
			frappe.throw(_("Serial {0} is not a GPS device item").format(self.serial_no))

	def assert_not_duplicate(self):
		clash = frappe.db.get_all(
			"Baro Firmware History",
			filters={
				"serial_no": self.serial_no,
				"baro_firmware_version": self.baro_firmware_version,
				"baro_update_date": self.baro_update_date,
			},
			fields=["name"],
			limit=2,
		)
		clash = [r.name for r in clash if r.name != self.name]
		if clash:
			frappe.throw(
				_("Firmware {0} on {1} for {2} is already recorded as {3}").format(
					self.baro_firmware_version, self.baro_update_date, self.serial_no, clash[0]
				),
				frappe.DuplicateEntryError,
			)

	def after_insert(self):
		derive.recompute_firmware_version(self.serial_no)

	def on_update(self):
		derive.recompute_firmware_version(self.serial_no)

	def on_trash(self):
		derive.recompute_firmware_version(self.serial_no)

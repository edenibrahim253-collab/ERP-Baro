# Copyright (c) 2026 BARO Group
# License: MIT. See license.txt
"""`Baro Platform Mapping` — the only place an external platform identity lives.

Non-submittable reference data on purpose (`21` §4): the connector upserts it freely,
while business records stay under workflow control. Composite uniqueness comes from
`autoname: format:{baro_platform}-{platform_device_id}`, so "one external id per
platform" is a primary-key fact rather than an application check.

`Serial No.baro_last_comm_at` is recomputed by the `doc_events` handler
(`baro_core.handlers`), not here, so the same rule runs for UI edits and syncs.
"""

import frappe
from frappe.model.document import Document
from frappe import _

from baro_core import exceptions, settings


class BaroPlatformMapping(Document):
	def validate(self):
		self.scrub_platform_device_id()
		self.validate_platform_is_usable()
		self.validate_serial_is_device()
		self.assert_one_serial_per_platform()

	def scrub_platform_device_id(self):
		# The autoname format reads this field, so it must be normalised before naming.
		self.platform_device_id = (self.platform_device_id or "").strip()
		if not self.platform_device_id:
			frappe.throw(_("Platform device id is required"))

	def validate_platform_is_usable(self):
		platform = frappe.db.get_value(
			"Baro GPS Platform", self.baro_platform, ["baro_enabled", "baro_platform_name"], as_dict=True
		)
		if not platform:
			frappe.throw(_("GPS Platform {0} does not exist").format(self.baro_platform))
		if not platform.baro_enabled:
			exceptions.platform_disabled(platform.baro_platform_name)

	def validate_serial_is_device(self):
		item_code = frappe.db.get_value("Serial No", self.serial_no, "item_code")
		if not item_code:
			frappe.throw(_("Serial {0} does not exist").format(self.serial_no))
		group = frappe.db.get_value("Item", item_code, "item_group")
		if not settings.is_device_item_group(group):
			frappe.throw(_("Serial {0} is not a GPS device item").format(self.serial_no))

	def assert_one_serial_per_platform(self):
		"""Reverse direction of the PK rule: a serial may not appear twice on one platform."""
		existing = frappe.db.get_all(
			"Baro Platform Mapping",
			filters={"baro_platform": self.baro_platform, "serial_no": self.serial_no},
			fields=["name"],
			limit=2,
		)
		clash = [r.name for r in existing if r.name != self.name]
		if clash:
			frappe.throw(
				_("Device {0} is already mapped on {1} as {2}").format(
					self.serial_no, self.baro_platform, clash[0]
				),
				frappe.DuplicateEntryError,
			)

	def on_update(self):
		self.sync_vehicle_pointer()

	def sync_vehicle_pointer(self):
		"""Keep the denormalised vehicle in step with the device's active assignment."""
		if self.baro_vehicle:
			return
		assignment = frappe.db.get_value(
			"Baro Device Assignment",
			{"serial_no": self.serial_no, "docstatus": 1, "baro_status": "Active"},
			"baro_vehicle",
		)
		if assignment:
			self.baro_vehicle = assignment

	def before_delete(self):
		if frappe.session.user != "Administrator" and not frappe.has_permission(
			"Baro Platform Mapping", "delete"
		):
			frappe.throw(_("Only a System Manager may remove a platform mapping"))

"""`Baro Vehicle` behaviour - docs/21-custom-doctype-fields.md #1.

The fleet register unit. Plate is deliberately **not** the document name: Ethiopian plates are
re-issued when a vehicle changes owner, and the internal id must survive that (docs/30 #3 rule 1).
"""

import frappe
from frappe import _
from frappe.model.document import Document

from baro_core import settings, utils
from baro_core.exceptions import duplicate_plate, duplicate_vin

ACTIVE = "Active"


class BaroVehicle(Document):
	def validate(self):
		self.set_default_company()
		self.normalise_identifiers()
		self.validate_plate()
		self.validate_vin()
		self.validate_unique_identifiers()
		self.validate_owner_change()
		self.validate_plate_change_has_reason()
		self.warn_near_duplicate()

	def before_delete(self):
		# A vehicle that ever had an assignment is retired, not deleted (docs/41 #2 footnote "dagger").
		if frappe.db.exists(
			"Baro Device Assignment", {"baro_vehicle": self.name, "docstatus": ("!=", 2)}
		):
			frappe.throw(
				_(
					"Vehicle {0} already has assignment history. Retire it instead of deleting it, so the "
					"device and billing trail stays intact."
				).format(self.name)
			)

	def on_update(self):
		self.reconcile_current_pointers()

	def set_default_company(self):
		if not self.company:
			self.company = frappe.defaults.get_user_default("Company") or frappe.db.get_single_value(
				"Global Settings", "default_company"
			)
		if not self.company:
			frappe.throw(_("Company is required before a vehicle can be registered"))

	def normalise_identifiers(self):
		if settings.get("baro_normalise_identifiers"):
			self.baro_plate_no = utils.plate(self.baro_plate_no)
			self.baro_vin = utils.normalise_identifier(self.baro_vin)
		self.baro_vin = utils.scrub_null(self.baro_vin)
		self.baro_chassis_no = utils.scrub_null(self.baro_chassis_no)

	def validate_plate(self):
		if not self.baro_plate_no:
			frappe.throw(_("Plate Number is required"))
		if not settings.matches("baro_plate_pattern", self.baro_plate_no):
			frappe.throw(
				_("Plate {0} does not match the Ethiopian format").format(self.baro_plate_no)
			)

	def validate_vin(self):
		if self.baro_vin and len(self.baro_vin) != 17:
			frappe.throw(_("VIN must be 17 characters"))

	def validate_unique_identifiers(self):
		"""Friendly pre-check; the unique index still has the last word under a race (docs/31 #2)."""
		other = frappe.db.get_value(
			"Baro Vehicle", {"name": ("!=", self.name), "baro_plate_no": self.baro_plate_no}, "name"
		)
		if other:
			duplicate_plate(self.baro_plate_no, other)
		if self.baro_vin:
			other_vin = frappe.db.get_value(
				"Baro Vehicle", {"name": ("!=", self.name), "baro_vin": self.baro_vin}, "name"
			)
			if other_vin:
				duplicate_vin(self.baro_vin, other_vin)

	def validate_owner_change(self):
		if not self.has_value_changed("customer") or self.is_new():
			return
		active = frappe.db.get_value(
			"Baro Device Assignment",
			{"baro_vehicle": self.name, "docstatus": 1, "baro_status": ACTIVE},
			"name",
		)
		if active:
			frappe.throw(
				_("End or supersede assignment {0} before changing the vehicle's customer").format(active)
			)

	def validate_plate_change_has_reason(self):
		if self.has_value_changed("baro_plate_no") and not self.is_new() and not (self.baro_notes or "").strip():
			frappe.throw(_("A plate change requires a reason"))

	def warn_near_duplicate(self):
		"""Non-blocking: same customer, plate within one edit distance of an existing one."""
		if self.is_new():
			return
		candidates = frappe.db.sql_list(
			"""
			select name from `tabBaro Vehicle`
			where name != %s and customer = %s
			  and (baro_plate_no like %s or baro_plate_no like %s)
			limit 3""",
			(
				self.name,
				self.customer,
				f"{self.baro_plate_no[:4]}%",
				f"%{self.baro_plate_no[-4:]}",
			),
		)
		for candidate in candidates:
			other = frappe.db.get_value("Baro Vehicle", candidate, "baro_plate_no")
			if other != self.baro_plate_no and _similar(other, self.baro_plate_no):
				frappe.msgprint(
					_("Similar plate {0} already exists for {1}").format(other, self.customer),
					indicator="orange",
					alert=True,
				)
				return

	def reconcile_current_pointers(self):
		"""The assignment is the authority for the derived pointers; correct any drift."""
		active = frappe.db.get_value(
			"Baro Device Assignment",
			{"baro_vehicle": self.name, "docstatus": 1, "baro_status": ACTIVE},
			"name",
		)
		if active != (self.baro_current_assignment or None):
			assignment = frappe.db.get_value("Baro Device Assignment", active, "serial_no") if active else None
			self.db_set("baro_current_assignment", active, update_modified=False)
			self.db_set("baro_current_device", assignment, update_modified=False)
			if active:
				status = "In-Service"
			elif self.baro_status == "In-Service":
				status = "Registered"
			else:
				status = None
			if status:
				self.db_set("baro_status", status, update_modified=False)


def _similar(a: str, b: str) -> bool:
	if a == b or abs(len(a) - len(b)) > 2:
		return False
	# Levenshtein without a dependency, bounded to short plates.
	prev = list(range(len(b) + 1))
	for i, ca in enumerate(a, 1):
		cur = [i]
		for j, cb in enumerate(b, 1):
			cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
		prev = cur
	return prev[-1] <= 2

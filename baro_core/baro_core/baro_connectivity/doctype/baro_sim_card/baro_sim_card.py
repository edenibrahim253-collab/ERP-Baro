"""`Baro SIM Card` - docs/21-custom-doctype-fields.md #3.

Lifecycle: `Provisioned -> Activated -> Suspended -> Deactivated -> Expired`. The scheduled job
**flags** approaching and passed expiry; it never flips the status itself, because a silent status
change in a record technicians rely on for field diagnostics would break them. `Expired` is set by
the Connectivity Admin from the flagged list (docs/60 T7).
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime, today

from baro_core import settings, utils

SUSPEND_TRANSITIONS = {"Activated": ("Suspended",), "Suspended": ("Activated", "Deactivated")}


class BaroSIMCard(Document):
	def validate(self):
		self.normalise_identifiers()
		self.validate_iccid()
		self.validate_msisdn()
		self.validate_supplier_is_provider()
		self.validate_expiry()
		self.validate_replacement_chain_is_acyclic()
		self.validate_unique_identifiers()
		if not self.company:
			self.company = frappe.defaults.get_user_default("Company")

	def before_submit(self):
		if self.baro_installed_device and self.baro_installed_device != (self.name or ""):
			frappe.throw(_("SIM is installed in {0}").format(self.baro_installed_device))

	def on_update_after_submit(self):
		if self.has_value_changed("baro_sim_status") and self.baro_sim_status in ("Suspended", "Activated"):
			if not set(("BARO Approver", "BARO Finance Approver", "BARO System Manager")) & set(frappe.get_roles()):
				frappe.throw(_("Suspension requires approval by a Finance Approver"))
			if not (self.baro_notes or "").strip():
				frappe.throw(_("A suspension or reactivation must record the reason in Notes"))

	def on_cancel(self):
		from baro_core import derive

		derive.touch_sim_pointers(self.name, None, None)

	def normalise_identifiers(self):
		self.baro_iccid = utils.iccid(self.baro_iccid) or utils.digits(self.baro_iccid)
		self.baro_msisdn = utils.msisdn(self.baro_msisdn)

	def validate_iccid(self):
		if not self.baro_iccid:
			frappe.throw(_("ICCID is required"))
		if not (19 <= len(self.baro_iccid) <= 20) or not utils.luhn_valid(self.baro_iccid):
			frappe.throw(_("ICCID {0} is not valid").format(self.baro_iccid))

	def validate_msisdn(self):
		if not self.baro_msisdn:
			frappe.throw(_("MSISDN is required"))
		if not settings.matches("baro_msisdn_pattern", self.baro_msisdn):
			frappe.throw(_("MSISDN {0} does not match the provider format").format(self.baro_msisdn))

	def validate_supplier_is_provider(self):
		group = frappe.db.get_value("Supplier", self.supplier, "supplier_group")
		if not frappe.db.exists("Supplier", self.supplier):
			frappe.throw(_("Select the connectivity provider"))
		if group and "tele" not in (group or "").lower().replace(" ", "") and not _is_telco_group(group):
			frappe.msgprint(
				_("Provider {0} is not in a telco Supplier Group; record why before relying on expiry alerts").format(
					group
				),
				indicator="orange",
			)

	def validate_expiry(self):
		if self.is_new() and get_datetime(str(self.baro_expiry_date)) < get_datetime(today()):
			frappe.throw(_("Plan expiry must be in the future"))

	def validate_replacement_chain_is_acyclic(self):
		node, depth = self.baro_replaces, 0
		seen = {self.name} if self.name else set()
		while node:
			if node in seen or depth > 20:
				frappe.throw(_("Replacement chain loops back to {0}").format(node))
			seen.add(node)
			node = frappe.db.get_value("Baro SIM Card", node, "baro_replaces")
			depth += 1

	def validate_unique_identifiers(self):
		for field in ("baro_iccid", "baro_msisdn"):
			other = frappe.db.get_value(
				"Baro SIM Card", {"name": ("!=", self.name), field: self.get(field)}, "name"
			)
			if other:
				frappe.throw(
					_("{0} is already used by SIM {1}").format(self.get(field), other),
					frappe.DuplicateEntryError,
				)


def _is_telco_group(supplier_group: str) -> bool:
	return bool(
		frappe.db.exists(
			"Supplier Group",
			["like", "%{}%".format(supplier_group)],
		)
	)

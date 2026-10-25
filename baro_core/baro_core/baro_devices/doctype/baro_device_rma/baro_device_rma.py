# Copyright (c) 2026 BARO Group
# License: MIT. See license.txt
"""`Baro Device RMA` — submittable return/replace/scrap authorisation (`21` §6).

The RMA deliberately creates no stock entries, no purchase invoices and no replacement
assignment. It records the decision and the evidence; a human with the right role performs
the effect through the normal document ("detection is not action", `01` §6). The one write
it makes outside itself is the device status, because the device's state *is* the RMA's
subject, and the pre-RMA status is captured so cancellation can restore it.
"""

import frappe
from frappe.model.document import Document
from frappe import _
from frappe.utils import getdate, nowdate

from baro_core import derive, settings, utils

OPEN_STATES = ("Open", "Awaiting Return", "Received", "Inspected")
TERMINAL_STATES = ("Replaced", "Refunded", "Scrapped", "Closed")
DISPOSAL_STATES = ("Replaced", "Refunded", "Scrapped")

# Device states a unit may enter an RMA from (`21` §6 before_submit).
RMA_ELIGIBLE_DEVICE_STATES = ("Faulty", "Active", "Returned")

STATUS_ROLE = {
	"Open": ("BARO Support Agent", "BARO Installer", "BARO Service Supervisor", "BARO System Manager"),
	"Awaiting Return": ("BARO Support Agent", "BARO Service Supervisor", "BARO System Manager"),
	"Received": ("BARO Stock Manager", "BARO Service Supervisor", "BARO System Manager"),
	"Inspected": ("BARO Stock Manager", "BARO Service Supervisor", "BARO System Manager"),
	"Replaced": ("BARO Stock Manager", "BARO Approver", "BARO System Manager"),
	"Refunded": ("BARO Stock Manager", "BARO Approver", "BARO Finance Approver", "BARO System Manager"),
	"Scrapped": ("BARO Approver", "BARO System Manager"),
	"Closed": ("BARO Service Supervisor", "BARO Approver", "BARO System Manager"),
}

PRE_RMA_TAG = "pre_rma_status:"


class BaroDeviceRMA(Document):
	def validate(self):
		self.assert_device_exists()
		self.assert_single_open_rma()
		self.assert_customer_matches()
		self.assert_warranty_type()
		self.assert_replacement_is_different()
		self.assert_status_change_allowed()
		self.assert_disposition_roles()

	def assert_device_exists(self):
		if not frappe.db.exists("Serial No", self.serial_no):
			frappe.throw(_("Serial {0} does not exist").format(self.serial_no))

	def assert_single_open_rma(self):
		clash = frappe.db.get_all(
			"Baro Device RMA",
			filters={
				"serial_no": self.serial_no,
				"baro_rma_status": ["in", OPEN_STATES],
				"docstatus": ["!=", 2],
			},
			pluck="name",
			limit=2,
		)
		clash = [n for n in clash if n != self.name]
		if clash:
			frappe.throw(
				_("RMA {0} is already open for this device").format(clash[0]),
				frappe.DuplicateEntryError,
			)

	def assert_customer_matches(self):
		owners = {
			frappe.db.get_value("Serial No", self.serial_no, "customer"),
			frappe.db.get_value(
				"Baro Device Assignment",
				{"serial_no": self.serial_no, "docstatus": 1, "baro_status": "Active"},
				"customer",
			),
		}
		owners.discard(None)
		if owners and self.customer not in owners:
			frappe.throw(_("Customer mismatch"))

	def assert_warranty_type(self):
		if self.baro_rma_type != "In-warranty":
			return
		expiry = frappe.db.get_value("Serial No", self.serial_no, "warranty_expiry_date")
		if not expiry or getdate(expiry) < getdate(self.creation or nowdate()):
			if settings.get("baro_warranty_override_allowed") and frappe.has_permission(
				"Baro Device RMA", "submit"
			) and "BARO Approver" in frappe.get_roles():
				self.remember_override(expiry)
				return
			frappe.throw(
				_("Warranty expired on {0}; choose Out-of-warranty or get approval").format(expiry)
			)

	def remember_override(self, expiry):
		tag = f"warranty_override:{expiry or 'unknown'}"
		if tag not in (self.baro_notes or ""):
			self.baro_notes = f"{self.baro_notes or ''}\n{tag}".strip()

	def assert_replacement_is_different(self):
		if self.baro_replacement_serial and self.baro_replacement_serial == self.serial_no:
			frappe.throw(_("Replacement must be a different unit"))

	def assert_status_change_allowed(self):
		if self.is_new():
			self.baro_rma_status = self.baro_rma_status or "Open"
			return
		previous = frappe.db.get_value("Baro Device RMA", self.name, "baro_rma_status")
		if previous == self.baro_rma_status:
			return
		allowed = STATUS_ROLE.get(self.baro_rma_status, ())
		if not any(utils.has_role(role) for role in allowed):
			frappe.throw(
				_("Transition {0} -> {1} requires one of: {2}").format(
					previous, self.baro_rma_status, ", ".join(allowed)
				)
			)
		if previous in TERMINAL_STATES:
			frappe.throw(_("RMA {0} is {1} and cannot be reopened").format(self.name, previous))

	def assert_disposition_roles(self):
		if self.baro_disposition in ("Scrap", "Refund") and not (
			utils.has_role("BARO Approver") or utils.has_role("BARO System Manager")
		):
			frappe.throw(_("Scrap and Refund dispositions require a BARO Approver"))

	def before_submit(self):
		self.assert_device_state_for_submit()
		self.remember_pre_rma_status()

	def assert_device_state_for_submit(self):
		status = frappe.db.get_value("Serial No", self.serial_no, "baro_device_status")
		if status not in RMA_ELIGIBLE_DEVICE_STATES:
			frappe.throw(_("Device is {0}").format(status or "Unset"))

	def remember_pre_rma_status(self):
		status = frappe.db.get_value("Serial No", self.serial_no, "baro_device_status")
		tag = f"{PRE_RMA_TAG}{status}"
		if PRE_RMA_TAG not in (self.baro_notes or ""):
			self.baro_notes = f"{self.baro_notes or ''}\n{tag}".strip()

	def on_submit(self):
		derive.set_device_status(self.serial_no, "RMA")

	def on_update_after_submit(self):
		if self.baro_rma_status not in DISPOSAL_STATES:
			return
		if self.baro_rma_status == "Replaced":
			self.apply_replacement()
		if self.baro_rma_status == "Scrapped":
			self.assert_scrappable()

	def apply_replacement(self):
		if not self.baro_replacement_serial:
			frappe.throw(_("A replacement RMA must name the replacement device"))
		self.link_assignments()

	def link_assignments(self):
		"""DRV links: the old Active assignment is named here; the Supervisor creates the new one."""
		if not self.baro_old_assignment:
			self.baro_old_assignment = frappe.db.get_value(
				"Baro Device Assignment",
				{"serial_no": self.serial_no, "docstatus": 1, "baro_status": "Active"},
				"name",
			)
		if self.baro_old_assignment:
			derive.supersede_assignment(self.baro_old_assignment, self.baro_new_assignment)
		if not self.baro_new_assignment:
			self.baro_new_assignment = frappe.db.get_value(
				"Baro Device Assignment",
				{"serial_no": self.baro_replacement_serial, "docstatus": 1},
				"name",
				order_by="from_time desc",
			)

	def assert_scrappable(self):
		active = frappe.db.get_value(
			"Baro Device Assignment",
			{"serial_no": self.serial_no, "docstatus": 1, "baro_status": "Active"},
			"name",
		)
		if active:
			frappe.throw(_("Device {0} still has an active assignment").format(self.serial_no))

	def on_cancel(self):
		derive.set_device_status(self.serial_no, self.pre_rma_status() or "Returned")
		if self.baro_rma_status in DISPOSAL_STATES:
			frappe.throw(_("Cancel is not valid once a disposition has been recorded; amend instead"))

	def pre_rma_status(self):
		for line in (self.baro_notes or "").splitlines():
			line = line.strip()
			if line.startswith(PRE_RMA_TAG):
				value = line[len(PRE_RMA_TAG):].strip()
				return None if value in ("None", "") else value
		return None

# Copyright (c) 2026 BARO Group
# License: MIT. See license.txt
"""`Baro Reconciliation Exception` — the human inbox behind the three-way diff (`51`).

Two invariants make this table usable rather than noisy, and both are code, not policy:

* **Detection is not action.** Resolving or waiving a row writes no other DocType. The
  corrective edit happens on the real document, under its own workflow (`40` §1).
* **The bot cannot close its own findings.** `BARO Integrator` may create and annotate rows
  but may never set `Resolved` or `Waived` (`41` §3). Because Frappe's `read_only` is a UI
  property and permlevel would hide the column from the readers who need it, this rule is a
  server-side role check in `validate`.
"""

import frappe
from frappe.model.document import Document
from frappe import _

from baro_core import exceptions, settings, utils

OPEN = "Open"
ACKNOWLEDGED = "Acknowledged"
IN_PROGRESS = "In Progress"
RESOLVED = "Resolved"
WAIVED = "Waived"

FORWARD = {
	OPEN: {ACKNOWLEDGED, IN_PROGRESS, RESOLVED, WAIVED},
	ACKNOWLEDGED: {IN_PROGRESS, RESOLVED, WAIVED},
	IN_PROGRESS: {RESOLVED, WAIVED, ACKNOWLEDGED},
	RESOLVED: set(),
	WAIVED: set(),
}

BILLABLE_TYPES = ("Billing mismatch", "ERP-only")

CLOSING_ROLES = {
	"ERP-only": ("BARO Stock Manager", "BARO Service Supervisor", "BARO Approver", "BARO System Manager"),
	"Platform-only": ("BARO Stock Manager", "BARO Service Supervisor", "BARO Approver", "BARO System Manager"),
	"Mapping missing": ("BARO Stock Manager", "BARO Approver", "BARO System Manager"),
	"State mismatch": ("BARO Service Supervisor", "BARO Connectivity Admin", "BARO Approver", "BARO System Manager"),
	"Billing mismatch": ("BARO Accounts User", "BARO Approver", "BARO Finance Approver", "BARO System Manager"),
	"Duplicate active device": ("BARO Fleet Officer", "BARO Service Supervisor", "BARO Approver", "BARO System Manager"),
	"Count mismatch": ("BARO Service Supervisor", "BARO Approver", "BARO System Manager"),
}


class BaroReconciliationException(Document):
	def validate(self):
		self.stamp_detection()
		self.resolve_customer()
		self.assert_closing_authorised()
		self.assert_waive_evidence()
		self.assert_marked_resolved()

	def stamp_detection(self):
		if not self.baro_detected_at:
			self.baro_detected_at = frappe.utils.now()

	def resolve_customer(self):
		"""FF-equivalent for a row that may reference a vehicle, a device, or neither."""
		if self.customer:
			return
		self.customer = (
			(self.baro_vehicle and frappe.db.get_value("Baro Vehicle", self.baro_vehicle, "customer"))
			or (self.serial_no and frappe.db.get_value("Serial No", self.serial_no, "customer"))
			or None
		)

	def assert_closing_authorised(self):
		if self.is_new():
			return
		previous = frappe.db.get_value("Baro Reconciliation Exception", self.name, "baro_status")
		if previous == self.baro_status:
			return
		if utils.is_integrator() and self.baro_status in (RESOLVED, WAIVED):
			exceptions.integrator_may_not_resolve()
		if self.baro_status not in FORWARD.get(previous, set()):
			frappe.throw(_("{0} cannot move from {1} to {2}").format(self.name, previous, self.baro_status))
		if self.baro_status in (RESOLVED, WAIVED):
			roles = CLOSING_ROLES.get(self.baro_exception_type, ())
			if not any(utils.has_role(role) for role in roles):
				frappe.throw(
					_("Closing a {0} exception requires one of: {1}").format(
						self.baro_exception_type, ", ".join(roles)
					)
				)

	def assert_waive_evidence(self):
		if self.baro_status == WAIVED:
			if not (self.baro_waive_reason or "").strip():
				frappe.throw(_("Waiving an exception requires a reason"))
			if not (utils.has_role("BARO Approver") or utils.has_role("BARO System Manager")):
				frappe.throw(_("Only a BARO Approver may waive an exception"))
		if self.baro_status == RESOLVED and not (self.baro_resolution_notes or "").strip():
			frappe.throw(_("Resolving an exception requires a note describing the fix"))

	def assert_marked_resolved(self):
		if self.baro_status in (RESOLVED, WAIVED) and not self.baro_resolved_at:
			self.baro_resolved_at = frappe.utils.now()

	def before_insert(self):
		self.baro_impact_billable = 1 if self.baro_exception_type in BILLABLE_TYPES else 0
		if not self.baro_status:
			self.baro_status = OPEN
		if int(settings.get("baro_count_alert_threshold") or 0) and self.baro_exception_type == "Count mismatch":
			self.baro_assigned_role = "BARO Approver"

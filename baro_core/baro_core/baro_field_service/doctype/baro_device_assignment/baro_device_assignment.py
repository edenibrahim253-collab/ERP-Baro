"""`Baro Device Assignment` - the spine's authority record.

Owns its own state here; effects on other DocTypes are registered as `doc_events` handlers
(`baro_core.handlers.assignment`) so the connector, Data Import and the UI all reach the same
code (docs/30-schema-conventions.md #1).

Three enforcement layers, and the reason each exists (docs/31):
1. `validate` - friendly duplicate checks so a human gets a named message;
2. UQ-DRV unique index - the database's answer to "one Active per device/vehicle";
3. `before_submit` under a named lock + `SELECT ... FOR UPDATE` - the only thing that can
   express "no two time windows overlap", which no index can.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, now_datetime

from baro_core import derive, locks, settings, utils
from baro_core.exceptions import overlap, self_approval_forbidden

APPROVE_ROLES = ("BARO Approver", "BARO System Manager")
SUBMIT_ROLES = ("BARO Service Supervisor", "BARO Approver", "BARO System Manager")
LIVE_STATUSES = ("Active", "Ended", "Superseded")


class BaroDeviceAssignment(Document):
	def validate(self):
		self.set_default_company()
		self.validate_customer_matches_vehicle()
		self.validate_device_is_gps_unit()
		self.validate_device_issuable()
		self.validate_device_reservation_belongs_to_customer()
		self.validate_customer_not_blocked()
		self.validate_window()
		self.validate_assignment_type()
		self.validate_sim_not_double_installed()
		self.validate_previous_assignment()
		self.validate_workflow_only_fields()
		# Layer 1 of docs/31: a readable failure before the index raises an opaque one.
		self.warn_existing_active()
		derive.set_active_keys(self)

	def before_submit(self):
		"""Layer 3: lock, then read, then check, then let the index have the last word."""
		with locks.acquired(derive_lock_keys(self)):
			self.lock_source_rows()
			self.assert_no_overlap()
			derive.set_active_keys(self)

	def before_cancel(self):
		self.assert_cancellable()

	def on_update_after_submit(self):
		"""`to_time` and status changes are on-submit edits and must re-run the same checks."""
		if self.has_value_changed("to_time") or self.has_value_changed("baro_status"):
			with locks.acquired(derive_lock_keys(self)):
				self.lock_source_rows()
				self.assert_no_overlap()
				derive.set_active_keys(self)
				self.save(ignore_permissions=True)

	# --- validation rules (docs/21 #2) -------------------------------------------------

	def set_default_company(self):
		if not self.company:
			self.company = frappe.db.get_value("Baro Vehicle", self.baro_vehicle, "company")
		if not self.company:
			frappe.throw(_("Company is required"))

	def validate_customer_matches_vehicle(self):
		owner = frappe.db.get_value("Baro Vehicle", self.baro_vehicle, "customer")
		if owner and self.customer != owner:
			frappe.throw(
				_("Vehicle {0} belongs to {1}; the assignment customer must match").format(
					self.baro_vehicle, owner
				)
			)

	def validate_device_is_gps_unit(self):
		item_code = frappe.db.get_value("Serial No", self.serial_no, "item_code")
		item_group = frappe.db.get_value("Item", item_code, "item_group")
		if not settings.is_device_item_group(item_group):
			frappe.throw(_("Serial {0} is not a GPS device item").format(self.serial_no))

	def validate_device_issuable(self):
		status = frappe.db.get_value("Serial No", self.serial_no, "baro_device_status")
		if status not in derive.ISSUABLE_DEVICE_STATES:
			frappe.throw(
				_("Device {0} is {1} and cannot be assigned").format(self.serial_no, status or _("unregistered"))
			)

	def validate_device_reservation_belongs_to_customer(self):
		reserved_for = frappe.db.get_value("Serial No", self.serial_no, "customer")
		if reserved_for and reserved_for != self.customer:
			frappe.throw(
				_("Device {0} is reserved for {1}").format(self.serial_no, reserved_for)
			)

	def validate_customer_not_blocked(self):
		blocked = frappe.db.get_value(
			"Customer", self.customer, ["on_hold", "is_frozen", "disabled"], as_dict=True
		)
		if blocked and any((blocked.get("on_hold"), blocked.get("is_frozen"), blocked.get("disabled"))):
			frappe.throw(_("Customer {0} is blocked; clear the hold before assigning").format(self.customer))

	def validate_window(self):
		if not self.from_time:
			frappe.throw(_("Active From is required"))
		limit = settings.int_value("baro_assignment_future_days")
		horizon = add_days(now_datetime(), limit)
		if frappe.utils.get_datetime(self.from_time) > horizon:
			frappe.throw(
				_("Active From may not be more than {0} day(s) ahead of today").format(limit)
			)
		if self.to_time and frappe.utils.get_datetime(self.to_time) <= frappe.utils.get_datetime(self.from_time):
			frappe.throw(_("Active To must be after Active From"))

	def validate_assignment_type(self):
		if self.baro_assignment_type == "Replacement" and not self.baro_previous_assignment:
			frappe.throw(_("A replacement must reference the assignment it replaces"))

	def validate_sim_not_double_installed(self):
		if not self.baro_sim_card:
			return
		installed_in = frappe.db.get_value("Baro SIM Card", self.baro_sim_card, "baro_installed_device")
		if installed_in and installed_in != self.serial_no:
			frappe.throw(
				_("SIM {0} is installed in {1}").format(
					frappe.db.get_value("Baro SIM Card", self.baro_sim_card, "baro_iccid"), installed_in
				)
			)

	def validate_previous_assignment(self):
		previous = self.baro_previous_assignment
		if not previous:
			return
		previous_to = frappe.db.get_value("Baro Device Assignment", previous, "to_time")
		if previous_to and frappe.utils.get_datetime(previous_to) > frappe.utils.get_datetime(self.from_time):
			frappe.throw(_("Overlaps the assignment being replaced"))

	def validate_workflow_only_fields(self):
		"""`baro_status` / `baro_activation_status` move only through a Workflow transition."""
		if self.is_new() or self.flags.ignore_workflow_checks:
			return
		if self.has_value_changed("baro_status") and self.baro_status in ("Active", "Superseded"):
			if not set(APPROVE_ROLES) & set(frappe.get_roles()):
				frappe.throw(_("Only an approver may move this assignment to {0}").format(self.baro_status))
			if self.owner == frappe.session.user:
				self_approval_forbidden()
		if self.has_value_changed("baro_activation_status") and not derive_activation_write_allowed():
			frappe.throw(
				_("Platform Activation is written by the activation-verification step, not by the installer")
			)

	def warn_existing_active(self):
		for field, value in (("serial_no", self.serial_no), ("baro_vehicle", self.baro_vehicle)):
			existing = frappe.db.get_value(
				"Baro Device Assignment",
				{field: value, "docstatus": 1, "baro_status": derive.ACTIVE, "name": ("!=", self.name)},
				"name",
			)
			if existing:
				frappe.throw(
					_("{0} {1} already has an Active assignment ({2}). End it first.").format(
						utils.key_label(field), value, existing
					),
					frappe.DuplicateEntryError,
				)

	# --- overlap (docs/31 #5) ----------------------------------------------------------

	def lock_source_rows(self):
		"""Row-lock the device record so a concurrent stock move cannot interleave with this submit."""
		frappe.db.sql("SELECT name FROM `tabSerial No` WHERE name = %s FOR UPDATE", (self.serial_no,))

	def assert_no_overlap(self):
		for key_field in ("serial_no", "baro_vehicle"):
			value = self.get(key_field)
			if not value:
				continue
			rows = frappe.db.sql(
				"""
				select name, from_time, to_time, baro_vehicle
				from `tabBaro Device Assignment`
				where {kf} = %s
				  and docstatus = 1
				  and baro_status in ('Active', 'Ended', 'Superseded')
				  and name != %s
				  and (to_time is null or to_time > %s)
				  and from_time < coalesce(%s, '2999-12-31 23:59:59')
				for update""".format(kf=key_field),
				(value, self.name or "", self.from_time, self.to_time or self.from_time),
				as_dict=1,
			)
			if rows:
				conflict = rows[0]
				overlap(
					utils.key_label(key_field),
					value,
					conflict.name,
					conflict.baro_vehicle or "",
					conflict.from_time,
				)

	# --- cancellation (docs/21 #2 last row) -------------------------------------------

	def assert_cancellable(self):
		if self.baro_activation_status != "Not Verified":
			derive_reason = _("the device activation was already verified")
		elif frappe.db.exists("Installation Note", {"baro_assignment": self.name, "docstatus": 1}):
			derive_reason = _("a submitted Installation Note depends on it")
		elif self.consumed_billing_period():
			derive_reason = _("a billing period has already been consumed")
		else:
			return
		frappe.throw(
			_("Assignment {0} has produced service or billing history ({1}); amend it instead of cancelling").format(
				self.name, derive_reason
			)
		)

	def consumed_billing_period(self) -> bool:
		return bool(
			frappe.db.exists(
				"Sales Invoice",
				{"customer": self.customer, "subscription": ("is", "set"), "docstatus": 1},
			)
			and frappe.db.sql(
				"""
				select si.name
				from `tabSales Invoice` si
				join `tabSubscription` s on s.name = si.subscription
				where si.customer = %s and si.docstatus = 1
				  and s.end_date >= %s
				limit 1""",
				(self.customer, self.from_time),
			)
		)

	def approval_task_subject(self) -> str:
		plate = frappe.db.get_value("Baro Vehicle", self.baro_vehicle, "baro_plate_no")
		return _("Verify activation - {0}").format(plate or self.baro_vehicle)

	def activation_sla_end(self):
		return add_days(self.from_time, settings.int_value("baro_activation_sla_days"))


def derive_lock_keys(doc) -> list[str]:
	return locks.assignment_keys(doc.serial_no, doc.baro_vehicle)


def derive_activation_write_allowed() -> bool:
	"""The connector path or a supervisor may set Platform Activation - never the installer."""
	roles = set(frappe.get_roles())
	return bool({"BARO Integrator", "BARO Service Supervisor", "BARO System Manager"} & roles)

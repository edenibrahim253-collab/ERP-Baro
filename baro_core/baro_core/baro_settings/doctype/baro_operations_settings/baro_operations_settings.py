# Copyright (c) 2026 BARO Group
# License: MIT. See license.txt
"""`Baro Operations Settings` — the Single that keeps every threshold out of code (`21`/`31`/`60`).

Validation here is strict on purpose: a broken plate regex silently rejects valid registrations,
and an empty device Item Group list silently turns "is this serial a device?" into "no". Both
failures look like data problems downstream, so they are stopped at the point of entry.
"""

import re

import frappe
from frappe.model.document import Document
from frappe import _

POSITIVE_INTS = (
	"baro_activation_sla_days",
	"baro_expiry_notice_days",
	"baro_cert_notice_days",
	"baro_inactive_threshold_hours",
	"baro_log_retention_days",
	"baro_max_rows_per_run",
	"baro_count_alert_threshold",
)
NON_NEGATIVE_INTS = ("baro_assignment_future_days",)


class BaroOperationsSettings(Document):
	def validate(self):
		self.validate_patterns()
		self.validate_device_groups()
		self.validate_numbers()
		self.normalize()

	def validate_patterns(self):
		for field in ("baro_plate_pattern", "baro_msisdn_pattern"):
			pattern = (self.get(field) or "").strip()
			if not pattern:
				frappe.throw(_("{0} is required").format(self.meta.get_label(field)))
			try:
				compiled = re.compile(pattern)
			except re.error as error:
				frappe.throw(_("{0} is not a valid regular expression: {1}").format(self.meta.get_label(field), error))
			if compiled.groups > 0:
				frappe.throw(
					_("{0} must not use capture groups; the value is matched, not parsed").format(
						self.meta.get_label(field)
					)
				)

	def validate_device_groups(self):
		rows = [r for r in (self.baro_device_item_groups or []) if r.item_group]
		if not rows:
			frappe.throw(
				_("Select at least one GPS Device Item Group. Without it no serial can be assigned.")
			)
		groups = {r.item_group for r in rows}
		if len(groups) != len(rows):
			frappe.throw(_("Device Item Groups must not repeat"))
		missing = [g for g in groups if not frappe.db.exists("Item Group", g)]
		if missing:
			frappe.throw(_("Unknown Item Group(s): {0}").format(", ".join(sorted(missing))))

	def validate_numbers(self):
		for field in POSITIVE_INTS:
			if int(self.get(field) or 0) < 1:
				frappe.throw(_("{0} must be at least 1").format(self.meta.get_label(field)))
		for field in NON_NEGATIVE_INTS:
			if int(self.get(field) or 0) < 0:
				frappe.throw(_("{0} cannot be negative").format(self.meta.get_label(field)))

	def normalize(self):
		for field in ("baro_plate_pattern", "baro_msisdn_pattern", "baro_reorder_notice_role", "baro_reconciliation_cron"):
			value = self.get(field)
			if isinstance(value, str):
				self.set(field, value.strip())

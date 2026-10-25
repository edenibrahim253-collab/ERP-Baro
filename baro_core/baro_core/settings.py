"""Single access point for `Baro Operations Settings`.

No rule in the app hard-codes a number or a pattern (docs/10-data-dictionary.md #4.9). Every
threshold, regex and notice window is read here, so an answer to a stakeholder question in
docs/70 becomes a settings change rather than a code change.
"""

import re

import frappe

DEFAULTS = {
	"baro_plate_pattern": r"^[A-Z0-9]{1,12}$",
	"baro_msisdn_pattern": r"^\+?\d{9,15}$",
	"baro_assignment_future_days": 0,
	"baro_activation_sla_days": 2,
	"baro_expiry_notice_days": 30,
	"baro_cert_notice_days": 30,
	"baro_inactive_threshold_hours": 24,
	"baro_log_retention_days": 90,
	"baro_normalise_identifiers": 1,
	"baro_reconciliation_cron": "Daily",
	"baro_max_rows_per_run": 20000,
	"baro_count_alert_threshold": 5,
	"baro_reorder_notice_role": "BARO Stock Manager",
	"baro_warranty_override_allowed": 0,
}


def get(key: str, default=None):
	"""Read one settings field, falling back to DEFAULTS when the Single has no value yet."""
	if default is None:
		default = DEFAULTS.get(key)
	single = frappe.get_doc("Baro Operations Settings")
	value = single.get(key)
	if value in (None, ""):
		return default
	return value


def int_value(key: str) -> int:
	return int(get(key) or 0)


def pattern(key: str) -> re.Pattern:
	return re.compile(get(key), re.UNICODE)


def matches(key: str, value: str) -> bool:
	if not value:
		return False
	return pattern(key).match(value) is not None


def device_item_groups() -> list[str]:
	"""Item Groups that make a serial a GPS device - and therefore require an IMEI."""
	rows = frappe.get_all(
		"Baro Device Item Group Reference", filters={"parent": "Baro Operations Settings"}, pluck="item_group"
	)
	return list(dict.fromkeys(rows or []))


def is_device_item_group(item_group: str | None) -> bool:
	return bool(item_group) and item_group in device_item_groups()

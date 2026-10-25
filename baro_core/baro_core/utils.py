"""Identifier normalisation and checksums.

A unique index on un-normalised text guarantees nothing (docs/31-uniqueness-concurrency-design.md #3),
so every externally-assigned identifier passes through here before validation, before the
index compares it, and before it reaches a reconciliation match key. "Not provided" is stored
as NULL, never "" - an empty string is a value and collides.
"""

import re

import frappe

SEPARATORS = re.compile(r"[\s\-_/().]")


def normalise_identifier(value: str | None, *, upper: bool = True, keep_plus: bool = False) -> str | None:
	"""Strip separators, optionally uppercase. Returns None for blank input."""
	if value is None:
		return None
	out = SEPARATORS.sub("", str(value).strip())
	if keep_plus:
		out = ("+" + out.lstrip("+")) if out.startswith("+") else out
	else:
		out = out.lstrip("+")
	if upper:
		out = out.upper()
	return out or None


def digits(value: str | None) -> str | None:
	"""Digits only - IMEI and ICCID are numeric by definition."""
	if value is None:
		return None
	out = re.sub(r"\D", "", str(value))
	return out or None


def luhn_valid(number: str | None) -> bool:
	"""ISO 7064 mod-10. Used for IMEI (15 digits, last is the check digit) and ICCID."""
	if not number or not number.isdigit():
		return False
	total = 0
	for index, char in enumerate(reversed(number)):
		digit = int(char)
		if index % 2 == 1:
			digit *= 2
			digit -= 9 if digit > 9 else 0
		total += digit
	return total % 10 == 0


def imei(value: str | None) -> str | None:
	"""15 digits or None. A 14-digit input is not an IMEI and must not be silently padded."""
	d = digits(value)
	return d if d and len(d) == 15 else None


def iccid(value: str | None) -> str | None:
	d = digits(value)
	return d if d and 19 <= len(d) <= 20 else None


def msisdn(value: str | None) -> str | None:
	"""Keeps a leading + (national vs international matters to a telco) but nothing else."""
	if value is None:
		return None
	out = SEPARATORS.sub("", str(value).strip())
	leading_plus = out.startswith("+")
	out = re.sub(r"\D", "", out)
	if not out:
		return None
	return ("+" + out) if leading_plus else out


def plate(value: str | None) -> str | None:
	return normalise_identifier(value)


def scrub_null(value):
	"""Frappe stores "" for cleared Data fields; a unique index treats "" as a value."""
	return None if value in ("", "None") else value


def is_integrator() -> bool:
	return "BARO Integrator" in frappe.get_roles(frappe.session.user)


def has_role(role: str) -> bool:
	"""One role test for the whole app.

	`frappe.get_roles()` is the documented API and is version-stable; the framework's own
	`frappe.has_role` shortcut is not something BARO rules should depend on (`04` §4).
	"""
	return role in frappe.get_roles(frappe.session.user)


def key_label(fieldname: str) -> str:
	return {
		"serial_no": frappe._("Device"),
		"baro_vehicle": frappe._("Vehicle"),
	}.get(fieldname, fieldname)

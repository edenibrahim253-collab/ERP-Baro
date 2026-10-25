# Copyright (c) 2026 BARO Group
# License: MIT. See license.txt
"""Row-level access (`41` §5). Client scripts are cosmetic; this is the enforcement.

Three deliberate choices:

* **Fail closed.** A technician or branch user with no `User Permission` rows sees nothing,
  rather than the whole fleet. Silent cross-branch visibility is the defect `41` §5.1 names as
  the most common way a "role-based" ERP leaks data.
* **The bot is unrestricted.** `BARO Integrator` must write mappings and logs for every
  customer, so no condition is applied to it (`41` §5.2) - and it has no Submit right anywhere.
* **Own drafts stay visible.** A row filter that hides a user's own unsaved work makes the
  installer's queue unusable, so the conditions always union in `owner = <user>`.

Frappe applies link-based `User Permission` scoping on its own once `apply_user_permissions` is
enabled on the DocType (shipped as a Property Setter fixture); these conditions add what link
scoping cannot express - the technician's own jobs and the exception queue's role routing.
"""

import frappe

UNRESTRICTED = (
	"BARO System Manager",
	"BARO Integrator",
	"BARO Report Viewer",
	"BARO Approver",
)

TECHNICIAN_ROLES = ("BARO Installer",)


def _roles(user: str) -> set[str]:
	return set(frappe.get_roles(user))


def _employee_of(user: str) -> str | None:
	return frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "name")


def _skip(user: str | None) -> bool:
	if not user or user == "Administrator":
		return True
	return bool(_roles(user) & set(UNRESTRICTED))


def _in(field: str, values) -> str:
	quoted = ", ".join(frappe.db.escape(v) for v in values)
	return f"coalesce({field},'') in ({quoted})"


def _none(field: str) -> str:
	"""Fail-closed condition for a scoped role that has no scope configured."""
	return f"coalesce({field},'') = '.__none__'"


def _scoped_customers(user: str, doctype: str) -> list[str] | None:
	"""Customers this user may see, from `User Permission`; None means "not restricted"."""
	rows = frappe.get_all(
		"User Permission",
		filters={"user": user, "allow": "Customer"},
		pluck="for_value",
	)
	if rows:
		return list(dict.fromkeys(rows))
	if _roles(user) & set(TECHNICIAN_ROLES):
		return []
	return None


def vehicle_query(user: str | None = None) -> str | None:
	if _skip(user):
		return None
	customers = _scoped_customers(user, "Baro Vehicle")
	if customers is None:
		return None
	if not customers:
		# A technician with no assignments yet sees the fleet through their own jobs only.
		employee = _employee_of(user)
		if not employee:
			return _none("`tabBaro Vehicle`.customer")
		return (
			"`tabBaro Vehicle`.customer in (select distinct customer from `tabBaro Device Assignment` "
			f"where baro_technician = {frappe.db.escape(employee)})"
		)
	return _in("`tabBaro Vehicle`.customer", customers) + f" or `tabBaro Vehicle`.owner = {frappe.db.escape(user)}"


def assignment_query(user: str | None = None) -> str | None:
	if _skip(user):
		return None
	roles = _roles(user)
	employee = _employee_of(user)
	if roles & set(TECHNICIAN_ROLES) and employee:
		return (
			f"`tabBaro Device Assignment`.baro_technician = {frappe.db.escape(employee)}"
			f" or `tabBaro Device Assignment`.owner = {frappe.db.escape(user)}"
		)
	customers = _scoped_customers(user, "Baro Device Assignment")
	if customers is None:
		return None
	if not customers:
		return _none("`tabBaro Device Assignment`.customer")
	return _in("`tabBaro Device Assignment`.customer", customers) + (
		f" or `tabBaro Device Assignment`.owner = {frappe.db.escape(user)}"
	)


def sim_query(user: str | None = None) -> str | None:
	"""A SIM has no customer field; its scope follows the vehicle it is installed in."""
	if _skip(user):
		return None
	customers = _scoped_customers(user, "Baro SIM Card")
	if customers is None:
		return None
	if not customers:
		return _none("`tabBaro SIM Card`.name")
	in_list = ", ".join(frappe.db.escape(c) for c in customers)
	return (
		"ifnull(`tabBaro SIM Card`.baro_installed_vehicle,'') in "
		f"(select name from `tabBaro Vehicle` where customer in ({in_list}))"
		f" or `tabBaro SIM Card`.owner = {frappe.db.escape(user)}"
	)


def exception_query(user: str | None = None) -> str | None:
	"""Each role sees its own queue; Approver and System Manager see all (`41` §5.3)."""
	if _skip(user):
		return None
	roles = _roles(user)
	if "BARO Service Supervisor" in roles or "BARO Finance Approver" in roles:
		return None
	allowed = sorted(roles & _EXCEPTION_ROLES)
	if not allowed:
		return _none("`tabBaro Reconciliation Exception`.baro_assigned_role")
	return _in("`tabBaro Reconciliation Exception`.baro_assigned_role", allowed)


_EXCEPTION_ROLES = frozenset(
	{
		"BARO Integrator",
		"BARO Stock Manager",
		"BARO Service Supervisor",
		"BARO Connectivity Admin",
		"BARO Accounts User",
		"BARO Approver",
	}
)


def serial_query(user: str | None = None) -> str | None:
	"""Devices follow their customer, so scoping rides on the assignment and vehicle rows."""
	if _skip(user):
		return None
	customers = _scoped_customers(user, "Serial No")
	if customers is None:
		return None
	if not customers:
		return _none("`tabSerial No`.customer")
	return _in("`tabSerial No`.customer", customers) + f" or `tabSerial No`.owner = {frappe.db.escape(user)}"


def has_vehicle_permission(doc, ptype: str, user: str | None = None) -> bool:
	return _party_allowed(doc, user, "customer")


def has_assignment_permission(doc, ptype: str, user: str | None = None) -> bool:
	if ptype != "read" and _skip(user):
		return True
	if _roles(user or frappe.session.user) & set(TECHNICIAN_ROLES):
		employee = _employee_of(user or frappe.session.user)
		if employee and doc.baro_technician == employee:
			return True
		if doc.owner == (user or frappe.session.user):
			return True
	return _party_allowed(doc, user, "customer")


def has_exception_permission(doc, ptype: str, user: str | None = None) -> bool:
	user = user or frappe.session.user
	if _skip(user):
		return True
	roles = _roles(user)
	if roles & {"BARO Service Supervisor", "BARO Finance Approver"}:
		return True
	return bool(roles & {doc.baro_assigned_role})


def _party_allowed(doc, user: str | None, field: str) -> bool:
	user = user or frappe.session.user
	if _skip(user):
		return True
	customers = _scoped_customers(user, doc.doctype)
	if customers is None:
		return True
	value = getattr(doc, field, None)
	if doc.owner == user:
		return True
	return bool(value) and value in customers

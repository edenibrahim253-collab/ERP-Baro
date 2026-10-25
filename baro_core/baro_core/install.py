"""Install-time setup for baro_core.

Creates only the site-level prerequisites the fixtures assume: the BARO Item Group
structure hint, and the `BARO Integrator` service-user guard. Everything else arrives as a
fixture in the deterministic order declared in hooks.py (docs/30-schema-conventions.md #8).
"""

import frappe

# Roles created by fixtures/role.json; asserted here so a partial import fails loudly
# at install rather than silently at first permission check.
REQUIRED_ROLES = [
	"BARO Sales Officer",
	"BARO Fleet Officer",
	"BARO Installer",
	"BARO Service Supervisor",
	"BARO Approver",
	"BARO Stock Manager",
	"BARO Connectivity Admin",
	"BARO Support Agent",
	"BARO Accounts User",
	"BARO Finance Approver",
	"BARO Procurement Officer",
	"BARO Report Viewer",
	"BARO Integrator",
	"BARO System Manager",
]


def before_install():
	frappe.reload_doc("baro_settings", "doctype", "baro_operations_settings", force=True)
	for module in frappe.get_file_lines(frappe.get_app_path("baro_core", "modules.txt")):
		if module.strip():
			frappe.reload_doc(module.strip(), "module_def", module.strip(), force=True)


def after_install():
	missing = [r for r in REQUIRED_ROLES if not frappe.db.exists("Role", r)]
	if missing:
		frappe.log_error(
			title="BARO install: roles missing",
			message="Roles not present after fixtures ran: " + ", ".join(missing),
		)

	# The integrator bot must never hold submit on a business document
	# (docs/41-role-permission-matrix.md #7.2). Enforce it structurally, not by convention.
	bot = frappe.db.get_value("Role", "BARO Integrator", "name")
	if bot:
		for dt in (
			"Baro Device Assignment",
			"Baro SIM Card",
			"Baro Device RMA",
			"Installation Note",
			"Quality Inspection",
		):
			frappe.db.set_value(
				"DocPerm",
				frappe.get_all(
					"DocPerm", filters={"parent": dt, "role": "BARO Integrator", "submit": 1}, pluck="name"
				),
				"submit",
				0,
			)
	frappe.db.commit()

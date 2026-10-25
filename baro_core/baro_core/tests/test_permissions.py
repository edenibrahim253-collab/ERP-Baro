# Copyright (c) 2026 BARO Group
# License: MIT. See license.txt
"""Server-side and record-level permission proofs (`docs/41` §5, §7).

The design promise is that hiding a workspace link is *not* the control. These tests therefore ask
two questions only a server can answer: can this role write this document, and does a list query
for this user carry a row filter?

Written without a Python runtime available; `bench run-tests --app baro_core` is the first real
execution.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from baro_core import permissions

INTEGRATOR = "baro-bot@barogroup.example"
INSTALLER = "baro-tech@barogroup.example"


def service_user(email: str, role: str) -> str:
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": role.replace("BARO ", ""),
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)
	user = frappe.get_doc("User", email)
	if role not in [r.role for r in user.roles]:
		user.append("roles", {"role": role})
		user.save(ignore_permissions=True)
	return email


class TestPermissions(FrappeTestCase):
	def setUp(self):
		self.bot = service_user(INTEGRATOR, "BARO Integrator")
		self.tech = service_user(INSTALLER, "BARO Installer")

	def test_integrator_cannot_submit_anything(self):
		"""`docs/41` §7.2 and `install.py`: the bot detects and writes, it never approves."""
		for doctype in ("Baro Device Assignment", "Baro SIM Card", "Baro Device RMA", "Installation Note"):
			self.assertFalse(
				frappe.has_permission(doctype, ptype="submit", user=self.bot),
				f"{doctype} must not be submittable by the integration service",
			)

	def test_integrator_can_write_the_log(self):
		self.assertTrue(
			frappe.has_permission("Baro Integration Log", ptype="write", user=self.bot),
			"the log-first contract needs a writable log",
		)

	def test_integrator_cannot_mint_inventory(self):
		"""`docs/41` §5.4 / `docs/60` T14: an unmapped device is an exception, never a Serial No."""
		self.assertFalse(frappe.has_permission("Serial No", ptype="create", user=self.bot))

	def test_row_filter_is_fail_closed_for_an_unscoped_technician(self):
		"""No User Permission and no Employee record must mean "sees nothing", not "sees everything"."""
		clause = permissions.vehicle_query(self.tech)
		self.assertTrue(clause, "a technician must get a row filter at all")
		self.assertIn(".__none__", clause)

	def test_administrator_gets_no_extra_clause(self):
		self.assertIsNone(permissions.vehicle_query("Administrator"))
		self.assertIsNone(permissions.assignment_query("Administrator"))

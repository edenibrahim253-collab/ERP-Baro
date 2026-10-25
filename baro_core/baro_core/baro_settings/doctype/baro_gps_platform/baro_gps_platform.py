# Copyright (c) 2026 BARO Group
# License: MIT. See license.txt
"""`Baro GPS Platform` — per-platform endpoint, auth, limits and health (`21` §8).

Two permission facts shape this controller:

* Credentials sit at **permlevel 2** (`BARO System Manager` only) while connector-written
  health fields sit at **permlevel 1** (`BARO Integrator` + System Manager). They cannot share
  one level, because granting the bot level 1 would hand it the API secrets. `41` §3 states the
  outcome; the two levels are how it is achieved.
* `baro_enabled` off means *no* integration traffic: the scheduler skips the platform and new
  mappings are refused by `Baro Platform Mapping.validate`.
"""

import re

import frappe
from frappe.model.document import Document
from frappe import _

from baro_core import utils

HEALTH_FIELDS = ("baro_last_success_at", "baro_last_failure_at", "baro_last_error")
CONFIG_FIELDS = ("baro_base_url", "baro_auth_type", "baro_rate_limit_per_min", "baro_timeout_secs", "baro_max_retries")
MODULE_PATH = re.compile(r"^[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)+$")


class BaroGPSPlatform(Document):
	def validate(self):
		self.validate_base_url()
		self.validate_adapter_module()
		self.validate_limits()
		self.validate_credentials_when_enabled()
		self.assert_health_fields_written_by_integration()
		self.assert_config_change_authorised()

	def validate_base_url(self):
		url = (self.baro_base_url or "").strip()
		if not url.startswith("https://"):
			frappe.throw(_("API Base URL must be an https:// address"))
		self.baro_base_url = url.rstrip("/")

	def validate_adapter_module(self):
		module = (self.baro_adapter_module or "").strip()
		if not MODULE_PATH.match(module):
			frappe.throw(
				_("Connector Module must be a dotted python path, for example baro_core.integrations.vendor_x")
			)
		self.baro_adapter_module = module

	def validate_limits(self):
		for field, minimum, maximum in (
			("baro_rate_limit_per_min", 1, 10000),
			("baro_timeout_secs", 1, 300),
			("baro_max_retries", 0, 20),
		):
			value = int(self.get(field) or 0)
			if not minimum <= value <= maximum:
				frappe.throw(
					_("{0} must be between {1} and {2}").format(
						self.meta.get_label(field), minimum, maximum
					)
				)

	def validate_credentials_when_enabled(self):
		if not self.baro_enabled:
			return
		if self.baro_auth_type in ("API Key", "Bearer Token", "OAuth2") and not self.get_password("baro_api_key"):
			frappe.throw(_("An enabled platform needs an API key or token"))
		if self.baro_auth_type == "Basic" and not (
			self.get_password("baro_api_key") and self.get_password("baro_api_secret")
		):
			frappe.throw(_("Basic auth needs both a user key and a secret"))

	def assert_health_fields_written_by_integration(self):
		if self.is_new():
			return
		changed = set((self.get_changed() or {}).keys())
		affected = [f for f in HEALTH_FIELDS if f in changed]
		if not affected:
			return
		if frappe.session.user == "Administrator":
			return
		if not (utils.has_role("BARO Integrator") or utils.has_role("BARO System Manager")):
			frappe.throw(_("Only the integration service may update platform status"))
		if not utils.has_role("BARO Integrator"):
			self.log_manual_health_edit(affected)

	def log_manual_health_edit(self, fields):
		"""A human editing INT fields is legal for a System Manager but must be visible (`30` §7)."""
		notes = f"manual health edit {frappe.session.user}: {', '.join(fields)}"
		if notes not in (self.baro_notes or ""):
			self.baro_notes = f"{self.baro_notes or ''}\n{notes}".strip()

	def assert_config_change_authorised(self):
		if self.is_new():
			return
		previous = self.get_doc_before_save()
		if not previous:
			return
		changed = [f for f in CONFIG_FIELDS if getattr(previous, f, None) != getattr(self, f, None)]
		if changed and not (
			utils.has_role("BARO System Manager") or frappe.session.user == "Administrator"
		):
			frappe.throw(
				_("Editing {0} requires BARO System Manager").format(
					", ".join(self.meta.get_label(f) for f in changed)
				)
			)

	def on_update(self):
		if not self.baro_enabled:
			self.disable_pending_work()

	def disable_pending_work(self):
		"""Flag, do not delete: mappings and logs stay as evidence (`21` §8)."""
		for mapping in frappe.get_all(
			"Baro Platform Mapping", filters={"baro_platform": self.name, "baro_enabled": 1}, pluck="name", limit=500
		):
			frappe.db.set_value("Baro Platform Mapping", mapping, "baro_enabled", 0, update_modified=True)

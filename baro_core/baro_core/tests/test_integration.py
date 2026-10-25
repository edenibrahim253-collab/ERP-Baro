# Copyright (c) 2026 BARO Group
# License: MIT. See license.txt
"""The integration boundary: log-first, one retry ladder, deduped exceptions (`docs/50`, `docs/51`).

Written without a Python runtime available; `bench run-tests --app baro_core` is the first real
execution.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import get_datetime

from baro_core.integrations import base, payload, reconciliation, retry

COMPANY = "_Test Company"


def make_log(key: str, **overrides) -> str:
	doc = frappe.get_doc(
		{
			"doctype": "Baro Integration Log",
			"naming_series": "BARO-INTLOG-.####",
			"baro_direction": "Outbound",
			"baro_platform": "_Test BARO Platform",
			"baro_endpoint": "fleet/list",
			"baro_idempotency_key": key,
			"company": COMPANY,
			"baro_log_status": "Received",
			"baro_max_attempts": 5,
			**overrides,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


class TestIntegration(FrappeTestCase):
	def setUp(self):
		if not frappe.db.exists("Baro GPS Platform", {"baro_platform_name": "_Test BARO Platform"}):
			frappe.get_doc(
				{
					"doctype": "Baro GPS Platform",
					"baro_platform_name": "_Test BARO Platform",
					"baro_base_url": "https://gps.example.test/api",
					"baro_adapter_module": "baro_core.integrations.vendor_template",
					"baro_auth_type": "HMAC Signature",
					"company": COMPANY,
					"baro_rate_limit_per_min": 60,
					"baro_timeout_secs": 10,
					"baro_max_retries": 5,
					"baro_pull_interval": "Hourly",
					"baro_enabled": 1,
				}
			).insert(ignore_permissions=True)

	def test_scrub_redacts_credential_shaped_keys(self):
		"""`docs/50` §3: the audit trail must never become a credential store."""
		scrubbed = payload.scrub(
			{"token": "abc", "nested": {"api_key": "xyz", "imei": "35693"}, "items": [{"password": "p"}] * 2}
		)
		self.assertEqual(scrubbed["token"], "[redacted]")
		self.assertEqual(scrubbed["nested"]["api_key"], "[redacted]")
		self.assertEqual(scrubbed["nested"]["imei"], "35693")
		self.assertEqual(scrubbed["items"][0]["password"], "[redacted]")

	def test_adapter_boundary_rejects_rows_without_a_platform_id(self):
		with self.assertRaises(base.AdapterError) as ctx:
			base.reduce_device({"imei": "356930035693001"})
		self.assertEqual(ctx.exception.error_class, base.PAYLOAD)

	def test_retryable_failure_waits_and_permanent_failure_dies(self):
		"""One ladder decides both branches (`docs/50` §6) - never the caller."""
		first = make_log("retry-test-temporary")
		retry.mark_failure(first, 1, 5, {"error_class": base.TIMEOUT, "message": "connect timeout"})
		self.assertEqual(frappe.db.get_value("Baro Integration Log", first, "baro_log_status"), "Retrying")
		self.assertTrue(get_datetime(frappe.db.get_value("Baro Integration Log", first, "baro_next_retry_at")))

		second = make_log("retry-test-permanent")
		retry.mark_failure(second, 1, 5, {"error_class": base.AUTH, "message": "401 from vendor"})
		doc = frappe.get_doc("Baro Integration Log", second)
		self.assertEqual(doc.baro_log_status, "Dead")
		self.assertIsNone(doc.baro_next_retry_at)
		self.assertTrue(
			frappe.db.exists("Baro Reconciliation Exception", {"baro_match_key": f"dead|{second}"})
		)

	def test_max_attempts_exhaustion_dead_letters(self):
		name = make_log("retry-test-exhausted")
		retry.mark_failure(name, 5, 5, {"error_class": base.SERVER, "message": "503 three times"})
		self.assertEqual(frappe.db.get_value("Baro Integration Log", name, "baro_log_status"), "Dead")

	def test_exception_writes_dedupe_on_match_key(self):
		"""`docs/51` §6.1: a daily detector must not re-raise the same finding on every run."""
		key = "dedupe-test|vehicle-1"
		self.assertEqual(
			reconciliation.raise_exception(
				exception_type="State mismatch", company=COMPANY, details="first", match_key=key
			),
			1,
		)
		self.assertEqual(
			reconciliation.raise_exception(
				exception_type="State mismatch", company=COMPANY, details="second", match_key=key
			),
			0,
		)

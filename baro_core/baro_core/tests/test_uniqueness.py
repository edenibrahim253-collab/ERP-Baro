# Copyright (c) 2026 BARO Group
# License: MIT. See license.txt
"""The acceptance criterion the whole design is judged on (`docs/31` §1).

Two live assignments on one device, one vehicle, or one plate must be impossible - through the UI,
through Data Import, and under a concurrent submit. These tests drive the *model*, not the form,
because Data Import and the connector reach the same code path (`docs/30` §1).

`baro_status = Active` is set here directly instead of through the workflow transition: the tests
assert what the index and the overlap query enforce, not who was allowed to press the button
(that boundary is `tests/test_permissions.py`).

Written without a Python runtime available; `bench run-tests --app baro_core` is the first real
execution.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, now_datetime

COMPANY = "_Test Company"
DEVICE_GROUP = "_Test BARO Device"
DEVICE_ITEM = "_TEST-BARO-GPS-01"
PLATE_PATTERN = "^[0-9A-Z][0-9A-Z -]{3,11}$"
MSISDN_PATTERN = r"^251\d{9}$"


def make_serial(imei: str, customer: str = None, status: str = "Allocated", serial_no: str = None) -> str:
	doc = frappe.get_doc(
		{
			"doctype": "Serial No",
			"serial_no": serial_no or imei,
			"item_code": DEVICE_ITEM,
			"customer": customer,
			"baro_imei": imei,
			"baro_device_status": status,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


class BaroTestCase(FrappeTestCase):
	"""Common fixtures: the device Item Group must be registered in Settings before anything assigns."""

	def setUp(self):
		self.make_reference_data()

	def make_reference_data(self):
		if not frappe.db.exists("Item Group", DEVICE_GROUP):
			frappe.get_doc({"doctype": "Item Group", "item_group_name": DEVICE_GROUP, "is_group": 0}).insert(
				ignore_permissions=True
			)
		if not frappe.db.exists("Item", DEVICE_ITEM):
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": DEVICE_ITEM,
					"item_name": "Test GPS Device",
					"item_group": DEVICE_GROUP,
					"stock_uom": "Nos",
				}
			).insert(ignore_permissions=True)

		settings = frappe.get_single("Baro Operations Settings")
		settings.baro_plate_pattern = PLATE_PATTERN
		settings.baro_msisdn_pattern = MSISDN_PATTERN
		settings.baro_assignment_future_days = 30
		settings.baro_activation_sla_days = 2
		settings.set("baro_device_item_groups", [{"item_group": DEVICE_GROUP}])
		settings.save(ignore_permissions=True)

	def make_customer(self, idx: str) -> str:
		name = f"_Test BARO Customer {idx}"
		if not frappe.db.exists("Customer", name):
			frappe.get_doc(
				{"doctype": "Customer", "customer_name": name, "customer_type": "Individual"}
			).insert(ignore_permissions=True)
		return name

	def make_vehicle(self, plate: str, customer: str) -> str:
		doc = frappe.get_doc(
			{
				"doctype": "Baro Vehicle",
				"naming_series": "BARO-VEH-.####",
				"baro_plate_no": plate,
				"customer": customer,
				"company": COMPANY,
				"baro_vehicle_type": "Car",
				"baro_status": "Registered",
			}
		)
		doc.insert(ignore_permissions=True)
		return doc.name

	def make_assignment(self, customer, vehicle, serial, from_time=None, to_time=None, status="Draft"):
		doc = frappe.get_doc(
			{
				"doctype": "Baro Device Assignment",
				"naming_series": "BARO-ASSIGN-.####",
				"customer": customer,
				"baro_vehicle": vehicle,
				"serial_no": serial,
				"baro_assignment_type": "Installation",
				"baro_status": status,
				"from_time": from_time or now_datetime(),
				"to_time": to_time,
				"company": COMPANY,
			}
		)
		doc.insert(ignore_permissions=True)
		return doc

	def live_assignment(self, customer, vehicle, serial, **kwargs):
		"""Submitted and Active - the state the UQ-DRV index constrains."""
		doc = self.make_assignment(customer, vehicle, serial, status="Active", **kwargs)
		doc.flags.ignore_workflow_checks = True
		doc.submit()
		return doc


class TestUniqueness(BaroTestCase):
	def test_imei_is_unique(self):
		"""`docs/31` §3 layer 1: a friendly named failure, not an index traceback."""
		make_serial("356930035693001")
		with self.assertRaises(frappe.DuplicateEntryError):
			make_serial("356930035693001", serial_no="BARO-SPARE-001")

	def test_plate_is_unique(self):
		customer = self.make_customer("A")
		self.make_vehicle("AB-11111", customer)
		with self.assertRaises(frappe.ValidationError):
			self.make_vehicle("AB-11111", customer)

	def test_second_active_assignment_on_one_device_is_rejected(self):
		customer = self.make_customer("B")
		serial = make_serial("356930035693002")
		first = self.make_vehicle("AC-22222", customer)
		second = self.make_vehicle("AD-33333", customer)
		self.live_assignment(customer, first, serial)
		with self.assertRaises(frappe.ValidationError) as ctx:
			self.live_assignment(customer, second, serial)
		self.assertIn("Active assignment", str(ctx.exception))

	def test_active_key_is_populated_only_while_live(self):
		"""UQ-DRV (`docs/31` §4): the column carries the key only when submitted *and* Active."""
		customer = self.make_customer("C")
		serial = make_serial("356930035693003")
		vehicle = self.make_vehicle("AE-44444", customer)
		draft = self.make_assignment(customer, vehicle, serial)
		self.assertIsNone(draft.baro_active_serial_key)
		draft.reload()
		draft.baro_status = "Active"
		draft.flags.ignore_workflow_checks = True
		draft.submit()
		draft.reload()
		self.assertEqual(draft.baro_active_serial_key, serial)
		self.assertEqual(draft.baro_active_vehicle_key, vehicle)

	def test_ending_an_assignment_releases_the_slot(self):
		customer = self.make_customer("D")
		serial = make_serial("356930035693004")
		vehicle = self.make_vehicle("AF-55555", customer)
		doc = self.live_assignment(customer, vehicle, serial)
		doc.reload()
		doc.baro_status = "Ended"
		doc.to_time = add_days(now_datetime(), 1)
		doc.flags.ignore_workflow_checks = True
		doc.flags.ignore_validate_update_after_submit = True
		doc.save()
		doc.reload()
		self.assertIsNone(doc.baro_active_serial_key)
		self.live_assignment(customer, vehicle, make_serial("356930035693004B"))

	def test_overlapping_windows_are_rejected_across_states(self):
		"""The rule an index cannot express: an Ended row still owns its past window (`docs/31` §5)."""
		customer = self.make_customer("E")
		serial = make_serial("356930035693005")
		vehicle = self.make_vehicle("AG-66666", customer)
		start = now_datetime()
		first = self.live_assignment(customer, vehicle, serial, from_time=start)
		first.reload()
		first.baro_status = "Ended"
		first.to_time = add_days(start, 10)
		first.flags.ignore_workflow_checks = True
		first.flags.ignore_validate_update_after_submit = True
		first.save()
		second = self.make_assignment(
			customer, vehicle, make_serial("356930035693005B"), from_time=add_days(start, 5), status="Active"
		)
		second.flags.ignore_workflow_checks = True
		with self.assertRaises(frappe.ValidationError) as ctx:
			second.submit()
		self.assertIn("covering this period", str(ctx.exception))

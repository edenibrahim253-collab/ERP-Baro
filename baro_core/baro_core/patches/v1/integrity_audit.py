"""The three post-migrate integrity queries (`31` §7.3).

Cheap, read-only, and run on every migrate. They answer the question the UQ-DRV trick raises:
what if Python stopped maintaining the key columns? A guarantee that can silently rot is worse
than no guarantee, because people keep relying on it.

Query 1 is covered by `backfill_active_keys`, which both detects and repairs. This module reports
the two the app must not repair automatically:

* **Active with a past `to_time`** - ending an assignment changes what is billed, so a human does
  it (`40` §1: detection is not action).
* **Active on a device that stock says is still on a shelf** - a fork between BARO state and
  stock truth, and only a person knows which one is lying.
"""

import frappe

from baro_core.patches import has_column, table

QUERIES = [
	(
		"assignment-active-past-to-time",
		"BARO Active assignment(s) whose to_time is already past",
		"""
		select name, serial_no, baro_vehicle, to_time from {table}
		where docstatus = 1 and baro_status = 'Active' and to_time is not null and to_time < now()
		""",
		"State mismatch",
	),
	(
		"assignment-vs-stock-status",
		"BARO Active assignment(s) on a serial stock still holds in a warehouse",
		"""
		select a.name, a.serial_no, s.status, s.warehouse from {table} a
		join `tabSerial No` s on s.name = a.serial_no
		where a.docstatus = 1 and a.baro_status = 'Active'
			and s.warehouse is not null and s.warehouse != '' and s.status = 'Active'
		""",
		"State mismatch",
	),
]


def execute():
	run()


def run():
	if not has_column("Baro Device Assignment", "baro_active_serial_key"):
		return
	for check_id, title, sql, exception_type in QUERIES:
		rows = frappe.db.sql(sql.format(table=table("Baro Device Assignment")), as_dict=True)
		if not rows:
			continue
		frappe.log_error(title=f"BARO integrity: {title}", message=frappe.as_json(rows[:100], indent=1))
		for row in rows[:20]:
			raise_integrity_exception(check_id, exception_type, title, row)


def raise_integrity_exception(check_id: str, exception_type: str, title: str, row: dict) -> None:
	"""One open exception per (check, assignment) - never a repeat per migrate (`51` §5)."""
	from baro_core.integrations.reconciliation import raise_exception

	raise_exception(
		exception_type=exception_type,
		serial_no=row.get("serial_no"),
		vehicle=row.get("baro_vehicle"),
		details=f"{title}: {row.get('name')} - " + ", ".join(f"{k} {v}" for k, v in row.items() if k != "name"),
		match_key=f"integrity|{check_id}|{row.get('name')}",
		assigned_role="BARO Service Supervisor",
		ref_doctype="Baro Device Assignment",
		ref_name=row.get("name"),
	)

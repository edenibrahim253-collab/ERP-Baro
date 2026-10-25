"""Re-derive UQ-DRV keys for rows whose key columns disagree with reality (`31` §4.2, §7.1).

Runs from `hooks.after_migrate`, so a partial import, a crashed backfill, or a hand-edit in the
database is corrected on the next migrate rather than at the next collision.

The repair goes through `derive.set_active_keys` and a document save - never a raw UPDATE. Only
rows that already disagree are loaded, and they are capped, so the cost is bounded by the number
of bugs rather than by the size of the fleet.
"""

import frappe

from baro_core import derive
from baro_core.patches import has_column, table

BATCH = 500

DRIFTED = """
select name from {table}
where docstatus = 1 and baro_status = 'Active'
	and (baro_active_serial_key is distinct from serial_no
		or baro_active_vehicle_key is distinct from baro_vehicle)
union
select name from {table}
where not (docstatus = 1 and baro_status = 'Active')
	and (baro_active_serial_key is not null or baro_active_vehicle_key is not null)
"""


def execute():
	run()


def run():
	if not has_column("Baro Device Assignment", "baro_active_serial_key"):
		return
	names = [row[0] for row in frappe.db.sql(DRIFTED.format(table=table("Baro Device Assignment")))]
	if not names:
		return
	frappe.logger("baro").warning("BARO UQ-DRV drift on %s assignment(s), re-deriving", len(names))
	for name in names[:BATCH]:
		try:
			doc = frappe.get_doc("Baro Device Assignment", name)
		except frappe.DoesNotExistError:
			continue
		derive.set_active_keys(doc)
		# An active key that collides with another live assignment cannot be saved - that is the
		# index doing its job. Report it and move on; a migrate must not die on one bad row.
		try:
			doc.flags.ignore_validate_update_after_submit = True
			doc.save(ignore_permissions=True)
		except frappe.DuplicateEntryError:
			report_conflict(doc)


def report_conflict(doc) -> None:
	from baro_core.integrations.reconciliation import raise_exception

	raise_exception(
		exception_type="Duplicate active device",
		serial_no=doc.serial_no,
		vehicle=doc.baro_vehicle,
		company=doc.company,
		details=f"{doc.name} cannot re-derive its active key: another live assignment already holds it",
		match_key=f"uqdrv|{doc.name}",
		assigned_role="BARO System Manager",
	)

"""Layer 2 - UQ-DRV (`31` §4, §7.1).

Order inside this patch is the design, not incidental: add the columns, backfill them from the
submitted-and-Active rows that already exist, scan for the duplicates the index is about to
reject, and only then create the index. Creating the index first would turn a messy first
migration into an opaque `bench migrate` crash instead of a readable report.
"""

import frappe

from baro_core.patches import add_unique, block, has_column, overlapping_actives, table

COLUMNS = [
	("baro_active_serial_key", "uk_baro_active_serial"),
	("baro_active_vehicle_key", "uk_baro_active_vehicle"),
]

BACKFILL = """
update {table}
set baro_active_serial_key = case when docstatus = 1 and baro_status = 'Active' then serial_no end,
	baro_active_vehicle_key = case when docstatus = 1 and baro_status = 'Active' then baro_vehicle end
"""


def execute():
	run()


def run():
	missing = [name for name, _ in COLUMNS if not has_column("Baro Device Assignment", name)]
	if missing:
		frappe.logger("baro").warning(
			"BARO UQ-DRV columns not present yet: %s - re-runs on the next migrate", ", ".join(missing)
		)
		return

	# Backfill is a raw UPDATE here on purpose: `31` §4.2 forbids db.set_value in application code,
	# and a patch that re-saves thousands of documents would run their validations against legacy
	# data. This is the one documented maintenance path, and `integrity_audit` re-checks it.
	frappe.db.sql(BACKFILL.format(table=table("Baro Device Assignment")))

	conflicts = overlapping_actives()
	if conflicts:
		block(
			f"{len(conflicts)} device/vehicle already carries more than one active assignment",
			conflicts,
		)
	for column, index_name in COLUMNS:
		add_unique("Baro Device Assignment", [column], index_name)

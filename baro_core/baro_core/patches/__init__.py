"""Shared index helpers for BARO patches (`docs/31-uniqueness-concurrency-design.md #7`).

Kept out of `baro_core.derive` because these touch DDL, which application code must never do:
a controller that can alter a table can also silently remove the guarantee it depends on.
"""

import frappe

DB = "database()"


def table(doctype: str) -> str:
	return f"`tab{doctype}`"


def has_column(doctype: str, fieldname: str) -> bool:
	return bool(
		frappe.db.sql(
			"""
			select 1 from information_schema.columns
			where table_schema = {db} and table_name = %s and column_name = %s limit 1
			""".format(db=DB),
			(f"tab{doctype}", fieldname),
		)
	)


def index_exists(doctype: str, index_name: str) -> bool:
	return bool(
		frappe.db.sql(
			"""
			select 1 from information_schema.statistics
			where table_schema = {db} and table_name = %s and index_name = %s limit 1
			""".format(db=DB),
			(f"tab{doctype}", index_name),
		)
	)


def duplicates(doctype: str, fieldname: str) -> list[tuple]:
	"""Existing values that would block a unique index. Empty string counts: it is a value."""
	return frappe.db.sql(
		f"""
		select `{fieldname}`, count(*) from {table(doctype)}
		where `{fieldname}` is not null and `{fieldname}` != ''
		group by `{fieldname}` having count(*) > 1
		order by count(*) desc
		"""
	)


def add_unique(doctype: str, fieldnames: list[str], index_name: str) -> bool:
	"""Create the index only when the data already satisfies it. Never repairs data.

	`fieldnames` comes from the constants in `patches/v1/*`, never from user input.
	"""
	if index_exists(doctype, index_name):
		return False
	columns = ", ".join(f"`{f}`" for f in fieldnames)
	frappe.db.sql_ddl(f"alter table {table(doctype)} add unique index `{index_name}` ({columns})")
	return True


def overlapping_actives() -> list[dict]:
	"""Pre-flight for UQ-DRV: two live assignments on one device or one vehicle (`31` §7.2)."""
	rows = []
	for column, label in (("serial_no", "device"), ("baro_vehicle", "vehicle")):
		rows += [
			dict(kind=label, key=value, count=count)
			for value, count in frappe.db.sql(
				f"""
				select `{column}`, count(*) from {table("Baro Device Assignment")}
				where docstatus = 1 and baro_status = 'Active' and `{column}` is not null
				group by `{column}` having count(*) > 1
				"""
			)
		]
	return rows


def block(message: str, offenders: list) -> None:
	"""Stop a migrate with a readable report instead of an opaque DuplicateEntryError.

	The patch does not "fix" data: auto-ending a duplicate active assignment would erase
	billing-affecting history (`01` §6), so a human resolves it and re-runs the migrate.
	"""
	lines = "\n".join(str(o) for o in offenders[:50])
	frappe.log_error(title=f"BARO patch blocked: {message}", message=f"{message}\n{lines}")
	if offenders and isinstance(offenders[0], dict):
		from baro_core.integrations.reconciliation import raise_exception

		for offender in offenders[:20]:
			serial = offender.get("key") if offender.get("kind") == "device" else None
			raise_exception(
				exception_type="Duplicate active device",
				details=f"{message}: {offender['kind']} {offender['key']} has {offender['count']} active assignments",
				match_key=f"uqdrv|{offender['kind']}|{offender['key']}",
				serial_no=serial,
				vehicle=offender.get("key") if offender.get("kind") == "vehicle" else None,
				assigned_role="BARO System Manager",
			)
	raise frappe.ValidationError(frappe._("BARO migrate blocked: {0}").format(message))

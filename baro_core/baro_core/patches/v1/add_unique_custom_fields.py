"""Layer 1 for Custom Fields on standard DocTypes (`31` §3).

`unique: 1` on a Custom Field does reach the schema, but only once the Custom Field fixture has
been applied - and `bench migrate` runs the patch list *before* importing fixtures. This patch is
the idempotent backstop: after the field exists, it guarantees the index exists too, and it
refuses to create an index over duplicate data.

`Customer.baro_platform_customer_ref` is deliberately NOT in here: the same external account may
legitimately appear for two legal entities, so it is searchable, not unique (`10` §3).
"""

import frappe

from baro_core.patches import add_unique, block, duplicates, has_column

# (DocType, fieldname, index name) - normalisation happens in `validate`, before the index compares.
UNIQUE_STANDARD_FIELDS = [
	("Serial No", "baro_imei", "uk_baro_imei"),
]


def execute():
	run()


def run():
	for doctype, fieldname, index_name in UNIQUE_STANDARD_FIELDS:
		if not has_column(doctype, fieldname):
			continue
		conflicts = duplicates(doctype, fieldname)
		if conflicts:
			# Duplicates are reported, never deleted - which device identity is right is not the patch's call.
			block(
				f"{doctype}.{fieldname} has {len(conflicts)} duplicate value(s); unique index not created",
				[{"kind": fieldname, "key": value, "count": count} for value, count in conflicts],
			)
		add_unique(doctype, [fieldname], index_name)

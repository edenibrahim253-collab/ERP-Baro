# Copyright (c) 2026 BARO Group
# License: MIT. See license.txt
"""Integration-module effects (`21` §4, `50` §7).

The mapping table is the only place an external device id exists, so it is also the only
place "last communication" comes from. `Serial No.baro_last_comm_at` is the **max** across the
enabled mappings for that serial, which is what makes a device with two platform accounts
report one truthful presence time.
"""

from baro_core import derive


def after_mapping_update(doc, method=None):
	derive.recompute_last_comm(doc.serial_no)

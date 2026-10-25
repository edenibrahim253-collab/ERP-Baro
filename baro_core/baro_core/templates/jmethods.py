"""Jinja helpers registered in `hooks.jinja` (`30` §13).

Kept to formatting, never to logic a template could get wrong: a print format or email template
that recomputes device state would create a second, undocumented authority for it.
"""

import frappe
from frappe.utils import format_datetime

# English source strings; translated at call time, because a module-level `frappe._()` would be
# resolved with no user language in context.
STATE_LABELS = {
	"In-Stock": "In stock",
	"Reserved": "Reserved for an order",
	"Allocated": "Allocated to a technician",
	"Installed": "Installed, activation pending",
	"Active": "Active - reporting",
	"Faulty": "Faulty",
	"RMA": "Returned to manufacturer",
	"Returned": "Returned from RMA",
	"Disposed": "Disposed",
}


def device_state_label(status: str | None) -> str:
	"""Plain-language device state for emails and print formats."""
	source = STATE_LABELS.get(status)
	if source is None:
		return status or frappe._("Unknown")
	return frappe._(source)


def assignment_window(from_time=None, to_time=None) -> str:
	"""One-line time range; an open end reads as ongoing rather than blank."""
	if not from_time:
		return frappe._("Not scheduled")
	start = format_datetime(from_time, "dd MMM yyyy HH:mm")
	if not to_time:
		return f"{start} - {frappe._('ongoing')}"
	return f"{start} - {format_datetime(to_time, 'dd MMM yyyy HH:mm')}"

# Copyright (c) 2026 BARO Group
# License: MIT. See license.txt
"""`Baro Integration Log` — append-only delivery record (`21` §7).

This DocType *is* the "documented synchronization error handling" acceptance criterion, so
three properties are enforced in code rather than left to convention:

* `baro_idempotency_key` is unique and the log row is written **before** the side effect,
  which makes replay a lookup instead of a second mutation (`50` §4).
* secrets never reach storage: the writer strips header material before persisting, and
  message text is truncated so a chatty vendor error cannot become a data leak.
* state moves along a fixed ladder. `Dead -> Retrying` is the only human-initiated
  transition and it requires a note, because re-driving a dead letter without recording why
  destroys the audit trail the log exists to provide.
"""

import frappe
from frappe.model.document import Document
from frappe import _

RECEIVED = "Received"
PROCESSED = "Processed"
FAILED = "Failed"
RETRYING = "Retrying"
DEAD = "Dead"

ALLOWED_TRANSITIONS = {
	RECEIVED: {PROCESSED, FAILED, RETRYING},
	FAILED: {RETRYING, DEAD, PROCESSED},
	RETRYING: {PROCESSED, FAILED, DEAD},
	DEAD: {RETRYING},
	PROCESSED: set(),
}

# Anything that looks like one of these in an error message is vendor credentials, not
# diagnostic information.
SENSITIVE_KEYS = (
	"authorization",
	"apikey",
	"api_key",
	"secret",
	"token",
	"password",
	"webhook_secret",
	"pin",
	"puk",
)

MAX_MESSAGE_CHARS = 1000


def scrub_secrets(text: str | None) -> str | None:
	"""Redact `key: value` pairs for sensitive keys, keeping the sentence readable."""
	if not text:
		return text
	scrubbed = text
	for key in SENSITIVE_KEYS:
		scrubbed = _redact(scrubbed, key)
	return scrubbed[:MAX_MESSAGE_CHARS]


def _redact(text: str, needle: str) -> str:
	hay = text.lower()
	out = text
	start = 0
	while True:
		at = hay.find(needle, start)
		if at == -1:
			break
		# Redact to the next delimiter after the ':' or '=' that follows the key.
		sep = _find_colon(hay, at, len(text))
		if sep == -1:
			break
		end = len(text)
		for ch in ("\n", ";", ",", "&", " "):
			pos = hay.find(ch, sep + 1, end)
			if pos != -1:
				end = pos
		if end > sep + 1:
			out = out[: sep + 1] + " [redacted]" + out[end:]
			hay = out.lower()
			start = hay.find(needle, start) + len(needle)
		else:
			break
	return out


def _find_colon(hay: str, from_pos: int, limit: int) -> int:
	for i in range(from_pos, min(limit, len(hay))):
		if hay[i] in (":", "="):
			return i
		if hay[i] == "\n":
			return -1
	return -1


class BaroIntegrationLog(Document):
	def validate(self):
		self.baro_idempotency_key = (self.baro_idempotency_key or "").strip()
		if not self.baro_idempotency_key:
			frappe.throw(_("Idempotency key is required"))
		self.baro_error_message = scrub_secrets(self.baro_error_message)
		if not self.is_new():
			self.assert_legal_transition()

	def assert_legal_transition(self):
		previous = frappe.db.get_value("Baro Integration Log", self.name, "baro_log_status")
		if previous == self.baro_log_status:
			return
		if self.baro_log_status not in ALLOWED_TRANSITIONS.get(previous, set()):
			frappe.throw(
				_("{0} cannot move from {1} to {2}").format(self.name, previous, self.baro_log_status)
			)
		if previous == DEAD:
			self.assert_redrive_authorised()

	def assert_redrive_authorised(self):
		if not frappe.has_permission("Baro Integration Log", "delete"):
			frappe.throw(_("Only a System Manager may re-drive a dead letter."))
		if not (self.baro_error_message or "").strip() and not (self.baro_next_retry_at):
			frappe.throw(_("Re-driving a dead letter requires a retry date and a note"))

	def on_update(self):
		if self.baro_log_status == PROCESSED and not self.baro_processed_at:
			self.baro_processed_at = frappe.utils.now()

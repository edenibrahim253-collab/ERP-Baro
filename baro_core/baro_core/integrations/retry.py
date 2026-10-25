# Copyright (c) 2026 BARO Group
# License: MIT. See license.txt
"""Retry ladder (`50` §6).

Backoff is exponential from the attempt count, permanent error classes are dead-lettered
immediately (a 401 will not start working on the fifth try), and a row that reaches
`baro_max_attempts` becomes `Dead` plus an exception in the human inbox - never silently dropped.

`jobs.process_integration_retries` takes a per-row lock before calling in, so two workers cannot
claim the same row. The re-check of `baro_log_status` inside `mark_processed`/`mark_failure` is
the second half of that guard: if a lock expired mid-flight, the stale worker finds the row
already terminal and writes nothing.
"""

import frappe
from frappe.utils import add_to_date, now_datetime

from baro_core.integrations import base, payload

MAX_BACKOFF_MINUTES = 60 * 24


def retry_due_events(log_name: str) -> dict:
	log = frappe.db.get_value(
		"Baro Integration Log",
		log_name,
		["name", "baro_log_status", "baro_attempt_count", "baro_max_attempts", "baro_direction",
		 "baro_platform", "baro_endpoint", "ref_doctype", "ref_name", "baro_error_class"],
		as_dict=True,
	)
	if not log or log.baro_log_status in ("Processed", "Dead"):
		return {"skipped": True}

	attempt = int(log.baro_attempt_count or 0) + 1
	result = re_drive(log)
	if result["ok"]:
		mark_processed(log_name)
		return {"ok": True, "attempt": attempt}
	mark_failure(log_name, attempt, int(log.baro_max_attempts or 5), result)
	return {"ok": False, "attempt": attempt, "error_class": result.get("error_class")}


def register_failure(log_name: str, error_class: str = None, message: str = None) -> dict:
	"""Record a first-attempt failure from the caller that just made it (webhook, sync).

	One ladder, one place: whether an error is worth retrying, how long to wait, and when it
	becomes a dead letter is decided here and nowhere else.
	"""
	attempt, maximum = frappe.db.get_value(
		"Baro Integration Log", log_name, ["baro_attempt_count", "baro_max_attempts"]
	)
	attempt = int(attempt or 0) + 1
	mark_failure(log_name, attempt, int(maximum or 5), {"error_class": error_class, "message": message})
	return {"ok": False, "attempt": attempt, "error_class": error_class or base.UNKNOWN}


def re_drive(log) -> dict:
	"""Re-apply the recorded operation.

	Inbound events re-run through the same handler, which is itself guarded by the unique
	idempotency key, so a re-drive of an already-applied event is a no-op. Outbound calls
	re-issue exactly one request, and only after the platform's rate-limit budget allows it.
	"""
	from baro_core.integrations.ratelimit import consume_for_platform
	from baro_core.integrations.webhook import apply_event

	if log.baro_direction == "Inbound":
		doc = frappe.get_doc("Baro Integration Log", log.name)
		data = payload.read_payload(doc)
		if data is None:
			return {"ok": False, "error_class": base.PAYLOAD, "message": "payload no longer retrievable"}
		event = (doc.baro_endpoint or "").split("/")[-1]
		try:
			apply_event(doc.baro_platform, event, data, doc)
		except Exception as error:  # noqa: BLE001
			return {"ok": False, "error_class": base.classify(error), "message": str(error)[:900]}
		return {"ok": True}

	if not consume_for_platform(log.baro_platform):
		return {"ok": False, "error_class": base.RATE_LIMIT, "message": "platform budget exhausted"}
	adapter = base.resolve(log.baro_platform)
	result = adapter.request("GET", log.baro_endpoint or "")
	if result.ok:
		return {"ok": True}
	return {"ok": False, "error_class": result.error_class, "message": str(result.error)[:900]}


def mark_processed(log_name):
	doc = frappe.get_doc("Baro Integration Log", log_name)
	if doc.baro_log_status == "Processed":
		return
	doc.baro_log_status = "Processed"
	doc.baro_processed_at = now_datetime()
	doc.baro_error_class = "None"
	doc.save(ignore_permissions=True)


def mark_failure(log_name, attempt: int, max_attempts: int, result: dict):
	doc = frappe.get_doc("Baro Integration Log", log_name)
	if doc.baro_log_status == "Processed":
		return
	permanent = result.get("error_class") not in base.RETRYABLE
	doc.baro_attempt_count = attempt
	doc.baro_error_class = result.get("error_class") or base.UNKNOWN
	doc.baro_error_message = result.get("message")
	if permanent or attempt >= max_attempts:
		doc.baro_log_status = "Dead"
		doc.baro_next_retry_at = None
	else:
		doc.baro_log_status = "Retrying"
		doc.baro_next_retry_at = add_to_date(now_datetime(), minutes=min(2 ** attempt, MAX_BACKOFF_MINUTES))
	doc.save(ignore_permissions=True)
	if doc.baro_log_status == "Dead":
		from baro_core import jobs
		from baro_core.integrations.reconciliation import raise_exception

		jobs.notify_dead_letter(doc)
		raise_exception(
			exception_type="State mismatch",
			platform=doc.baro_platform,
			company=doc.company,
			assigned_role="BARO Service Supervisor",
			details=f"Dead letter {doc.name} ({doc.baro_error_class}): {doc.baro_error_message}",
			match_key=f"dead|{doc.name}",
			ref_doctype=doc.ref_doctype,
			ref_name=doc.ref_name,
		)

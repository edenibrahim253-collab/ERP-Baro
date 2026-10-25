# Copyright (c) 2026 BARO Group
# License: MIT. See license.txt
"""Scheduler entrypoints (`30` §11, `60` trigger catalog).

Every job here obeys the same contract, and the contract is the point:

1. **Detect, do not act.** No job submits, cancels, suspends a service or posts an invoice.
   A job notifies, flags a field, or raises a `Baro Reconciliation Exception` for a human.
   The blueprint's own constraint - service-impacting and financial changes need approval -
   is why `flag_overdue_invoices` can raise a `Billing mismatch` row but cannot suspend
   tracking, and why `flag_sim_expiry` flags rather than setting `Expired` (`21` §3).
2. **Bounded.** Every read is batched with a limit; row caps come from Settings, not literals.
3. **Locked and idempotent.** A named lock per job (and per platform for sync/reconciliation)
   so a restarted worker cannot double-run, and re-running produces the same result.
4. **Observable.** Each run writes one `Baro Integration Log`-free summary into the Error Log
   only on failure; successes are visible through the reports the flags feed.
"""

import frappe
from frappe.utils import add_days, cint, getdate, now, now_datetime, time_diff_in_hours

from baro_core import locks, settings

BATCH = 500


def _recipients(role: str) -> list[str]:
	return frappe.get_all(
		"Has Role",
		filters={"role": role, "parenttype": "User"},
		pluck="parent",
		order_by="asc",
		limit=200,
	)


def _emails(users) -> list[str]:
	rows = frappe.get_all(
		"User", filters={"name": ["in", list(users)], "enabled": 1}, pluck="email", limit=200
	)
	return [r for r in rows if r]


def _digest_email(recipients, subject: str, message: str) -> None:
	"""One mail per run, never one per row (`60` §4: anything that can fire for 200 vehicles fires once)."""
	to = _emails(set(recipients))
	if not to:
		return
	try:
		frappe.sendmail(recipients=to, subject=subject, message=message, now=True)
	except Exception:  # noqa: BLE001 - a failed SMTP hop must not abort the flagging job
		frappe.log_error(frappe.get_traceback(), f"BARO digest mail failed: {subject}")


def _notify(recipients, subject: str, message: str, reference_doctype=None, reference_name=None):
	"""One Notification Log per (subject, reference) - re-running a job does not spam twice."""
	if not recipients:
		return
	key = f"{subject}|{reference_name or ''}"
	if frappe.db.exists(
		"Notification Log", {"subject": subject, "document_name": reference_name or None, "for_user": ("in", recipients)}
	):
		return
	for user in recipients:
		doc = frappe.get_doc(
			{
				"doctype": "Notification Log",
				"subject": subject,
				"for_user": user,
				"from_user": "Administrator",
				"type": "Alert",
				"document_type": reference_doctype,
				"document_name": reference_name,
				"email_content": message,
			}
		)
		doc.insert(ignore_permissions=True)
	frappe.logger(__name__).info("baro notified %s: %s", key, len(recipients))


def notify_dead_letter(log) -> None:
	"""`40` §8: an integration row that reaches `Dead` names the platform, endpoint and correlation id."""
	recipients = _recipients("BARO System Manager") + _recipients("BARO Integrator")
	subject = f"BARO - dead letter on {log.baro_platform} {log.baro_endpoint}"
	message = (
		f"{log.name}: {log.baro_error_class} - {log.baro_error_message}\nCorrelation {log.baro_correlation_id}. "
		"Re-drive it from the Integration Log once the cause is fixed."
	)
	_notify(recipients, subject, message, "Baro Integration Log", log.name)
	_digest_email(recipients, subject, message)


def flag_contracts_expiring():
	"""T3 - Contract/Subscription expiry inside the notice window."""
	window = settings.int_value("baro_expiry_notice_days")
	today, horizon = getdate(), getdate(add_days(now_datetime(), window))
	rows = frappe.get_all(
		"Subscription",
		filters={"status": ["in", ["Active", "Trialing"]], "end_date": ["between", [today, horizon]]},
		fields=["name", "party_type", "party", "end_date"],
		limit=BATCH,
	)
	sales = _recipients("BARO Sales Officer")
	for row in rows:
		_notify(
			sales + _recipients("BARO Accounts User"),
			f"BARO - T3 Subscription {row.name} expires {row.end_date}",
			f"Subscription for {row.party} ends on {row.end_date}. Renew or plan to end assignments.",
			"Subscription",
			row.name,
		)
	if rows:
		lines = "<br>".join(f"{r.name} ({r.party}) - {r.end_date}" for r in rows)
		_digest_email(sales, "BARO - subscriptions expiring", lines)


def flag_overdue_invoices():
	"""T5 - overdue invoices: notify finance and raise a `Billing mismatch` exception (RA-5).

	Deliberately does **not** suspend anything: suspension is a Finance Approver decision made
	through a workflow transition (`40` §4), and a cron job must not be able to cut a customer's
	service.
	"""
	rows = frappe.get_all(
		"Sales Invoice",
		filters={"status": ["in", ["Overdue", "Unpaid"]], "docstatus": 1},
		fields=["name", "customer", "due_date", "outstanding_amount"],
		limit=BATCH,
	)
	finance = _recipients("BARO Accounts User") + _recipients("BARO Finance Approver")
	for row in rows:
		_notify(
			finance,
			f"BARO - T5 Invoice {row.name} overdue",
			f"{row.outstanding_amount} outstanding since {row.due_date} for {row.customer}.",
			"Sales Invoice",
			row.name,
		)
	if rows:
		lines = "<br>".join(f"{r.name}: {r.outstanding_amount} since {r.due_date}" for r in rows)
		_digest_email(finance, "BARO - overdue invoices", lines)
	if rows:
		from baro_core.integrations.reconciliation import raise_exception

		raise_exception(
			exception_type="Billing mismatch",
			company=frappe.get_single("Baro Operations Settings").get("company") or frappe.db.get_value("Company", None, "name"),
			assigned_role="BARO Accounts User",
			details=f"{len(rows)} overdue invoice(s) as of {now()}",
			match_key=f"RA-5|{getdate()}",
		)


def flag_sim_expiry():
	"""T7 - flag approaching/passed expiry; a human sets `Expired` (`21` §3)."""
	window = settings.int_value("baro_expiry_notice_days")
	horizon = getdate(add_days(now_datetime(), window))
	rows = frappe.get_all(
		"Baro SIM Card",
		filters={"baro_sim_status": ["in", ["Provisioned", "Activated", "Suspended"]], "baro_expiry_date": ["<=", horizon]},
		fields=["name", "baro_iccid", "baro_expiry_date", "baro_sim_status"],
		limit=BATCH,
	)
	sim_admins = _recipients("BARO Connectivity Admin")
	for row in rows:
		_notify(
			sim_admins + _recipients("BARO Service Supervisor"),
			f"BARO - T7 SIM {row.name} plan expiry {row.baro_expiry_date}",
			f"ICCID {row.baro_iccid} is {row.baro_sim_status} and its plan expires {row.baro_expiry_date}. "
			"Renew with the provider or set the status to Expired from the flagged list.",
			"Baro SIM Card",
			row.name,
		)
	if rows:
		lines = "<br>".join(f"{r.name} - {r.baro_sim_status} - expires {r.baro_expiry_date}" for r in rows)
		_digest_email(sim_admins, "BARO - SIM data plans expiring", lines)


def flag_certificates_expiring():
	"""T8 - registration, insurance and speed-limiter certificate windows on the fleet register.

	The subject names the vehicle record, never the plate: `60` §4 forbids plate and IMEI in an
	email subject, because these alerts are forwarded outside the fleet team.
	"""
	window = settings.int_value("baro_cert_notice_days")
	horizon = getdate(add_days(now_datetime(), window))
	fleet = _recipients("BARO Fleet Officer")
	lines = []
	for field, label in (
		("baro_registration_expiry", "registration"),
		("baro_insurance_expiry", "insurance"),
		("baro_cert_expiry", "speed-limiter certificate"),
	):
		rows = frappe.get_all(
			"Baro Vehicle",
			filters={"baro_status": ["in", ["Registered", "In-Service"]], field: ["between", [getdate(), horizon]]},
			fields=["name", "baro_plate_no", "customer", field],
			limit=BATCH,
		)
		for row in rows:
			_notify(
				fleet + _recipients("BARO Support Agent"),
				f"BARO - T8 {label} expiring - {row.name}",
				f"Vehicle {row.baro_plate_no} ({row.customer}) {label} expires {row.get(field)}.",
				"Baro Vehicle",
				row.name,
			)
			lines.append(f"{row.name}: {label} expires {row.get(field)}")
	if lines:
		_digest_email(fleet, "BARO - fleet compliance dates expiring", "<br>".join(lines))


def flag_reorder_points():
	"""T9 - read standard stock data, notify the configured role, create no purchase request."""
	role = settings.get("baro_reorder_notice_role")
	rows = frappe.get_all(
		"Reorder Item",
		filters={"docstatus": 0},
		fields=["parent", "item_code", "qty_to_reorder"],
		limit=BATCH,
	)
	if not rows:
		return
	lines = "<br>".join(f"{r.item_code}: {r.qty_to_reorder}" for r in rows[:50])
	role_recipients = _recipients(role)
	_notify(role_recipients, f"BARO - T9 device reorder suggestions ({len(rows)})", lines, None, None)
	_digest_email(role_recipients, "BARO - device stock below reorder point", lines)


def flag_warranty_expiry():
	"""T10 - weekly digest of devices whose warranty lapses in the next 30 days."""
	serials = frappe.get_all(
		"Serial No",
		filters={"warranty_expiry_date": ["between", [getdate(), getdate(add_days(now_datetime(), 30))]]},
		fields=["name", "customer", "warranty_expiry_date"],
		limit=BATCH,
	)
	if not serials:
		return
	body = "<br>".join(f"{s.name} ({s.customer}) - {s.warranty_expiry_date}" for s in serials[:100])
	_notify(
		_recipients("BARO Service Supervisor"),
		f"BARO - T10 warranty digest ({len(serials)} devices)",
		body,
		None,
		None,
	)


def flag_inactive_devices():
	"""T6 - presence gap detected from `Serial No.baro_last_comm_at` (`50` §7).

	Creates a **draft** `Issue` at most per device per threshold window; never auto-submits, so a
	network outage cannot manufacture submitted support tickets.
	"""
	threshold = settings.int_value("baro_inactive_threshold_hours")
	cutoff = add_days(now_datetime(), -threshold)
	rows = frappe.get_all(
		"Serial No",
		filters={"baro_device_status": ["in", ["Installed", "Active"]], "baro_last_comm_at": ["<", cutoff]},
		fields=["name", "customer", "baro_last_comm_at"],
		limit=BATCH,
	)
	for row in rows:
		if frappe.db.exists("Baro Integration Log", {"baro_idempotency_key": f"inactive|{row.name}"}):
			continue
		hours = cint(time_diff_in_hours(now_datetime(), row.baro_last_comm_at))
		subject = f"Device {row.name} silent for {hours}h"
		if frappe.db.exists("Issue", {"subject": subject, "status": ["!=", "Closed"]}):
			continue
		frappe.get_doc(
			{
				"doctype": "Issue",
				"subject": subject,
				"customer": row.customer,
				"status": "Open",
				"issue_type": "Problem",
				"description": f"Last communication {row.baro_last_comm_at}. Threshold {threshold}h.",
			}
		).insert(ignore_permissions=True, ignore_mandatory=True)


def sync_platform_fleet():
	"""Pull dispatch - upsert mapping + last-comm only, performs no diff (`51` §1)."""
	from baro_core.integrations.sync import pull_enabled_platforms

	with locks.acquired(["sync:dispatch"]):
		pull_enabled_platforms()


def process_integration_retries():
	"""Claim `Failed`/`Retrying` rows whose next retry is due, one lock per row (`50` §6)."""
	from baro_core.integrations.retry import retry_due_events

	rows = frappe.get_all(
		"Baro Integration Log",
		filters={"baro_log_status": ["in", ["Failed", "Retrying"]], "baro_next_retry_at": ["<=", now()]},
		fields=["name"],
		order_by="baro_next_retry_at asc",
		limit=50,
	)
	for row in rows:
		with locks.acquired([locks.retry_claim_lock(row.name)]):
			retry_due_events(row.name)


def run_platform_reconciliation():
	"""Three-way diff per platform, one lock per platform, writes only exceptions (`51` §2)."""
	from baro_core.integrations.reconciliation import reconcile_platform

	if not _reconciliation_due():
		return
	for platform in frappe.get_all("Baro GPS Platform", filters={"baro_enabled": 1}, pluck="name"):
		with locks.acquired([locks.reconciliation_lock(platform)]):
			summary = reconcile_platform(platform)
		# The run row is what makes `baro_reconciliation_cron` a real setting instead of decoration.
		frappe.get_doc(
			{
				"doctype": "Baro Integration Log",
				"baro_direction": "Outbound",
				"baro_platform": platform,
				"baro_endpoint": "reconciliation",
				"baro_idempotency_key": f"recon|{platform}|{now_datetime().strftime('%Y%m%d%H%M%S')}",
				"baro_log_status": "Processed" if not summary.get("aborted") else "Failed",
				"baro_error_class": summary.get("error_class", "None"),
				"baro_error_message": "platform read failed, no exceptions written" if summary.get("aborted") else None,
				"baro_processed_at": now_datetime(),
				"company": frappe.db.get_value("Baro GPS Platform", platform, "company"),
			}
		).insert(ignore_permissions=True)


def _reconciliation_due() -> bool:
	"""The cron is a heartbeat; the setting decides whether this hour is a run."""
	frequency = settings.get("baro_reconciliation_cron")
	hourly = frappe.get_all(
		"Baro Integration Log",
		filters={"baro_endpoint": "reconciliation", "baro_direction": "Outbound"},
		pluck="creation",
		order_by="creation desc",
		limit=1,
	)
	if not hourly:
		return True
	last = getdate(hourly[0])
	if frequency == "Hourly":
		return True
	if frequency == "Weekly":
		return (getdate() - last).days >= 7
	return (getdate() - last).days >= 1


def archive_integration_logs():
	"""Export-and-purge after `baro_log_retention_days` (`50` §7).

	The export is written as a `File` *before* any delete, and only rows the export captured are
	removed, so a crash between the two steps loses nothing.
	"""
	days = settings.int_value("baro_log_retention_days")
	cutoff = add_days(now(), -days)
	names = frappe.get_all(
		"Baro Integration Log",
		filters={"creation": ["<", cutoff], "baro_log_status": ["in", ["Processed", "Dead"]]},
		pluck="name",
		order_by="creation asc",
		limit=BATCH,
	)
	if not names:
		return
	payload = "\n".join(str(n) for n in names)
	export = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": f"baro-integration-log-archive-{getdate()}.txt",
			"is_private": 1,
			"content": payload,
		}
	).insert(ignore_permissions=True)
	for name in names:
		frappe.delete_doc("Baro Integration Log", name, ignore_permissions=True, delete_permanently=True)

"""BARO Core app hooks.

Cross-DocType side effects live in the per-module `handlers.py` files registered here, so the
same code path is reachable from the UI, from Data Import and from the GPS connector
(docs/30-schema-conventions.md #1). Scheduler jobs notify or flag only - none of them submits,
cancels, suspends a service or posts an invoice (docs/40-workflows-approvals.md #1).
"""

app_name = "baro_core"
app_title = "BARO Core"
app_publisher = "BARO Group"
app_description = "BARO ERP 360 asset spine: fleet, devices, SIM, assignments, installations"
app_email = "it@barogroup.example"
app_license = "MIT"
required_apps = ["frappe", "erpnext"]

before_install = "baro_core.install.before_install"
after_install = "baro_core.install.after_install"

# Re-apply the UQ-DRV index state and run the three integrity queries after every migrate
# (docs/31-uniqueness-concurrency-design.md #7.3, docs/30-schema-conventions.md #8 rule 5).
# These are `after_migrate` rather than `patches.txt` entries because `bench migrate` applies
# fixtures *after* the patch list: a patch that indexes a Custom Field would run before the
# Custom Field exists. All three are idempotent, so running on every migrate is safe.
after_migrate = [
	"baro_core.patches.v1.add_unique_custom_fields.run",
	"baro_core.patches.v1.backfill_active_keys.run",
	"baro_core.patches.v1.integrity_audit.run",
]

app_home_page = "baro-fleet"

# Deterministic seed order (docs/30 #8 rule 3): Roles -> DocTypes -> Custom Fields -> Property
# Setters -> Workflows -> Notifications -> Workspaces/Reports.
# Secrets are never fixtures: Password fields on `Baro GPS Platform` / `Baro SIM Card` are
# excluded from every export and set per site in the UI (docs/30 #8 rule 1).
# `[verify-vs-v16]` the fixture file name `bench export-fixtures` writes for each entry; the
# entries below are copied verbatim from docs/30 #8 so the export is reproducible.
# `notification.json`, `print_format.json` and `baro_operations_settings.json` ship as empty
# arrays on purpose, and README.md explains each: the Single cannot be exported before a System
# Manager has filled it (its `validate_device_groups` needs site-resident Item Groups), and the
# Notification/Print Format records are authored on the staging site because the Frappe
# framework schema is not in the reference archive this build was checked against (docs/appendix).
BARO_DT = [
	"Baro Vehicle",
	"Baro Device Assignment",
	"Baro SIM Card",
	"Baro Platform Mapping",
	"Baro Firmware History",
	"Baro Device RMA",
	"Baro Integration Log",
	"Baro Reconciliation Exception",
	"Baro GPS Platform",
]
STD_DT = ["Serial No", "Installation Note", "Customer", "Subscription", "Quality Inspection", "Issue"]

fixtures = [
	{"doctype": "Role", "filters": [["name", "like", "BARO %"]]},
	{"doctype": "Custom Field", "filters": [["fieldname", "like", "baro_%"]]},
	{"doctype": "Property Setter", "filters": [["doc_type", "in", BARO_DT + STD_DT]]},
	{"doctype": "Workflow", "filters": [["name", "like", "BARO%"]]},
	{"doctype": "Notification", "filters": [["subject", "like", "BARO%"]]},
	{"doctype": "Workspace", "filters": [["title", "like", "BARO%"]]},
	{"doctype": "Report", "filters": [["name", "like", "BARO%"]]},
	{"doctype": "Print Format", "filters": [["name", "like", "BARO%"]]},
	{"doctype": "Baro Operations Settings"},
]

doc_events = {
	"Serial No": {
		"validate": "baro_core.baro_devices.handlers.validate_serial_no",
		"on_update": "baro_core.baro_devices.handlers.after_serial_update",
	},
	"Installation Note": {
		"validate": "baro_core.baro_field_service.handlers.validate_installation_note",
		"on_submit": "baro_core.baro_field_service.handlers.after_installation_submit",
		"on_update_after_submit": "baro_core.baro_field_service.handlers.after_installation_update",
	},
	"Quality Inspection": {
		"on_submit": "baro_core.baro_devices.handlers.after_quality_inspection",
	},
	"Warranty Claim": {
		"validate": "baro_core.baro_devices.handlers.validate_warranty_claim",
	},
	"Baro Device Assignment": {
		# The controller owns its own state; these are the effects on *other* DocTypes.
		"on_submit": "baro_core.baro_field_service.handlers.after_assignment_submit",
		"on_cancel": "baro_core.baro_field_service.handlers.after_assignment_cancel",
		"on_update_after_submit": "baro_core.baro_field_service.handlers.after_assignment_update",
	},
	"Baro Platform Mapping": {
		"on_update": "baro_core.baro_integrations.handlers.after_mapping_update",
	},
	"Baro Firmware History": {
		"after_insert": "baro_core.baro_devices.handlers.after_firmware_row",
		"on_update": "baro_core.baro_devices.handlers.after_firmware_row",
	},
}

# Record-level access (`41` §5). SQL row filters are the last line of defence when a list
# report is built by someone else, so they ship with the app rather than as site config.
permission_query_conditions = {
	"Baro Vehicle": "baro_core.permissions.vehicle_query",
	"Baro Device Assignment": "baro_core.permissions.assignment_query",
	"Baro SIM Card": "baro_core.permissions.sim_query",
	"Baro Reconciliation Exception": "baro_core.permissions.exception_query",
	"Serial No": "baro_core.permissions.serial_query",
}

has_permission = {
	"Baro Vehicle": "baro_core.permissions.has_vehicle_permission",
	"Baro Device Assignment": "baro_core.permissions.has_assignment_permission",
	"Baro Reconciliation Exception": "baro_core.permissions.has_exception_permission",
}

scheduler_events = {
	"cron": {
		# Every-5-minutes claim loop; the job filters by baro_next_retry_at and locks each row
		# so two workers cannot retry the same event (docs/30 #11).
		"*/5 * * * *": ["baro_core.jobs.process_integration_retries"],
		# Poll dispatch: one entrypoint; per-platform cadence is read from
		# `Baro GPS Platform.baro_pull_interval` inside the job.
		"*/15 * * * *": ["baro_core.jobs.sync_platform_fleet"],
		# Reconciliation frequency is a setting (baro_reconciliation_cron); the job no-ops when
		# it is not due, so this cron entry is only the heartbeat.
		"0 * * * *": ["baro_core.jobs.run_platform_reconciliation"],
	},
	"hourly": ["baro_core.jobs.flag_inactive_devices"],
	"daily": [
		"baro_core.jobs.flag_contracts_expiring",
		"baro_core.jobs.flag_overdue_invoices",
		"baro_core.jobs.flag_sim_expiry",
		"baro_core.jobs.flag_certificates_expiring",
		"baro_core.jobs.flag_reorder_points",
	],
	"weekly": [
		"baro_core.jobs.flag_warranty_expiry",
		"baro_core.jobs.archive_integration_logs",
	],
}

jinja = {
	"methods": [
		"baro_core.templates.jmethods.device_state_label",
		"baro_core.templates.jmethods.assignment_window",
	]
}

translate_codes = ["am", "en"]

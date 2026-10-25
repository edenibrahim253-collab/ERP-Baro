# Copyright (c) 2026 BARO Group
# License: MIT. See license.txt
"""Payload storage for the integration log (`21` §7: never an inline blob).

The payload is a `File` in private storage, with credential-looking keys removed *before* it is
written. Vendor webhook bodies routinely contain the account token they were registered with;
keeping them verbatim in a table that support agents can read would turn an audit trail into a
credential store.
"""

import json

import frappe

SECRET_KEYS = (
	"authorization",
	"apikey",
	"api_key",
	"key",
	"secret",
	"webhooksecret",
	"webhook_secret",
	"token",
	"accesstoken",
	"access_token",
	"password",
	"pin",
	"puk",
	"signature",
)


def scrub(data, depth: int = 0):
	if depth > 8:
		return "[truncated]"
	if isinstance(data, dict):
		out = {}
		for key, value in data.items():
			if str(key).lower().strip() in SECRET_KEYS:
				out[key] = "[redacted]"
			else:
				out[key] = scrub(value, depth + 1)
		return out
	if isinstance(data, (list, tuple)):
		return [scrub(item, depth + 1) for item in list(data)[:200]]
	if isinstance(data, str) and len(data) > 4000:
		return data[:4000] + "…[truncated]"
	return data


def store_payload(log_doc, data) -> str | None:
	"""Attach the scrubbed payload as a private File and return its name (`baro_payload_ref` is a Link to File)."""
	content = json.dumps(scrub(data), indent=1, ensure_ascii=False, default=str)
	file_name = f"baro-intlog-{log_doc.name}.json"
	existing = frappe.db.get_value("File", {"file_name": file_name}, "name")
	if existing:
		return existing
	try:
		created = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": file_name,
				"attached_to_doctype": log_doc.doctype,
				"attached_to_name": log_doc.name,
				"is_private": 1,
				"content": content,
			}
		).insert(ignore_permissions=True)
	except Exception:  # noqa: BLE001 - a payload that cannot be stored must not lose the log row
		frappe.log_error(frappe.get_traceback(), "BARO payload storage failed")
		return None
	return created.name


def read_payload(log_doc):
	if not log_doc.baro_payload_ref:
		return None
	try:
		raw = frappe.get_doc("File", log_doc.baro_payload_ref).get_content()
		return json.loads(raw)
	except Exception:  # noqa: BLE001
		return None

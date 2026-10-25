# Copyright (c) 2026 BARO Group
# License: MIT. See license.txt
"""Worked vendor adapter example (`50` §3).

Nothing in BARO code may know a vendor's URL shape, so a vendor's shape lives exactly here: one
module per platform, exposing a class named `Adapter`, registered as
`Baro GPS Platform.baro_adapter_module = "baro_core.integrations.vendor_template"`.

Copy this file per vendor and change three things - `auth_headers`, the endpoint paths, and
`DEVICE_KEYS`, the map from the vendor's own field names onto `PlatformDevice`. The reduce step is
the contract: whatever the vendor sends beyond those keys is dropped here rather than becoming an
implicit dependency somewhere else.

`Q2` in `70-open-questions-stakeholders.md` decides the real vendors, so this module is a
template, not an integration: `baro_enabled` stays off for a platform pointing at it, and
`Baro GPS Platform.validate` requires an https base URL plus credentials before anything runs.
"""

import frappe

from baro_core.integrations.base import PlatformAdapter, reduce_fleet

# vendor field name -> PlatformDevice field name
DEVICE_KEYS = {
	"id": "platform_device_id",
	"imei": "imei",
	"sn": "serial_hint",
	"groupid": "group_id",
	"state": "status",
	"fwver": "firmware",
	"lasttime": "last_comm_at",
}


class Adapter(PlatformAdapter):
	def auth_headers(self) -> dict:
		token = self.platform.get_password("baro_api_key")
		return {"Authorization": f"Bearer {token}", "Accept": "application/json"}

	def list_fleet(self):
		return self.fetch_devices("/api/devices", rows_key="data")

	def get_status(self, platform_device_ids: list[str]):
		return self.fetch_devices(
			"/api/devices/status",
			rows_key="data",
			params={"ids": ",".join(platform_device_ids)},
			method="GET",
		)

	def normalise(self, rows) -> list[dict]:
		"""Rename vendor keys onto PlatformDevice; `reduce_fleet` then enforces the shape."""
		out = []
		for row in rows or []:
			mapped = {DEVICE_KEYS.get(str(key).lower(), key): value for key, value in row.items()}
			mapped.setdefault("platform_device_id", str(row.get("id") or ""))
			out.append(mapped)
		return reduce_fleet(out)

	def verify_signature(self, body: bytes, signature: str | None) -> bool:
		"""Vendor signs `timestamp + body`; the default HMAC over the raw body alone is not enough.

		Anything malformed returns False rather than raising - this runs on untrusted input, and a
		bad header must look like a failed authentication, not a 500.
		"""
		import hashlib
		import hmac

		from frappe.utils import get_datetime, now_datetime

		secret = self.platform.get_password("baro_webhook_secret")
		if not (secret and signature and "|" in signature):
			return False
		timestamp, _, digest = signature.partition("|")
		try:
			sent = get_datetime(timestamp)
		except (ValueError, TypeError):
			return False
		if abs((now_datetime() - sent).total_seconds()) > 300:
			return False
		expected = hmac.new(secret.encode("utf-8"), f"{timestamp}\n".encode() + (body or b""), hashlib.sha256).hexdigest()
		return hmac.compare_digest(expected, digest)

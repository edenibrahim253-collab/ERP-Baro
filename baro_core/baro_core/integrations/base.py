# Copyright (c) 2026 BARO Group
# License: MIT. See license.txt
"""The platform-agnostic client contract (`50` §3).

A vendor adapter implements four operations and nothing else: authenticate, list the fleet,
read status for a set of device ids, and prove an inbound payload came from the platform.
Keeping the surface that small is what lets `Baro GPS Platform.baro_adapter_module` stay
configuration rather than code.

Every call returns `AdapterResult`, so the caller always learns the error *class* - Timeout,
Auth, RateLimit, Payload, Server, Unknown - which is what decides whether the event is retried,
dead-lettered, or turned into a reconciliation exception. A bare exception string cannot drive
that decision.
"""

import importlib
import json

import frappe
from frappe.utils import now_datetime

TIMEOUT = "Timeout"
AUTH = "Auth"
RATE_LIMIT = "RateLimit"
PAYLOAD = "Payload"
SERVER = "Server"
UNKNOWN = "Unknown"

# Which classes are worth another attempt: a timeout or a 5xx may succeed later; a 401 or a
# malformed body will not, and retrying it only burns the rate limit.
RETRYABLE = {TIMEOUT, RATE_LIMIT, SERVER}

# `50` §3 PlatformDevice: the only fields a vendor may deliver upward. The adapter's job is to
# *reduce* the platform's model to these keys - a richer dict reaching BARO code means a vendor
# schema has quietly become a BARO dependency, and the next vendor cannot be added without it.
PLATFORM_DEVICE_FIELDS = (
	"platform_device_id",
	"imei",
	"serial_hint",
	"group_id",
	"status",
	"firmware",
	"last_comm_at",
	"raw_ref",
)


def reduce_device(row: dict) -> dict:
	"""Project one vendor row onto PlatformDevice, dropping everything else."""
	if not isinstance(row, dict):
		raise AdapterError(f"fleet row is {type(row).__name__}, expected an object", PAYLOAD)
	out = {}
	for key in PLATFORM_DEVICE_FIELDS:
		value = row.get(key)
		if value is None:
			continue
		out[key] = str(value).strip() if isinstance(value, str) else value
	if not out.get("platform_device_id"):
		raise AdapterError("fleet row has no platform_device_id", PAYLOAD)
	return out


def reduce_fleet(rows) -> list[dict]:
	return [reduce_device(row) for row in (rows or [])]


class AdapterError(Exception):
	def __init__(self, message: str, error_class: str = UNKNOWN, http_status: int = None):
		super().__init__(message)
		self.error_class = error_class if error_class in (TIMEOUT, AUTH, RATE_LIMIT, PAYLOAD, SERVER, UNKNOWN) else UNKNOWN
		self.http_status = http_status


class AdapterResult:
	"""Outcome of one outbound call: ok, the payload, and the failure classification."""

	def __init__(self, ok: bool, data=None, error: AdapterError = None):
		self.ok = ok
		self.data = data
		self.error = error
		self.at = now_datetime()

	@property
	def error_class(self) -> str:
		return self.error.error_class if self.error else "None"

	def to_log_fields(self) -> dict:
		return {
			"baro_http_status": self.error.http_status if self.error else 200,
			"baro_error_class": self.error_class,
			"baro_error_message": str(self.error) if self.error else None,
		}


class PlatformAdapter:
	"""Base class vendors extend. Subclasses must not touch Frappe documents."""

	def __init__(self, platform_doc):
		self.platform = platform_doc
		self.base_url = (platform_doc.baro_base_url or "").rstrip("/")
		self.timeout = int(platform_doc.baro_timeout_secs or 15)

	def session(self):
		import requests

		session = requests.Session()
		session.headers.update(self.auth_headers())
		session.timeout = self.timeout
		return session

	def auth_headers(self) -> dict:
		raise NotImplementedError

	def list_fleet(self) -> "AdapterResult":
		"""data = [PlatformDevice] (`50` §3) - the platform's view of the fleet it holds."""
		raise NotImplementedError

	def get_status(self, platform_device_ids: list[str]) -> "AdapterResult":
		raise NotImplementedError

	def fetch_devices(self, path: str, rows_key: str = None, params: dict = None, method: str = "GET") -> "AdapterResult":
		"""Fetch one page and hand it through `normalise`. Adapters implement paging/auth, never field invention."""
		result = self.request(method, path, params=params)
		if not result.ok:
			return result
		rows = result.data
		if isinstance(rows, dict):
			rows = rows.get(rows_key) if rows_key else rows.get("data") or rows.get("rows") or rows.get("devices") or []
		try:
			return AdapterResult(True, self.normalise(rows))
		except AdapterError as error:
			return AdapterResult(False, None, error)

	def normalise(self, rows) -> list[dict]:
		"""Vendor field names -> PlatformDevice. Override per vendor; the reduce step is not optional."""
		return reduce_fleet(rows)

	def verify_signature(self, body: bytes, signature: str | None) -> bool:
		"""Default: HMAC-SHA256 of the raw body against the platform's webhook secret."""
		import hashlib
		import hmac

		secret = self.platform.get_password("baro_webhook_secret")
		if not secret:
			return False
		if not signature:
			return False
		digest = hmac.new(secret.encode("utf-8"), body or b"", hashlib.sha256).hexdigest()
		return hmac.compare_digest(digest, signature.split("=")[-1].strip())

	def request(self, method: str, path: str, **kwargs) -> AdapterResult:
		import requests

		url = f"{self.base_url}/{path.lstrip('/')}"
		try:
			response = self.session().request(method, url, **kwargs)
		except requests.Timeout as error:
			return AdapterResult(False, None, AdapterError(str(error), TIMEOUT))
		except requests.RequestException as error:
			return AdapterResult(False, None, AdapterError(str(error), UNKNOWN))
		except Exception as error:  # noqa: BLE001 - an unexpected failure still has to be classified, not raised
			return AdapterResult(False, None, AdapterError(str(error), classify(error)))
		if response.status_code == 429 or (response.status_code == 403 and "rate" in response.text.lower()):
			return AdapterResult(False, None, AdapterError("rate limited", RATE_LIMIT, response.status_code))
		if response.status_code == 401:
			return AdapterResult(False, None, AdapterError("authentication rejected", AUTH, response.status_code))
		if 500 <= response.status_code < 600:
			return AdapterResult(False, None, AdapterError(response.text[:500], SERVER, response.status_code))
		if response.status_code >= 400:
			return AdapterResult(False, None, AdapterError(response.text[:500], PAYLOAD, response.status_code))
		try:
			return AdapterResult(True, response.json())
		except ValueError:
			return AdapterResult(True, {"text": response.text})


def classify(error) -> str:
	"""Map an arbitrary exception onto one of the six error classes.

	Called when a connector itself blows up (`requests` not installed, a vendor SDK raising
	inside the adapter) and therefore returns no `AdapterResult`. The decision it drives - retry
	or dead-letter - must not depend on the exception text being clean.
	"""
	if isinstance(error, AdapterError):
		return error.error_class
	text = str(error).lower()
	if isinstance(error, (ValueError, KeyError, TypeError, AttributeError)):
		return PAYLOAD
	if "timeout" in text or "timed out" in text:
		return TIMEOUT
	if "401" in text or "403" in text or "auth" in text or "signature" in text or "token" in text:
		return AUTH
	if "429" in text or "rate" in text:
		return RATE_LIMIT
	if "server error" in text or "internal" in text or "unavailable" in text:
		return SERVER
	return UNKNOWN


def resolve(platform_name: str) -> PlatformAdapter:
	"""Instantiate the adapter named on the `Baro GPS Platform` row."""
	doc = frappe.get_doc("Baro GPS Platform", platform_name)
	module_path = doc.baro_adapter_module
	try:
		module = importlib.import_module(module_path)
	except ImportError as error:
		frappe.throw(
			frappe._("Connector module {0} cannot be imported: {1}").format(module_path, error)
		)
	adapter_class = getattr(module, "Adapter", None)
	if not adapter_class:
		frappe.throw(
			frappe._("Connector module {0} must expose a class named Adapter").format(module_path)
		)
	return adapter_class(doc)


def json_default(obj):
	if isinstance(obj, AdapterResult):
		return {"ok": obj.ok, "error": obj.error_class}
	return str(obj)


def as_json(data) -> str:
	return json.dumps(data, default=json_default, ensure_ascii=False)

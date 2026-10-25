"""Named locks around check-and-write (docs/31-uniqueness-concurrency-design.md #5.2).

Rules encoded here:
* one coarse namespace lock plus one lock per contested key;
* keys acquired in sorted order, so two callers can never hold half a deadlock;
* every lock has an expiry, so a crashed worker cannot strand an assignment forever;
* the integration retry poller uses the same namespace, which is what stops a webhook
  replay and a human submit from interleaving.

`frappe.cache().lock()` availability across frappe versions is a [verify-vs-v16] item; if the
pinned version lacks it, the MariaDB GET_LOCK path below is used and behaves the same way.
"""

from contextlib import contextmanager

import frappe

NAMESPACE = "baro"
DEFAULT_EXPIRY = 30


def _redis_lock(key: str, expiry: int):
	cache = frappe.cache()
	lock = getattr(cache, "lock", None)
	if callable(lock):
		return lock(key, expiry=expiry)
	return None


@contextmanager
def acquired(keys: list[str], expiry: int = DEFAULT_EXPIRY):
	"""Take every key in sorted order; release in reverse. Raises device_busy if contended."""
	from baro_core.exceptions import device_busy

	handles = []
	try:
		for key in sorted(set(keys)):
			full = f"{NAMESPACE}:{key}"
			handle = _redis_lock(full, expiry)
			if handle is None:
				# Fallback: MariaDB advisory lock, released explicitly below.
				got = frappe.db.sql("SELECT GET_LOCK(%s, %s)", (full, 1))[0][0]
				if not got:
					device_busy()
				handles.append(("sql", full))
				continue
			if not handle.acquire(blocking=False):
				device_busy()
			handles.append(("redis", handle))
		yield
	finally:
		for kind, item in reversed(handles):
			try:
				if kind == "redis":
					item.release()
				else:
					frappe.db.sql("SELECT RELEASE_LOCK(%s)", item)
			except Exception:
				# An un-released lock expires on its own; never mask the original error.
				frappe.log_error(title="BARO lock release failed")


def assignment_keys(serial_no: str | None = None, vehicle: str | None = None) -> list[str]:
	keys = ["assign"]
	if serial_no:
		keys.append(f"assign:serial:{serial_no}")
	if vehicle:
		keys.append(f"assign:vehicle:{vehicle}")
	return keys


def platform_lock(platform: str) -> str:
	return f"sync:{platform}"


def reconciliation_lock(platform: str) -> str:
	return f"recon:{platform}"


def retry_claim_lock(log_name: str) -> str:
	return f"retry:{log_name}"

# Copyright (c) 2026 BARO Group
# License: MIT. See license.txt
"""Per-platform token bucket (`50` §6).

The limit is read from `Baro GPS Platform.baro_rate_limit_per_min` because every vendor publishes
a different one, and exceeding it is the most common way an integration degrades itself: a
throttled platform returns 429, the retry ladder burns more quota, and the fleet's status data
goes stale exactly when it is needed.

State lives in the Redis cache, not the database - a bucket is a transient counter, and writing
it per request would make the limiter the bottleneck it exists to prevent.
"""

import time

import frappe

CACHE_TTL = 120


def _key(platform: str) -> str:
	return f"baro:ratelimit:{platform}"


def bucket(platform: str, per_minute: int) -> dict:
	"""{tokens, capacity, updated}. Missing bucket == full bucket."""
	cache = frappe.cache()
	state = cache.get_value(_key(platform))
	if isinstance(state, str):
		import json

		try:
			state = json.loads(state)
		except ValueError:
			state = None
	capacity = max(1, int(per_minute or 60))
	if not state or state.get("capacity") != capacity:
		state = {"tokens": capacity, "capacity": capacity, "updated": time.time()}
		return state
	elapsed = time.time() - float(state.get("updated") or 0)
	refill = int(elapsed * capacity / 60.0)
	if refill:
		state["tokens"] = min(capacity, int(state.get("tokens", 0)) + refill)
		state["updated"] = state["updated"] + refill * 60.0 / capacity
	return state


def allow(platform: str, per_minute: int, cost: int = 1) -> bool:
	state = bucket(platform, per_minute)
	if state["tokens"] < cost:
		return False
	state["tokens"] -= cost
	_store(platform, state)
	return True


def wait_seconds(platform: str, per_minute: int) -> float:
	state = bucket(platform, per_minute)
	if state["tokens"] >= 1:
		return 0.0
	capacity = max(1, int(per_minute or 60))
	return round((1 - state["tokens"]) * 60.0 / capacity, 2)


def _store(platform: str, state: dict) -> None:
	import json

	# Stored as a JSON string rather than a python object: the Redis wrapper's serialisation
	# differs across frappe versions, a string does not. [verify-vs-v16]
	frappe.cache().set_value(_key(platform), json.dumps(state), expires_in_sec=CACHE_TTL)


def consume_for_platform(platform_name: str, cost: int = 1) -> bool:
	"""Convenience wrapper used by sync and retry: reads the limit off the platform row."""
	per_minute = frappe.db.get_value("Baro GPS Platform", platform_name, "baro_rate_limit_per_min") or 60
	return allow(platform_name, int(per_minute), cost)

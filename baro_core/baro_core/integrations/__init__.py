# Copyright (c) 2026 BARO Group
# License: MIT. See license.txt
"""GPS platform integration package (`50`).

`base.py` is the platform-agnostic contract, `<vendor>.py` implements it, `webhook.py` handles
inbound events, `sync.py` polls, `retry.py` drives the retry ladder and `reconciliation.py`
produces the three-way diff. Nothing in this package imports a vendor name: the adapter is
resolved from `Baro GPS Platform.baro_adapter_module` at runtime, so adding or retiring a
platform is configuration, not a code edit (`50` §3).
"""

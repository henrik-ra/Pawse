"""Xiaomi smartwatch integration for Pawse.

The Redmi Watch 4 uses Xiaomi's encrypted proprietary protocol, so data is read
via **Gadgetbridge**:

- ``gadgetbridge_client`` — read a Gadgetbridge SQLite export. Pair the watch in
  the Gadgetbridge Android app, then sync its database here (see
  ``sync_gadgetbridge.ps1``).

``xiaomi_client.get_daily_signals(date)`` is the unified entry point used by the
rest of Pawse; it routes to the Gadgetbridge backend and always falls back to
realistic demo data so the dashboard never breaks.
"""

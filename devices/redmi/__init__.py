"""Redmi smartwatch integration for Pawse.

Three interchangeable backends read the same Redmi/Xiaomi watch; pick whichever
works best for your setup:

- ``ble_client``          — BLE direct from this PC (bleak). True real-time HR.
- ``gadgetbridge_client`` — read a Gadgetbridge SQLite export. Most reliable.
- ``zepp_client``         — Zepp Life / Mi Fitness cloud (unofficial).

``redmi_client.get_daily_signals(date)`` is the unified entry point used by the
rest of Pawse; it routes to a backend (``REDMI_BACKEND`` env var) and always
falls back to realistic demo data so the dashboard never breaks.
"""

# Apple Watch

Reads **steps** and **heart-rate** from Apple Health (HealthKit).

- **Demo mode:** `apple_watch_client.py` returns mock data.
- **Real mode (later):** Apple Health data export (`export.xml`) or a companion iOS app
  using HealthKit. There is no public cloud REST API — data comes via the device export.

## Usage

```python
from devices.apple_watch.apple_watch_client import get_daily_signals

signals = get_daily_signals("2026-06-18")
```

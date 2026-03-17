# Weight Gurus BLE

Custom Home Assistant integration for Weight Gurus `LS212-B` / A6-family BLE
scales.

The integration uses Home Assistant's Bluetooth stack for discovery and active
connections, so it can work through local adapters or Bluetooth proxies. It
supports the reverse-engineered A6 handshake, captures live measurements, and
computes the same profile-based estimates the vendor app derives locally.

## Status

This integration is currently targeted at the `LS212-B` scale family using the
`20568521-5acd-4c5a-9294-eb2691c8b8bf` BLE service.

The following entities are exposed:

- `weight`
- `battery`
- `bmi`
- `body_fat_percent`
- `muscle_percent`
- `body_water_percent`
- `impedance_metric`
- `measured_at`

## Requirements

- Home Assistant `2026.3.0` or newer
- HACS
- A working local Bluetooth adapter or Home Assistant Bluetooth proxy

## Installation

### HACS custom repository

1. Open HACS.
2. Go to the custom repositories dialog.
3. Add `https://github.com/rtclauss/weightgurus-ble` as an `Integration`
   repository.
4. Install `Weight Gurus BLE`.
5. Restart Home Assistant.

### Integration setup

1. Go to `Settings -> Devices & Services`.
2. Add `Weight Gurus BLE`.
3. Select or enter the Bluetooth address for the scale.
4. Open the integration options and enter:
   - `height_cm`
   - `birthday`
   - `sex`
   - `athlete`

Age is calculated from `birthday` at measurement time, so it updates
automatically on birthdays.

## Bluetooth behavior

When the scale advertises, Home Assistant opens a short active BLE session,
completes the A6 login and initialization sequence, requests the live reading,
and updates the sensor entities from the resulting `0x4802` payload.

## Notes

- The derived body metrics are app-style estimates based on weight, impedance,
  birthday, height, sex, and athlete mode.
- This repository contains the reverse-engineering workarea and helper scripts
  used to develop the integration. HACS only installs the
  `custom_components/weightgurus_ble` directory.

## Development

The repo still includes the local reverse-engineering utilities under
`scripts/` and notes under `workarea/`. Example A6 session command:

```bash
.venv/bin/python scripts/a6_session.py --name "LS212-B" --send-live --height-cm 180 --birthday 1990-03-03 --sex male --not-athlete
```

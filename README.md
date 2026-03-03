# Weight Gurus BLE

Workspace for reverse-engineering the BLE behavior of a Weight Gurus scale and
building a Home Assistant custom component that can later be packaged for HACS.

## Current layout

- `workarea/`: reverse-engineering artifacts, notes, captures, and generated output
- `scripts/`: local utilities for discovery and protocol analysis
- `custom_components/weightgurus_ble/`: future Home Assistant integration code

## Local environment

The local Python environment is already created in `.venv`.

Activate it with:

```bash
source .venv/bin/activate
```

Run the initial BLE discovery helper with:

```bash
.venv/bin/python scripts/ble_scan.py --timeout 8 --name "weight"
```

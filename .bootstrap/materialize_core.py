from __future__ import annotations

# Temporary bootstrap helper used while assembling the initial repository snapshot.
# It is intentionally not imported by the integration and will be removed once
# custom_components/tuya_local_ble/tuya_ble/tuya_ble.py is materialized.

import base64
import pathlib
import zlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAYLOAD = ROOT / ".bootstrap" / "tuya_ble.py.zlib.b64"
OUTPUT = ROOT / "custom_components" / "tuya_local_ble" / "tuya_ble" / "tuya_ble.py"

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
OUTPUT.write_bytes(zlib.decompress(base64.b64decode(PAYLOAD.read_text().strip())))
print(OUTPUT)

# YD_350K protocol notes

These notes describe only behavior observed during this project. They are intentionally kept separate from user-specific credentials and captures.

## Transport and security

The lock advertises the Tuya FD50 service and uses the TuyaOS v2 packet path.

Observed security flags:

- `0x0e` for the DEVICE_INFO/login exchange.
- `0x0f` after the session key is derived.

For this product, the working derivations are:

```text
login_key   = MD5(full_localKey || secKey)
session_key = MD5(full_localKey || secKey || srand)
```

The `srand` bytes are taken from the DEVICE_INFO response.

## V4 status frames

Ordinary frame plaintext:

```text
[event_seq:5] 80 [kind:1] [dp_id:1] [type:1] [len:2] [value:len]
```

Timed event plaintext:

```text
[event_seq:5] 00 [kind:1] 01 [timestamp:4] [dp_id:1] [type:1] [len:2] [value:len]
```

The first five bytes are a rolling 40-bit event sequence.

## Confirmed behavior

### Passage mode

DP33 boolean writes are accepted by the lock and reflected back as state:

- `DP33=true`: passage/automatic-lock suppression enabled.
- `DP33=false`: normal automatic locking restored.

A successful fingerprint/PIN operation can cause firmware to clear passage mode and resume normal auto-lock behavior.

### Lock state

DP47 is the authoritative physical state observed from the lock:

- `true`: unlocked.
- `false`: locked.

The unlocked report may arrive a few seconds after the initiating authentication event; callers should not infer motor state solely from an access event.

### Secure/reverse lock

Physical secure-lock operation produces DP32 and DP79 together:

- secure on: DP32=true and DP79=true
- secure off: DP32=false and DP79=false

Direct DP32 writes are acknowledged at the transport level but do not reliably change the physical mode. The current implementation therefore treats DP32 as reported state and uses DP79 as the control candidate.

## Lock/unlock controls

DP46 (`manual_lock=true`) is confirmed to physically lock the 350K. DP47 remains the authoritative physical state. An experimental Home Assistant lock entity is available (disabled by default): Lock uses DP46, Unlock uses the still-experimental DP71 authenticated BLE flow, and neither command changes DP47 optimistically.


## Protocol logging

The old per-lock `Verbose protocol logging` and `Keep BLE connection alive` switches have been removed. Configure both from **Settings → Devices & services → Tuya BLE → Configure**. Logging levels are `Off`, `Parsed events`, and `Raw frames + events`. Raw mode can expose lock event details in logs and should normally remain off.


## Experimental DP71 unlock

Previous Smart Life HCI captures showed the first app unlock after a fresh BLE connection as a 68-byte GATT write. That size matches the existing TuyaOS FD50 DP71 (`0x47`) unlock-check command exactly after Tuya header/CRC, AES padding, security flag, IV, and BLE packet framing. The experimental Home Assistant button therefore reuses the existing device-specific `ble_unlock_check` transformation and sends it through `FUN_SENDER_DPS_V4`. The button is disabled by default and does not change state optimistically; DP47 remains authoritative.


## Additional experimental features

- DP19 (`unlock_ble`) is mirrored into the last-access-event sensors as `bluetooth_unlock` when reported.
- DP31 is exposed as Lock volume (`mute`, `low`, `normal`, `high`).
- DP28 is exposed as Lock language (`chinese_simplified`, `english`) for this product schema.
- Disabled-by-default diagnostic sensors expose recent ACK latency and GATT write sizing/count without storing decrypted authorization material.

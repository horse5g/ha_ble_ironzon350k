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

A successful fingerprint operation has been observed clearing passage mode and restoring normal auto-lock behavior. PIN behavior should remain treated as unconfirmed until it is reproduced independently.

### Lock state

DP47 is the authoritative physical state observed from the lock:

- `true`: unlocked.
- `false`: locked.

The unlocked report may arrive a few seconds after the initiating authentication event; callers should not infer motor state solely from an access event.

The 350K's generic `FUN_SENDER_DEVICE_STATUS` request has not been observed to return DP47 on demand. It acknowledges the request and may emit other current datapoints such as battery/configuration state, but a successful status request must not be treated as proof that the physical lock state was refreshed. The Home Assistant button is therefore labeled **Request device status** rather than **Refresh lock status**.

### Secure/reverse lock

Physical secure-lock operation produces DP32 and DP79 together:

- secure on: DP32=true and DP79=true
- secure off: DP32=false and DP79=false

Direct DP32 writes are acknowledged at the transport level but do not reliably change the physical mode. DP32 is therefore treated as reported state. DP79 control has now been physically confirmed and is used for secure-lock control.

### Remote lock

DP46 (`manual_lock=true`) is confirmed to physically lock the 350K. DP47 remains the authoritative physical state. The experimental Home Assistant lock entity uses DP46 for Lock and does not update DP47 optimistically.

Two Home Assistant-only DP46 lock operations produced the same timed DP20 record immediately before the authoritative DP47 locked report:

```text
04 00 00 00 ff
```

This is strong evidence that DP20 records beginning with `0x04` are associated with the remote/HA lock actuation path. The remaining bytes are not yet assigned semantics.

A different timed DP20 record has repeatedly appeared around fresh connection/status synchronization without a user actuation:

```text
06 00 00 00 01
```

That value should not currently be interpreted as an access or motor action. It may represent a synchronization/status record or a replayed/current lock record; more captures are required.

## Implemented but awaiting physical validation

- DP71 authenticated BLE unlock path / `ble_unlock_check`.
- DP19 BLE/app unlock event interpretation.
- DP31 volume selector values and reporting.
- DP28 language selector values and reporting.
- The full Home Assistant lock entity path after the recent transport/diagnostic changes, especially Unlock.

## Protocol logging

The old per-lock `Verbose protocol logging` and `Keep BLE connection alive` switches have been removed. Configure both from **Settings → Devices & services → Tuya BLE → Configure**. Logging levels are `Off`, `Parsed events`, and `Raw frames + events`. Raw mode can expose lock event details in logs and should normally remain off.

## Experimental DP71 unlock

Previous Smart Life HCI captures showed the first app unlock after a fresh BLE connection as a 68-byte GATT write. That size matches the existing TuyaOS FD50 DP71 (`0x47`) unlock-check command exactly after Tuya header/CRC, AES padding, security flag, IV, and BLE packet framing. The experimental Home Assistant button therefore reuses the existing device-specific `ble_unlock_check` transformation and sends it through `FUN_SENDER_DPS_V4`. The button is disabled by default and does not change state optimistically; DP47 remains authoritative.

## Additional experimental features

- DP19 (`unlock_ble`) is mirrored into the last-access-event sensors as `bluetooth_unlock` when reported.
- DP31 is exposed as Lock volume (`mute`, `low`, `normal`, `high`).
- DP28 is exposed as Lock language (`chinese_simplified`, `english`) for this product schema.
- Diagnostic sensors expose recent ACK latency and GATT write sizing/count without storing decrypted authorization material.
- A raw DP20 diagnostic retains the exact plaintext lock record for reverse engineering. It is intentionally separate from the sanitized recorder/export and must be treated as sensitive diagnostic data.

## BLE proxy reliability note

An earlier long-delay/reliability problem was traced to faulty ESP proxy hardware. After replacing that ESP, command handling became reliable. Do not treat that earlier delay as evidence of an inherent 350K session or command-timing requirement.

The integration now treats expected ESPHome proxy loss during disconnect as an already-closed link, aborts outstanding response waiters when the BLE transport disappears, and suppresses full tracebacks for those handled disconnect conditions. Unexpected exceptions still retain normal traceback logging.
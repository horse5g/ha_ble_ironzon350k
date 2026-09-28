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

## Pending lock/unlock controls

Remote lock/unlock are deliberately not exposed as a normal HA lock entity yet.

Current candidates:

- DP46 (`manual_lock`) for lock.
- DP71 raw BLE unlock/check flow for unlock.

The exact official-app unlock payload still needs to be decoded/validated before enabling remote unlock.


## Protocol logging

The old per-lock `Verbose protocol logging` switch has been removed. Configure logging from **Settings → Devices & services → Tuya BLE → Configure**. Levels are `Off`, `Parsed events`, and `Raw frames + events`. Raw mode can expose lock event details in logs and should normally remain off.

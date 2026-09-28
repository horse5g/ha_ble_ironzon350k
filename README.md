# HA BLE Ironzon 350K

Experimental Home Assistant support for the Ironzon/YD_350K Tuya BLE lock (`product_id: z1dfsaya`), built on top of ShonP40/Tuya-BLE.

> [!WARNING]
> This is reverse-engineered, device-specific code. Keep a working physical/keypad/fingerprint entry method available while testing remote controls. Do not expose raw protocol logs publicly; they can contain credential IDs and other lock event data.

## Current status

Working in the current test setup:

- TuyaOS FD50 BLE transport.
- 0x0e login key derivation from the full `localKey + secKey`.
- 0x0f session key derivation from `localKey + secKey + srand`.
- Tuya V4 ordinary and timed datapoint parsing.
- Battery reporting (DP8).
- Physical lock-state reporting (DP47; `true` = unlocked, `false` = locked).
- Passage/automatic-lock control via DP33.
- Secure-lock state reporting via DP32.
- Secure-lock control via DP79 (confirmed in live testing).
- Remote lock via DP46=`true` (confirmed in live testing).
- Access-event diagnostics for fingerprint/PIN/failure events.
- BLE/app unlock event detection from DP19 when reported by firmware.
- Configurable 350K protocol logging under the integration Configure dialog (`Off`, `Parsed events`, `Raw frames + events`).
- Optional BLE connection keeper configured from the integration Configure dialog.
- Lock volume select via DP31.
- Lock language select via DP28.
- Experimental Home Assistant `lock` entity using DP47 as authoritative state, DP46 for lock, and the inferred DP71 unlock path.
- Optional transport diagnostic sensors for command/connection testing.

Still experimental:

- Remote unlock through DP71 / `ble_unlock_check`. The framing is inferred from previous Smart Life captures and related TuyaOS FD50 locks and still needs repeated physical validation on the 350K.
- The experimental HA lock entity is disabled by default in the entity registry because its Unlock action uses the DP71 path.
- Exact semantics of several event/history datapoints are not fully understood.

## Experimental branch

Current active test work lives on:

```text
experiment/dp46-lock
```

To install that branch manually from the Home Assistant bash shell:

```bash
cd /tmp
rm -rf ha_ble_ironzon350k-dp46

git clone \
  --depth 1 \
  --branch experiment/dp46-lock \
  https://github.com/horse5g/ha_ble_ironzon350k.git \
  ha_ble_ironzon350k-dp46

SRC=/tmp/ha_ble_ironzon350k-dp46/custom_components/tuya_local_ble
DEST=/config/custom_components/tuya_local_ble

cp -a "$SRC"/. "$DEST"/
```

Restart Home Assistant after copying the files.

## Experimental entities and options

### Integration options

Open **Settings → Devices & services → Tuya BLE → Configure**.

- **Keep BLE connection alive** — periodically keeps an already-authenticated 350K BLE session warm. It does not deliberately wake a disconnected/sleeping lock.
- **350K protocol logging**
  - `Off` — normal integration logging only.
  - `Parsed events` — decoded 350K datapoints, timed events, command acknowledgements, and useful protocol timing.
  - `Raw frames + events` — also logs encrypted BLE fragments and decrypted Tuya V4 payloads. Use only for short troubleshooting sessions.

### Normal device entities

- Battery
- Lock state
- Passage mode
- Passage mode control
- Secure-lock state/control
- Lock volume
- Lock language
- Last access event
- Last successful credential ID
- Last access event time

### Disabled-by-default experimental/diagnostic entities

Enable these from the device's entity list when testing:

- **350K lock (experimental)**
- **Last lock record**
- **Last TX ACK latency**
- **Last GATT write count**
- **Largest last GATT write**
- **GATT write chunk size**

The experimental lock entity does not optimistically change DP47. Lock/unlock state remains based on the value physically reported by the lock.

## Suggested test sequence

For reproducible testing, set protocol logging to **Parsed events** first. Raw mode is normally unnecessary.

1. **Baseline state**
   - Confirm battery, DP47 lock state, volume, and language populate after connection.
   - Confirm the integration does not continuously reconnect when Keep BLE connection alive is off.

2. **Passage mode**
   - Turn passage mode on and off from Home Assistant.
   - Confirm the physical lock behavior changes and DP33 echoes the resulting state.
   - Also test locking while passage mode is enabled; current lock firmware appears to leave passage enabled, so this should be treated as device behavior rather than automatically cleared by the integration unless further evidence says otherwise.

3. **Volume (DP31)**
   - Change one step at a time and verify the audible response.
   - Confirm the lock reports the new DP31 value afterward.

4. **Language (DP28)**
   - Switch language, verify voice prompts, then switch it back.
   - Confirm DP28 reports the selected value.

5. **Lock command (DP46)**
   - With the door open/safe to test, invoke Lock from the experimental lock entity.
   - Confirm the motor actuates and DP47 changes to `false`.
   - Confirm HA transitions from `locking` to `locked` from the actual DP47 report.

6. **Unlock command (DP71, experimental)**
   - Keep a local entry method available.
   - Invoke Unlock once; do not repeatedly click while an operation is pending.
   - A successful test should physically unlock and then produce DP47=`true`.
   - Capture only sanitized parsed logs when reporting results; do not publish keys or raw authenticated captures.

7. **Access-event detection**
   - Unlock once each with fingerprint, PIN, and the Tuya/HA BLE path.
   - Check `Last access event`, credential ID, and timestamp.
   - Current identified events include `fingerprint_unlock`, `pin_unlock`, `bluetooth_unlock`, `failed_fingerprint`, and `failed_pin`.

8. **Transport diagnostics**
   - Compare a cold/on-demand operation with an operation while Keep BLE connection alive is enabled.
   - Record ACK latency, GATT write count, largest write, and configured write chunk size.
   - These are diagnostic measurements, not lock-state inputs.

## What results are useful to report

For each experiment, the most useful sanitized information is:

- action performed,
- whether the motor/configuration physically changed,
- parsed DP IDs/types/values before and after,
- command acknowledged or timed out,
- ACK latency,
- whether the BLE connection stayed alive or reconnected,
- any unexpected state transition.

Avoid posting `devices.json`, local keys, secKeys, devKeys, Tuya account/session credentials, ESPHome API/Noise keys, or raw HCI snoop captures.

## 350K datapoints currently understood

| DP | Meaning / current interpretation |
|---:|---|
| 8 | Battery percentage |
| 12 | Successful fingerprint credential ID |
| 13 | Successful PIN credential ID |
| 19 | BLE/app unlock event / credential value when reported |
| 20 | Lock event record (raw; exact byte semantics incomplete) |
| 21 | Failed credential/alarm event |
| 28 | Language enum |
| 31 | Beep volume enum |
| 32 | Secure/reverse-lock **reported state** |
| 33 | Passage / automatic-lock suppression control |
| 46 | Tuya `manual_lock`; `true` is confirmed to physically lock |
| 47 | Physical lock state (`true` unlocked, `false` locked) |
| 68 | Special function enum |
| 71 | BLE unlock/check raw command; experimental unlock path |
| 78 | Special control boolean; exact role unknown |
| 79 | Secure-lock control; confirmed, with DP32 as reported secure state |

## Transport diagnostics

The 350K test branch can expose local-only diagnostic values for the most recent outbound request:

- response/ACK latency in milliseconds,
- number of GATT writes used,
- largest GATT write size,
- selected GATT write chunk size.

These are intended to help compare ESPHome Bluetooth proxies, connection-keeper behavior, MTU/chunking changes, and cold-versus-warm command latency without enabling raw packet logging.

## BLE proxy notes

The integration works best with an active ESPHome Bluetooth proxy and a stable API/Wi-Fi connection. The optional 350K connection keeper only keeps an already-open BLE session alive; it does not force a disconnected or unreachable lock to reconnect.

For latency testing, Wi-Fi/API stability of the proxy is generally more important than placing the proxy as close as physically possible to the lock.

## Repository policy

The working integration belongs under `custom_components/tuya_local_ble/`.

Credentials and captures stay out of GitHub. Do **not** commit `devices.json`, local keys, secKeys, devKeys, account credentials, authenticated API responses, raw HCI snoop logs, APKs, or credential-bearing Home Assistant logs.

## Upstream

This project currently carries modifications to the `tuya_local_ble` integration from ShonP40/Tuya-BLE while the 350K-specific protocol work is still experimental.

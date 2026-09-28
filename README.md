# HA BLE Ironzon 350K

Experimental Home Assistant support for the Ironzon/YD_350K Tuya BLE lock (`product_id: z1dfsaya`), built on top of ShonP40/Tuya-BLE.

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
- Access-event diagnostics for fingerprint/PIN/failure events.
- Configurable 350K protocol logging under the integration Configure dialog (Off / Parsed events / Raw frames + events).
- Optional BLE connection keeper for low-latency controls through an ESPHome Bluetooth proxy.

Still experimental / not enabled as a normal HA lock control:

- Remote lock command via DP46=`true` (confirmed in live testing).
- Remote unlock via an experimental DP71 / `ble_unlock_check` V4 command. The framing is inferred from previous Smart Life captures and must still be physically validated on the 350K. The test button is disabled by default in the entity registry.

## Repository policy

The working integration belongs under `custom_components/tuya_local_ble/`.

Credentials and captures stay out of GitHub. Do **not** commit `devices.json`, local keys, secKeys, devKeys, account credentials, authenticated API responses, raw HCI snoop logs, APKs, or credential-bearing Home Assistant logs.

## 350K datapoints currently understood

| DP | Meaning / current interpretation |
|---:|---|
| 8 | Battery percentage |
| 12 | Successful fingerprint credential ID |
| 13 | Successful PIN credential ID |
| 20 | Lock event record (raw) |
| 21 | Failed credential/alarm event |
| 28 | Language |
| 31 | Beep volume |
| 32 | Secure/reverse-lock **reported state** |
| 33 | Passage / automatic-lock suppression control |
| 46 | Tuya `manual_lock`; `true` is confirmed to physically lock |
| 47 | Physical lock state (`true` unlocked, `false` locked) |
| 68 | Special function enum |
| 71 | BLE unlock/check raw command; experimental 19-byte unlock-check payload under test |
| 78 | Special control boolean; exact role unknown |
| 79 | Secure-lock control; confirmed, with DP32 as reported secure state |

## BLE proxy notes

The integration works best with an active ESPHome Bluetooth proxy and a stable API/Wi-Fi connection. The optional 350K connection keeper only keeps an already-open BLE session alive; it does not force a disconnected or unreachable lock to reconnect.

## Upstream

This project currently carries modifications to the `tuya_local_ble` integration from ShonP40/Tuya-BLE while the 350K-specific protocol work is still experimental.

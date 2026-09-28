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

## Untested / pending physical validation

The following features are implemented on `experiment/dp46-lock` but should still be treated as unverified until they are exercised on the physical lock. This checklist is intended to keep implemented code separate from behavior that has actually been confirmed.

- [ ] **Experimental HA lock entity** — verify `lock()` still actuates correctly through DP46 after the recent transport/diagnostic changes, and that HA state only follows authoritative DP47.
- [ ] **Remote unlock via DP71 / `ble_unlock_check`** — verify physical unlock, protocol ACK, DP47=`true`, and repeated cold/warm-session behavior.
- [ ] **BLE/app unlock event detection (DP19)** — confirm whether HA/DP71 unlocks and Smart Life unlocks produce DP19, and whether it arrives as an ordinary or timed V4 report.
- [ ] **Lock volume select (DP31)** — verify all exposed enum values (`Mute`, `Low`, `Normal`, `High`), audible behavior, and reported DP31 echo/state.
- [ ] **Lock language select (DP28)** — verify the currently exposed language enum values, voice prompts, and reported DP28 echo/state.
- [ ] **Native-size FD50 writes** — confirm the 350K uses single large GATT writes when the backend reports a usable write-without-response size (for example ~52-byte boolean-control frames and ~68-byte DP71 frames), and confirm fallback fragmentation still works.
- [ ] **Keep BLE connection alive option** — verify the integration-option setting persists across reload/restart and that the ~120-second idle keepalive maintains an already-authenticated session without forcing a sleeping lock to connect.
- [ ] **Transport diagnostics** — verify ACK latency, GATT write count, largest write size, and selected write chunk size update accurately for cold and warm commands.
- [ ] **Session diagnostics** — verify reconnect count, connected-since timestamp, last-disconnect timestamp, command result, total command duration, and ACK-to-DP47 actuation latency.
- [ ] **V4 sequence-gap detector** — verify normal monotonic progression, deliberate disconnect/reconnect behavior, wrap/reset handling, and that large discontinuities are not miscounted as thousands of missed events.
- [ ] **Unknown DP recorder** — verify safe scalar collection for BOOL/ENUM/VALUE, redaction for RAW/BITMAP/STRING, the 32-DP bound, and reset behavior after integration reload.
- [ ] **Sanitized event timeline** — verify ordering of ordinary/timed reports, the 25-entry bound, credential-ID redaction for DP12/13/19, and reset behavior after integration reload.
- [ ] **DP20 event/history correlation** — use the recorder/timeline to correlate manual lock, auto-lock, app lock, fingerprint/PIN unlock, HA lock, and eventual HA unlock without assigning byte semantics prematurely.
- [ ] **Cold-vs-warm latency comparison** — compare on-demand reconnect operations with an already-warm keepalive session to separate BLE/session setup time from protocol ACK and motor actuation time.

- [ ] **Test-marker service** — verify marker ordering relative to subsequent lock reports and multi-lock targeting.
- [ ] **Sanitized diagnostic export** — verify service response remains free of credential IDs/raw payloads while retaining enough metadata for offline comparison.
- [ ] **State freshness/session sensors** — verify Last device report, State age, BLE session state, and Last RX age across sleep/reconnect cycles.
- [ ] **Command counters** — verify success, timeout/not-acknowledged, BLE error, busy, and reconnect-required accounting.
- [ ] **Manual Refresh lock status** — verify it wakes/connects on demand, requests status once, and does not alter lock configuration.
- [ ] **Clear test diagnostics** — verify it clears only local experiment state and never changes physical lock settings.
- [ ] **HA event-bus events/device triggers** — verify each known access/lock transition fires once per physical event without leaking credential IDs.
- [ ] **Firmware/protocol diagnostic sensors** — verify values match the device-info handshake and persist through normal sleep cycles.

Already-confirmed controls should not be reclassified as untested: DP33 passage control, DP46 physical lock, DP79 secure-lock control, DP32 secure-lock reported state, and DP47 physical lock state have all been observed working in live testing.

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

## Session and command diagnostics

The experimental branch also provides disabled-by-default local diagnostic sensors for:

- BLE reconnect count (session-local; resets when the config entry reloads).
- BLE connected-since and last-disconnect timestamps.
- Last observed 40-bit V4 event sequence and cumulative small sequence gaps.
- Last high-level 350K command, command result, and total duration including on-demand reconnect time.
- ACK latency, GATT write count/size, negotiated write chunk size, and ACK-to-DP47 motor actuation latency.

Sequence gaps are intentionally conservative: small forward jumps are counted as potentially missed reports, while large discontinuities are treated as reboot/reset/reordering and logged without inflating the gap counter. Lock/unlock actuation latency starts after the protocol ACK and stops only when authoritative DP47 reaches the requested physical state.

## Sanitized unknown-DP recorder

A disabled-by-default diagnostic sensor named **Unknown DP recorder** records session-local metadata for 350K datapoints that are not yet positively interpreted by this project. It is intended for safe exploratory testing while exercising the lock later.

The sensor state is the number of distinct unknown DPs observed in the current Home Assistant integration session. Its attributes contain a bounded record for each DP with:

- DP number and observed Tuya type(s),
- payload length(s),
- total / ordinary / timed occurrence counts,
- first/last-seen epoch timestamps and last V4 event sequence,
- up to eight distinct scalar values for BOOL / ENUM / VALUE datapoints,
- a `payload_redacted` flag.

RAW, BITMAP, and STRING contents are **never retained by this recorder**; only their type, length, timing, and count metadata are kept. The recorder stores at most 32 distinct DPs and eight lengths/scalars per DP. Additional distinct DPs increment `overflow_count` rather than growing attributes indefinitely. Data resets when the integration reloads or Home Assistant restarts.

This recorder is independent of Raw protocol logging. For routine discovery, leave protocol logging at **Parsed events** (or Off) and enable only the **Unknown DP recorder** entity. Existing Raw logging can still contain decrypted protocol content and should continue to be treated as sensitive.

An example sanitized record may look like:

```yaml
state: 3
records:
  - dp: 6
    types: [DT_VALUE]
    lengths: [4]
    count: 2
    ordinary_count: 0
    timed_count: 2
    scalar_values: [1]
    payload_redacted: false
  - dp: 61
    types: [DT_RAW]
    lengths: [19]
    count: 1
    scalar_values: []
    payload_redacted: true
```


## Sanitized event timeline

A second disabled-by-default diagnostic sensor, **Sanitized event timeline**, keeps the most recent 25 decoded 350K V4 datapoint reports in order. This makes later correlation tests possible without requiring Raw protocol logging or a new HCI capture for every experiment.

Each entry stores only bounded metadata: timestamp, rolling 40-bit event sequence, event kind, DP number, Tuya type, payload length, whether it came from an ordinary or timed report, whether the DP is already interpreted, and a safe scalar when appropriate.

RAW, BITMAP, and STRING contents are never retained. Credential/user identifier scalar DPs 12, 13, and 19 are also redacted from this generic timeline even though dedicated access-event diagnostics may expose those IDs elsewhere. The buffer is session-only, resets on integration reload/Home Assistant restart, and never exceeds 25 entries.

For later testing, enable both **Unknown DP recorder** and **Sanitized event timeline**. The unknown-DP recorder summarizes recurring patterns; the timeline preserves ordering between events such as DP20, DP47, DP6, DP68, DP78, and newly discovered IDs.

## Test harness services and automation

The experimental branch includes a local-only test harness intended to make one physical test session useful without requiring raw authenticated captures.

### Test markers

Call `tuya_local_ble.mark_350k_test` immediately before a physical/app/HA action. `label` is required; `note` is optional. Both are user supplied, whitespace-normalized, and bounded. The marker does **not** send anything to the lock; it is inserted into the same sanitized event timeline as a `source: marker` record. Do not place secrets in marker labels or notes.

Example:

```yaml
action: tuya_local_ble.mark_350k_test
data:
  label: fingerprint_unlock
```

The sanitized timeline capacity is now 50 entries so a complete fingerprint/PIN/manual/HA test matrix is less likely to wrap.

### Sanitized diagnostic export

`tuya_local_ble.export_350k_diagnostics` is a response-producing service. It returns current firmware/protocol metadata, session freshness, reconnect/sequence diagnostics, command counters/timings, safe scalar state, unknown-DP summaries, and the sanitized timeline. It intentionally omits local keys, secKeys, `ble_unlock_check`, credential IDs, and raw/string/bitmap payload contents.

When exactly one 350K is loaded, the target fields can be omitted. With multiple locks, specify `device_id` or `config_entry_id`.

### Local diagnostic buttons

Two disabled-by-default diagnostic buttons are available:

- **Refresh lock status** — explicitly connects/authenticates and requests `DEVICE_STATUS` once. It is user initiated; unlike Keep BLE connection alive it does not run continuously.
- **Clear test diagnostics** — clears the unknown-DP summary, sanitized timeline, sequence-gap count, command counters, and recent command/transport measurements without changing any physical lock configuration.

### Freshness / session / command diagnostics

Disabled-by-default sensors now include **Last device report**, **State age**, **BLE session state**, **Last BLE RX age**, and **Command counters**. State/RX ages are local freshness measurements; the lock's retained DP47 state is still authoritative for the last reported physical state.

Command counters are session-local and include total attempts, successful ACKs, not-acknowledged/timeouts, BLE errors, not-connected failures, busy/rejected attempts, unavailable commands, generic errors, and commands that required establishing a session first.

### Home Assistant events and device triggers

Known parser events are emitted on the local HA event bus as `tuya_local_ble_350k_event` without credential IDs. Experimental device triggers are available for fingerprint unlock, PIN unlock, Bluetooth unlock, failed fingerprint, failed PIN, locked, and unlocked. These triggers should remain considered experimental until the corresponding physical test checklist is completed.

### Firmware / protocol metadata

Disabled-by-default diagnostic sensors expose device firmware, hardware, and Tuya protocol versions so captures from different 350K firmware revisions can be compared without inspecting raw traffic.

### Protocol regression tests

`tests/test_350k_protocol.py` covers the confirmed DP46 V4 payload, DP28/31 enum framing, non-secret DP71 framing shape, 40-bit sequence wrap/gaps, negotiated GATT write-size selection, timeline redaction/bounds, and marker sanitization. The test module imports only pure helpers and does not require access to the physical lock or private credentials.

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
# HA BLE Ironzon 350K

Experimental Home Assistant support for the Ironzon/YD_350K Tuya BLE lock (`product_id: z1dfsaya`), built on top of ShonP40/Tuya-BLE.

> [!WARNING]
> This is reverse-engineered, device-specific code. Keep a working physical/keypad/fingerprint entry method available while testing remote controls. Do not expose raw protocol logs publicly; they can contain credential IDs and other lock event data.

## Current status

### Confirmed on the physical 350K

- TuyaOS FD50 BLE transport.
- `0x0e` login key derivation from the full `localKey + secKey`.
- `0x0f` session key derivation from `localKey + secKey + srand`.
- Tuya V4 ordinary and timed datapoint parsing.
- Battery reporting via DP8.
- Physical lock-state reporting via DP47 (`true` = unlocked, `false` = locked).
- Passage/automatic-lock suppression control via DP33.
- Secure-lock reported state via DP32.
- Secure-lock control via DP79.
- Remote physical lock via DP46=`true`.
- Fingerprint/PIN/failure access-event diagnostics for the event types already observed.

DP47 remains the authoritative physical lock state. Command acknowledgements and access events are not treated as proof that the motor reached a requested state.

### Implemented / awaiting validation

The following are implemented on `experiment/dp46-lock` but should not yet be described as physically confirmed behavior:

- Remote unlock through DP71 / `ble_unlock_check`.
- BLE/app unlock event interpretation through DP19.
- Lock volume select through DP31.
- Lock language select through DP28.
- Experimental Home Assistant `lock` entity using DP47 for state, DP46 for Lock, and DP71 for Unlock.
- Native-size FD50 writes when the backend reports a larger write-without-response size.
- Configurable BLE connection keeper.
- Transport/session/freshness diagnostics.
- V4 sequence-gap diagnostics.
- Unknown-DP recorder and sanitized event timeline.
- Test-marker and sanitized diagnostic-export services.
- Native Home Assistant **Download diagnostics** support using the same sanitized snapshot.
- Home Assistant event-bus events and device triggers.
- Firmware/hardware/protocol diagnostic sensors.

The experimental HA lock entity is disabled by default because Unlock still uses the unconfirmed DP71 path.

### Unknown / incomplete

- Exact byte semantics of DP20 lock-history/event records.
- Exact purpose of DP68 beyond the currently observed enum behavior.
- Exact purpose of DP78.
- Whether every firmware/app unlock path consistently produces DP19.
- Whether PIN unlock has the same passage-mode-clearing behavior observed with fingerprint unlock.

## Experimental branch

Current active test work lives on:

```text
experiment/dp46-lock
```

The intent is to test and clean this branch before integrating the confirmed work back into `main`.

To install the branch manually from the Home Assistant bash shell:

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

## Physical-validation checklist

- [ ] **Experimental HA lock entity** — verify `lock()` still actuates correctly through DP46 after the transport/diagnostic changes and that HA state follows only DP47.
- [ ] **Remote unlock via DP71 / `ble_unlock_check`** — verify physical unlock, ACK, DP47=`true`, and repeated cold/warm-session behavior.
- [ ] **BLE/app unlock event detection (DP19)** — determine which Smart Life and HA unlock paths produce it and whether reports are ordinary or timed V4 events.
- [ ] **Lock volume (DP31)** — verify `Mute`, `Low`, `Normal`, and `High`, including reported DP31 state.
- [ ] **Lock language (DP28)** — verify the exposed language values, prompts, and reported DP28 state.
- [ ] **Native-size FD50 writes** — verify single larger GATT writes when available and fallback fragmentation when unavailable.
- [ ] **Keep BLE connection alive** — verify persistence across reload/restart and idle-session behavior.
- [ ] **Transport diagnostics** — verify ACK latency, GATT write count, largest write, and selected chunk size.
- [ ] **Session diagnostics** — verify reconnect count, connection timestamps, command result/duration, and ACK-to-DP47 actuation latency.
- [ ] **V4 sequence-gap detector** — verify normal progression, reconnect/reset behavior, wrap handling, and discontinuity filtering.
- [ ] **Unknown DP recorder** — verify safe scalar collection, RAW/BITMAP/STRING redaction, bounds, and reset behavior.
- [ ] **Sanitized event timeline** — verify ordering, the **50-entry** bound, DP12/13/19 credential-value redaction, marker ordering, and reset behavior.
- [ ] **DP20 correlation** — correlate manual lock, auto-lock, app lock, fingerprint/PIN unlock, HA lock, and eventual HA unlock without assigning byte meanings prematurely.
- [ ] **Test-marker service** — verify marker ordering and multi-lock targeting.
- [ ] **Sanitized diagnostic export** — verify both the service response and native HA Download diagnostics remain free of credentials/raw payloads while retaining useful metadata.
- [ ] **State freshness/session sensors** — verify Last device report, State age, BLE session state, and Last RX age.
- [ ] **Command counters** — verify success, timeout/not-acknowledged, BLE error, busy/rejected, unavailable, and reconnect-required accounting.
- [ ] **Manual Refresh lock status** — verify it connects/authenticates, requests status once, and does not change lock configuration.
- [ ] **Clear test diagnostics** — verify it clears only local experiment state.
- [ ] **HA event-bus events/device triggers** — verify one event per physical action without leaking credential IDs.
- [ ] **Firmware/protocol diagnostic sensors** — verify values against the device-info handshake.

Already-confirmed DP33, DP46, DP47, DP32, and DP79 behavior should not be moved back into the unverified list unless later testing contradicts the observations.

## Experimental entities and options

### Integration options

Open **Settings → Devices & services → Tuya BLE → Configure**.

- **Keep BLE connection alive** — periodically keeps an already-authenticated 350K BLE session warm. It does not deliberately wake a disconnected/sleeping lock.
- **350K protocol logging**
  - `Off` — normal integration logging only.
  - `Parsed events` — decoded datapoints, timed events, acknowledgements, and useful protocol timing.
  - `Raw frames + events` — also logs encrypted BLE fragments and decrypted Tuya V4 payloads. Use only for short troubleshooting sessions because raw output may contain sensitive lock-event data.

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

Volume and language are exposed as normal entities because their schema is implemented, but their physical behavior remains in the validation checklist above.

### Disabled-by-default experimental/diagnostic entities

Enable these from the device's entity list only while testing:

- **350K lock (experimental)**
- **Last lock record (raw diagnostic)**
- **Last TX ACK latency**
- **Last GATT write count**
- **Largest last GATT write**
- **GATT write chunk size**
- Session/command/freshness sensors
- Unknown DP recorder
- Sanitized event timeline
- Firmware/hardware/protocol version sensors

The experimental lock entity does not optimistically change DP47.

### Raw DP20 diagnostic warning

**Last lock record (raw diagnostic)** intentionally retains the exact plaintext DP20 value for reverse engineering. It is disabled by default and should be treated as sensitive diagnostic data.

It is **not** the same thing as the sanitized unknown-DP recorder, sanitized event timeline, `export_350k_diagnostics` service, or native Home Assistant diagnostics. Those sanitized facilities deliberately omit raw/string/bitmap contents and credential scalar values where applicable.

## Sanitized unknown-DP recorder

The disabled-by-default **Unknown DP recorder** stores session-local metadata for datapoints that are not yet positively interpreted.

It retains only bounded information such as:

- DP number and Tuya type(s),
- payload length(s),
- ordinary/timed occurrence counts,
- first/last-seen time and last V4 event sequence,
- up to eight distinct safe scalar values for BOOL / ENUM / VALUE datapoints,
- a `payload_redacted` flag.

RAW, BITMAP, and STRING contents are never retained by this recorder. It stores at most 32 distinct DPs and eight lengths/scalars per DP. Extra distinct DPs increment an overflow counter instead of growing attributes without bound.

## Sanitized event timeline

The disabled-by-default **Sanitized event timeline** keeps the most recent **50** decoded 350K V4 reports/markers in order.

Each entry contains bounded metadata: timestamp, 40-bit event sequence, source/kind, DP number, Tuya type, payload length, ordinary/timed classification, whether the DP is interpreted, and a safe scalar where appropriate.

RAW, BITMAP, and STRING contents are never retained. Credential/user scalar DPs 12, 13, and 19 are redacted from the generic timeline. The timeline is session-only and resets when the integration reloads or Home Assistant restarts.

## Diagnostics

Home Assistant's native **Download diagnostics** action is supported for each config entry. For the 350K it includes product/firmware/protocol metadata plus the existing sanitized runtime snapshot.

Native diagnostics and the legacy `tuya_local_ble.export_350k_diagnostics` service intentionally omit local keys, secKeys, `ble_unlock_check`, credential IDs, and raw/string/bitmap payload contents. The service is retained for the reverse-engineering/test harness, while the native HA action is the preferred general-purpose diagnostic export.

## Test harness services

### Test markers

Call `tuya_local_ble.mark_350k_test` immediately before a physical/app/HA action. `label` is required and `note` is optional. Both are whitespace-normalized and bounded.

The marker does not send anything to the lock; it is inserted into the same 50-entry sanitized event timeline.

Example:

```yaml
action: tuya_local_ble.mark_350k_test
data:
  label: fingerprint_unlock
```

Do not put secrets in marker labels or notes.

### Sanitized diagnostic export

`tuya_local_ble.export_350k_diagnostics` returns current firmware/protocol metadata, state/session freshness, reconnect/sequence diagnostics, command counters/timings, safe scalar state, unknown-DP summaries, and the sanitized timeline.

It intentionally omits local keys, secKeys, `ble_unlock_check`, credential IDs, and raw/string/bitmap payload contents.

### Local diagnostic buttons

Two disabled-by-default diagnostic buttons are available:

- **Refresh lock status** — connects/authenticates and requests `DEVICE_STATUS` once.
- **Clear test diagnostics** — clears local experiment state such as the unknown-DP summary, timeline, sequence-gap count, command counters, and recent transport measurements without changing physical lock configuration.

## Protocol regression tests and CI

`tests/test_350k_protocol.py` covers pure protocol/diagnostic helpers including:

- confirmed DP46 V4 payload framing,
- DP28/DP31 enum framing,
- non-secret DP71 framing shape,
- 40-bit sequence wrap/gap handling,
- negotiated write-size selection,
- timeline redaction/bounds,
- marker sanitization.

`tests/test_crypto_compat.py` pins the AES-CBC behavior used by the Tuya transport to a fixed known-answer vector. The integration currently pins `pycryptodome==3.23.0`.

CI runs on pushes to `main` and `experiment/**`, pull requests, and manual dispatches:

- Python 3.14 compile and unit/protocol regression tests,
- Home Assistant Hassfest validation,
- conservative Ruff `F` correctness checks for undefined names, duplicate definitions/keys, unused imports, and related Python errors.

The tests require no physical lock and no private credentials.

## 350K datapoints currently understood

| DP | Meaning / current interpretation |
|---:|---|
| 8 | Battery percentage |
| 12 | Successful fingerprint credential ID |
| 13 | Successful PIN credential ID |
| 19 | BLE/app unlock event / credential value when reported; interpretation awaiting fuller validation |
| 20 | Raw lock event/history record; exact byte semantics incomplete |
| 21 | Failed credential/alarm event |
| 28 | Language enum; implementation awaiting physical validation |
| 31 | Beep volume enum; implementation awaiting physical validation |
| 32 | Secure/reverse-lock **reported state**, confirmed |
| 33 | Passage / automatic-lock suppression control, confirmed |
| 46 | Tuya `manual_lock`; `true` physically locks, confirmed |
| 47 | Physical lock state (`true` unlocked, `false` locked), confirmed |
| 68 | Special function enum; exact role incomplete |
| 71 | BLE unlock/check raw command; experimental unlock path |
| 78 | Special control boolean; exact role unknown |
| 79 | Secure-lock control, physically confirmed |

## Passage-mode observation

A successful **fingerprint** operation has been observed clearing passage mode and restoring normal auto-lock behavior. PIN should not be claimed to do the same until that behavior is independently reproduced.

## BLE proxy notes

The integration works best with an active ESPHome Bluetooth proxy and a stable API/Wi-Fi connection. The optional connection keeper only keeps an already-open session alive; it does not force a disconnected/unreachable lock to reconnect.

An earlier test setup showed long command delays and poor reliability. That behavior was traced to a bad ESP proxy. After replacing the ESP, the lock became reliably responsive. Those old delays should not be treated as evidence for a required 20–40 second protocol/session cooldown.

For latency comparisons, proxy Wi-Fi/API stability is therefore an important variable alongside BLE signal quality and session state.

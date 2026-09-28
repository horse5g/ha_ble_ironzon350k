from pathlib import Path
import json

root = Path("custom_components/tuya_local_ble")

# const.py
p = root / "const.py"
s = p.read_text()
needle = "DP_350K_UNKNOWN_DP_COUNT: Final = -3518\n"
if "DP_350K_EVENT_TIMELINE_COUNT" not in s:
    assert needle in s
    s = s.replace(
        needle,
        needle + "DP_350K_EVENT_TIMELINE_COUNT: Final = -3519\n",
        1,
    )
p.write_text(s)

# tuya_ble.py
p = root / "tuya_ble" / "tuya_ble.py"
s = p.read_text()

needle = "    DP_350K_UNKNOWN_DP_COUNT,\n    PROTOCOL_LOG_EVENTS,\n"
if "    DP_350K_EVENT_TIMELINE_COUNT," not in s:
    assert needle in s
    s = s.replace(
        needle,
        "    DP_350K_UNKNOWN_DP_COUNT,\n"
        "    DP_350K_EVENT_TIMELINE_COUNT,\n"
        "    PROTOCOL_LOG_EVENTS,\n",
        1,
    )

marker = "_350K_INTERPRETED_DPS = frozenset({\n    8,   # battery\n"
if "_350K_EVENT_TIMELINE_CAPACITY" not in s:
    assert marker in s
    s = s.replace(
        marker,
        "_350K_EVENT_TIMELINE_CAPACITY = 25\n"
        "# Credential/user identifiers are useful elsewhere in dedicated diagnostics,\n"
        "# but the generic timeline deliberately redacts them so it is safer to share.\n"
        "_350K_TIMELINE_SENSITIVE_SCALAR_DPS = frozenset({12, 13, 19})\n\n"
        "_350K_INTERPRETED_DPS = frozenset({\n"
        "    8,   # battery\n",
        1,
    )

needle = (
    "        self._350k_unknown_dps: dict[int, dict[str, object]] = {}\n"
    "        self._350k_unknown_dp_overflow = 0\n"
    "        # Session-local diagnostics. These intentionally reset when the HA\n"
)
if "self._350k_event_timeline" not in s:
    assert needle in s
    s = s.replace(
        needle,
        "        self._350k_unknown_dps: dict[int, dict[str, object]] = {}\n"
        "        self._350k_unknown_dp_overflow = 0\n"
        "        # Bounded, session-local ordering of decoded 350K reports. The timeline\n"
        "        # never keeps raw/string/bitmap payload contents or credential IDs.\n"
        "        self._350k_event_timeline: list[dict[str, object]] = []\n"
        "        # Session-local diagnostics. These intentionally reset when the HA\n",
        1,
    )

needle = (
    "                self._datapoints._update_from_device(\n"
    "                    DP_350K_UNKNOWN_DP_COUNT,\n"
    "                    time.time(),\n"
    "                    0,\n"
    "                    TuyaBLEDataPointType.DT_VALUE,\n"
    "                    0,\n"
    "                )\n"
    "            self._decode_advertisement_data()\n"
)
if "DP_350K_EVENT_TIMELINE_COUNT,\n                    now," not in s:
    assert needle in s
    replacement = (
        "                now = time.time()\n"
        "                self._datapoints._update_from_device(\n"
        "                    DP_350K_UNKNOWN_DP_COUNT,\n"
        "                    now,\n"
        "                    0,\n"
        "                    TuyaBLEDataPointType.DT_VALUE,\n"
        "                    0,\n"
        "                )\n"
        "                self._datapoints._update_from_device(\n"
        "                    DP_350K_EVENT_TIMELINE_COUNT,\n"
        "                    now,\n"
        "                    0,\n"
        "                    TuyaBLEDataPointType.DT_VALUE,\n"
        "                    0,\n"
        "                )\n"
        "            self._decode_advertisement_data()\n"
    )
    s = s.replace(needle, replacement, 1)

anchor = "    def _record_350k_unknown_dp(\n        self,\n        dp_id: int,\n"
if "def _record_350k_event_timeline(" not in s:
    assert anchor in s
    insert = '''    @property
    def event_timeline_diagnostics(self) -> dict[str, object]:
        """Return a JSON-safe snapshot of the recent sanitized 350K timeline."""
        return {
            "count": len(self._350k_event_timeline),
            "capacity": _350K_EVENT_TIMELINE_CAPACITY,
            "session_only": True,
            "raw_string_bitmap_contents_stored": False,
            "credential_scalar_dps_redacted": sorted(
                _350K_TIMELINE_SENSITIVE_SCALAR_DPS
            ),
            "events": [dict(event) for event in self._350k_event_timeline],
        }

    def _record_350k_event_timeline(
        self,
        dp_id: int,
        dp_type: TuyaBLEDataPointType,
        raw_value: bytes,
        value: bytes | bool | int | str,
        *,
        timed: bool,
        timestamp: int | float,
        event_seq: int,
        kind: int,
    ) -> TuyaBLEDataPoint | None:
        """Record one decoded 350K event without retaining sensitive payloads."""
        if self.product_id != "z1dfsaya":
            return None

        payload_redacted = False
        scalar: bool | int | None = None
        if dp_type == TuyaBLEDataPointType.DT_BOOL:
            scalar = bool(value)
        elif dp_type in (TuyaBLEDataPointType.DT_ENUM, TuyaBLEDataPointType.DT_VALUE):
            if dp_id in _350K_TIMELINE_SENSITIVE_SCALAR_DPS:
                payload_redacted = True
            else:
                scalar = int(value)
        else:
            payload_redacted = True

        entry: dict[str, object] = {
            "timestamp": int(timestamp),
            "sequence": int(event_seq),
            "kind": int(kind),
            "dp": int(dp_id),
            "type": dp_type.name,
            "length": len(raw_value),
            "source": "timed" if timed else "ordinary",
            "interpreted": dp_id in _350K_INTERPRETED_DPS,
            "payload_redacted": payload_redacted,
        }
        if scalar is not None:
            entry["scalar"] = scalar

        self._350k_event_timeline.append(entry)
        if len(self._350k_event_timeline) > _350K_EVENT_TIMELINE_CAPACITY:
            del self._350k_event_timeline[
                : len(self._350k_event_timeline) - _350K_EVENT_TIMELINE_CAPACITY
            ]

        self._datapoints._update_from_device(
            DP_350K_EVENT_TIMELINE_COUNT,
            time.time(),
            0,
            TuyaBLEDataPointType.DT_VALUE,
            len(self._350k_event_timeline),
        )
        return self._datapoints[DP_350K_EVENT_TIMELINE_COUNT]

'''
    s = s.replace(anchor, insert + anchor, 1)

needle = '''            unknown_summary_dp = self._record_350k_unknown_dp(
                dp_id,
                dp_type,
                raw_value,
                value,
                timed=True,
                timestamp=timestamp,
                event_seq=event_seq,
            )
'''
if "timed=True,\n                timestamp=timestamp,\n                event_seq=event_seq,\n                kind=kind," not in s:
    assert needle in s
    replacement = '''            timeline_dp = self._record_350k_event_timeline(
                dp_id,
                dp_type,
                raw_value,
                value,
                timed=True,
                timestamp=timestamp,
                event_seq=event_seq,
                kind=kind,
            )
            if timeline_dp is not None:
                datapoints.append(timeline_dp)

''' + needle
    s = s.replace(needle, replacement, 1)

needle = '''        unknown_summary_dp = self._record_350k_unknown_dp(
            dp_id,
            dp_type,
            raw_value,
            value,
            timed=False,
            timestamp=time.time(),
            event_seq=event_seq,
        )
'''
if "timed=False,\n            timestamp=event_timestamp,\n            event_seq=event_seq,\n            kind=kind," not in s:
    assert needle in s
    replacement = '''        event_timestamp = time.time()
        timeline_dp = self._record_350k_event_timeline(
            dp_id,
            dp_type,
            raw_value,
            value,
            timed=False,
            timestamp=event_timestamp,
            event_seq=event_seq,
            kind=kind,
        )
        if timeline_dp is not None:
            datapoints.append(timeline_dp)

        unknown_summary_dp = self._record_350k_unknown_dp(
            dp_id,
            dp_type,
            raw_value,
            value,
            timed=False,
            timestamp=event_timestamp,
            event_seq=event_seq,
        )
'''
    s = s.replace(needle, replacement, 1)

p.write_text(s)

# sensor.py
p = root / "sensor.py"
s = p.read_text()
needle = "    DP_350K_UNKNOWN_DP_COUNT,\n)\n"
if "    DP_350K_EVENT_TIMELINE_COUNT," not in s:
    assert needle in s
    s = s.replace(
        needle,
        "    DP_350K_UNKNOWN_DP_COUNT,\n    DP_350K_EVENT_TIMELINE_COUNT,\n)\n",
        1,
    )

anchor = "\n\n@dataclass\nclass TuyaBLECategorySensorMapping:\n"
if "def event_timeline_getter(" not in s:
    assert anchor in s
    insert = '''

def event_timeline_getter(self: TuyaBLESensor) -> None:
    """Expose the bounded sanitized 350K event timeline."""
    snapshot = self._device.event_timeline_diagnostics
    self._attr_native_value = int(snapshot["count"])
    self._attr_extra_state_attributes = {
        "capacity": snapshot["capacity"],
        "session_only": snapshot["session_only"],
        "raw_string_bitmap_contents_stored": snapshot[
            "raw_string_bitmap_contents_stored"
        ],
        "credential_scalar_dps_redacted": snapshot[
            "credential_scalar_dps_redacted"
        ],
        "events": snapshot["events"],
    }
'''
    s = s.replace(anchor, insert + anchor, 1)

needle = '''                TuyaBLESensorMapping(
                    dp_id=DP_350K_UNKNOWN_DP_COUNT,
                    getter=unknown_dp_recorder_getter,
                    description=SensorEntityDescription(
                        key="unknown_dp_recorder",
                        icon="mdi:radar",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        entity_registry_enabled_default=False,
                    ),
                ),
'''
if 'key="event_timeline_recorder"' not in s:
    assert needle in s
    addition = '''                TuyaBLESensorMapping(
                    dp_id=DP_350K_EVENT_TIMELINE_COUNT,
                    getter=event_timeline_getter,
                    description=SensorEntityDescription(
                        key="event_timeline_recorder",
                        icon="mdi:timeline-clock-outline",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        entity_registry_enabled_default=False,
                    ),
                ),
'''
    s = s.replace(needle, needle + addition, 1)
p.write_text(s)

# strings / translation JSON
for rel in ("strings.json", "translations/en.json"):
    p = root / rel
    data = json.loads(p.read_text())
    data["entity"]["sensor"]["event_timeline_recorder"] = {
        "name": "Sanitized event timeline"
    }
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")

# README
p = Path("README.md")
s = p.read_text()
if "## Sanitized event timeline" not in s:
    needle = "\n## Suggested test sequence\n"
    assert needle in s
    section = """
## Sanitized event timeline

A second disabled-by-default diagnostic sensor, **Sanitized event timeline**, keeps the most recent 25 decoded 350K V4 datapoint reports in order. This makes later correlation tests possible without requiring Raw protocol logging or a new HCI capture for every experiment.

Each entry stores only bounded metadata: timestamp, rolling 40-bit event sequence, event kind, DP number, Tuya type, payload length, whether it came from an ordinary or timed report, whether the DP is already interpreted, and a safe scalar when appropriate.

RAW, BITMAP, and STRING contents are never retained. Credential/user identifier scalar DPs 12, 13, and 19 are also redacted from this generic timeline even though dedicated access-event diagnostics may expose those IDs elsewhere. The buffer is session-only, resets on integration reload/Home Assistant restart, and never exceeds 25 entries.

For later testing, enable both **Unknown DP recorder** and **Sanitized event timeline**. The unknown-DP recorder summarizes recurring patterns; the timeline preserves ordering between events such as DP20, DP47, DP6, DP68, DP78, and newly discovered IDs.
"""
    s = s.replace(needle, "\n" + section + needle, 1)
p.write_text(s)

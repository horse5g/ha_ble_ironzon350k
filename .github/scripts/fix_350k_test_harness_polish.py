from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected 1 match, found {count}")
    return text.replace(old, new, 1)


p = Path("custom_components/tuya_local_ble/button.py")
s = p.read_text(encoding="utf-8")
old = '''    @property
    def available(self) -> bool:
        """Return if entity is available."""
        result = super().available
'''
new = '''    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if (
            self._device.product_id == "z1dfsaya"
            and self._mapping.dp_id in (-9001, -9002)
        ):
            # Refresh must be callable specifically when the lock is asleep;
            # Clear diagnostics is entirely local and never needs BLE.
            return True
        result = super().available
'''
if "self._mapping.dp_id in (-9001, -9002)" not in s:
    s = replace_once(s, old, new, "button availability")
p.write_text(s, encoding="utf-8")

p = Path("custom_components/tuya_local_ble/sensor.py")
s = p.read_text(encoding="utf-8")
old = '''        return self._mapping.dp_id in (
            DP_350K_STATE_AGE_SECONDS,
            DP_350K_LAST_RX_AGE_SECONDS,
        )
'''
new = '''        return self._mapping.dp_id in (
            DP_350K_STATE_AGE_SECONDS,
            DP_350K_LAST_RX_AGE_SECONDS,
            DP_350K_SESSION_STATE,
        )
'''
section = s[s.find("    def should_poll"):s.find("    async def async_update")]
if "DP_350K_SESSION_STATE" not in section:
    s = replace_once(s, old, new, "session-state polling")
p.write_text(s, encoding="utf-8")

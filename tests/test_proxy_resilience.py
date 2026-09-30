from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import unittest

PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "tuya_local_ble"
    / "tuya_ble"
    / "resilience.py"
)
spec = importlib.util.spec_from_file_location("tuya_ble_resilience", PATH)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


class TestProxyResilience(unittest.IsolatedAsyncioTestCase):
    async def test_disconnect_aborts_pending_response_waiters(self) -> None:
        loop = asyncio.get_running_loop()
        first = loop.create_future()
        second = loop.create_future()
        pending = {1: first, 2: second, 3: None}

        self.assertEqual(module.abort_pending_response_futures(pending), 2)
        self.assertEqual(pending, {})

        with self.assertRaisesRegex(OSError, "BLE transport disconnected"):
            await first
        with self.assertRaisesRegex(OSError, "BLE transport disconnected"):
            await second

    async def test_disconnect_does_not_overwrite_completed_future(self) -> None:
        loop = asyncio.get_running_loop()
        completed = loop.create_future()
        completed.set_result(0)
        pending = {7: completed}

        self.assertEqual(module.abort_pending_response_futures(pending), 0)
        self.assertEqual(pending, {})
        self.assertEqual(await completed, 0)

    async def test_control_is_rejected_while_reconnect_is_in_progress(self) -> None:
        self.assertTrue(
            module.should_reject_control_during_reconnect(
                connect_in_progress=True,
                session_authenticated=False,
            )
        )

    async def test_disconnected_control_can_start_its_own_connection(self) -> None:
        self.assertFalse(
            module.should_reject_control_during_reconnect(
                connect_in_progress=False,
                session_authenticated=False,
            )
        )

    async def test_authenticated_control_is_not_rejected(self) -> None:
        self.assertFalse(
            module.should_reject_control_during_reconnect(
                connect_in_progress=True,
                session_authenticated=True,
            )
        )


if __name__ == "__main__":
    unittest.main()

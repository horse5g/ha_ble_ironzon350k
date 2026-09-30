"""BLE transport hardening for flaky Home Assistant Bluetooth proxies."""
from __future__ import annotations

import logging
import time
from collections.abc import Callable

from .const import PRODUCT_ID_350K
from .tuya_ble.const import TuyaBLECode
from .tuya_ble.diagnostics_350k import valid_dp71_payload_shape
from .tuya_ble.exceptions import TuyaBLEDeviceError
from .tuya_ble.resilience import (
    abort_pending_response_futures,
    should_reject_control_during_reconnect,
)
from .tuya_ble.tuya_ble import BLEAK_EXCEPTIONS, TuyaBLEDevice

_LOGGER = logging.getLogger(__name__)


class ResilientTuyaBLEDevice(TuyaBLEDevice):
    """Tuya BLE device with defensive proxy-disconnect handling.

    ESPHome proxies can disappear while a Tuya request is waiting for its ACK.
    The upstream protocol wait is intentionally generous, so without an early
    abort the 350K control lock can remain occupied long after the transport is
    already gone. This wrapper keeps the wire protocol unchanged while making
    transport teardown fail fast and best-effort.
    """

    def _abort_transport_waiters(self) -> int:
        """Discard partial RX state and wake requests waiting on a dead link."""
        aborted = abort_pending_response_futures(self._input_expected_responses)
        self._clean_input()

        if self.product_id == PRODUCT_ID_350K:
            # Any latency correlation crossing a broken BLE session would be
            # misleading. Authoritative DP47 state is still retained normally.
            self._350k_unlock_requested_monotonic = None
            self._350k_actuation_started_monotonic = None
            self._350k_actuation_expected_state = None
            self._350k_actuation_command = None

        return aborted

    def _fire_disconnected_callbacks(self) -> None:
        """Release pending protocol waits before publishing disconnect."""
        aborted = self._abort_transport_waiters()
        if aborted:
            _LOGGER.debug(
                "%s: aborted %s pending Tuya response waiter(s) after BLE disconnect",
                self.address,
                aborted,
            )
        super()._fire_disconnected_callbacks()

    def _350k_reconnect_in_progress(self) -> bool:
        """Return whether a 350K control would wait behind authentication."""
        return self.product_id == PRODUCT_ID_350K and should_reject_control_during_reconnect(
            self._connect_lock.locked(),
            self.session_state == "authenticated",
        )

    def _start_resilient_350k_command(self) -> float:
        """Start one command without treating on-demand connect as a failure."""
        self._350k_command_counters["total"] += 1
        self._publish_350k_command_counters()
        return time.monotonic()

    def _record_350k_reconnect_required(self, command: str) -> None:
        """Record a control rejected because another task owns reconnect."""
        started = self._start_resilient_350k_command()
        self._finish_350k_command(command, "reconnect_required", started)
        _LOGGER.warning(
            "%s: Ignoring 350K %s while BLE reconnect/authentication is in progress; retry after reconnect",
            self.address,
            command,
        )

    async def _run_resilient_350k_control(
        self,
        command: str,
        payload_factory: Callable[[], bytes],
        *,
        code: TuyaBLECode = TuyaBLECode.FUN_SENDER_DPS_V4,
        detail: str,
        payload_unavailable: bool = False,
        expected_unlocked: bool | None = None,
        unlock_request: bool = False,
    ) -> bool:
        """Run one 350K control without queueing it behind a reconnect.

        A control is still allowed to establish an on-demand connection when no
        other connection attempt exists. If the reconnect/authentication lock is
        already owned by another task, however, executing the old command after
        that potentially long wait is surprising and unsafe. Reject it quickly
        and let the user retry against the fresh authenticated session.
        """
        if self._350k_control_lock.locked():
            self._record_350k_busy(command)
            _LOGGER.warning(
                "%s: Ignoring 350K %s; another control operation is still pending",
                self.address,
                detail,
            )
            return False

        if self._350k_reconnect_in_progress():
            self._record_350k_reconnect_required(command)
            return False

        started = self._start_resilient_350k_command()
        async with self._350k_control_lock:
            # Close the small race between the initial fail-fast check and
            # acquiring the control lock.
            if self._350k_reconnect_in_progress():
                self._finish_350k_command(command, "reconnect_required", started)
                _LOGGER.warning(
                    "%s: Cancelling 350K %s because BLE reconnect/authentication started before transmit",
                    self.address,
                    detail,
                )
                return False

            try:
                payload = payload_factory()
            except Exception as ex:
                result = "unavailable" if payload_unavailable else "error"
                self._finish_350k_command(command, result, started)
                if payload_unavailable:
                    _LOGGER.warning(
                        "%s: 350K %s unavailable: %s",
                        self.address,
                        detail,
                        ex,
                    )
                else:
                    _LOGGER.exception(
                        "%s: Failed to build 350K %s payload",
                        self.address,
                        detail,
                    )
                return False

            try:
                await self._ensure_connected()
                if (
                    self._expected_disconnect
                    or self._client is None
                    or not self._client.is_connected
                    or not self._is_paired
                ):
                    self._finish_350k_command(command, "not_connected", started)
                    return False

                _LOGGER.debug(
                    "%s: Sending 350K %s",
                    self.address,
                    detail,
                )
                self._log_350k_raw(
                    "%s: 350K raw %s plaintext: %s",
                    self.address,
                    code.name,
                    payload.hex(),
                )
                result = await self._send_packet_while_connected(
                    code,
                    payload,
                    0,
                    True,
                )
                if not result:
                    self._finish_350k_command(command, "not_acknowledged", started)
                    return False

                self._finish_350k_command(command, "acknowledged", started)
                if unlock_request:
                    self._350k_unlock_requested_monotonic = time.monotonic()
                if expected_unlocked is not None:
                    self._arm_350k_actuation(
                        command,
                        expected_unlocked=expected_unlocked,
                    )
                return True
            except BLEAK_EXCEPTIONS as ex:
                if unlock_request:
                    self._350k_unlock_requested_monotonic = None
                self._finish_350k_command(command, "ble_error", started)
                _LOGGER.warning(
                    "%s: 350K %s failed because BLE transport disconnected: %s",
                    self.address,
                    detail,
                    ex,
                )
                return False
            except Exception:
                if unlock_request:
                    self._350k_unlock_requested_monotonic = None
                self._finish_350k_command(command, "error", started)
                _LOGGER.exception(
                    "%s: Unexpected error sending 350K %s",
                    self.address,
                    detail,
                )
                return False

    async def set_350k_bool_datapoint(self, dp_id: int, value: bool) -> bool:
        """Write a 350K boolean control with resilient reconnect semantics."""
        if self.product_id != PRODUCT_ID_350K or dp_id not in (33, 46, 79):
            raise TuyaBLEDeviceError(0)
        command = {
            33: "passage_on" if value else "passage_off",
            46: "lock" if value else "manual_lock_false",
            79: "secure_on" if value else "secure_off",
        }[dp_id]
        return await self._run_resilient_350k_control(
            command,
            lambda: self._build_350k_v4_bool_data(dp_id, value),
            detail=f"DP{dp_id}={value}",
            expected_unlocked=(False if dp_id == 46 and value else None),
        )

    async def set_350k_enum_datapoint(self, dp_id: int, value: int) -> bool:
        """Write 350K language/volume with resilient reconnect semantics."""
        if self.product_id != PRODUCT_ID_350K or dp_id not in (28, 31):
            raise TuyaBLEDeviceError(0)
        command = "language" if dp_id == 28 else "volume"
        return await self._run_resilient_350k_control(
            command,
            lambda: self._build_350k_v4_enum_data(dp_id, value),
            detail=f"DP{dp_id}={value}",
        )

    async def unlock_350k(self) -> bool:
        """Send DP71 unlock without queueing behind an existing reconnect."""
        if self.product_id != PRODUCT_ID_350K:
            raise TuyaBLEDeviceError(0)

        def build_unlock_payload() -> bytes:
            payload = self._build_raykube_unlock_v4_data()
            if not valid_dp71_payload_shape(payload):
                raise TuyaBLEDeviceError("unexpected 350K DP71 payload framing")
            return payload

        return await self._run_resilient_350k_control(
            "unlock",
            build_unlock_payload,
            detail="DP71 unlock",
            payload_unavailable=True,
            expected_unlocked=True,
            unlock_request=True,
        )

    async def refresh_350k_status(self) -> bool:
        """Request device status, but never queue the request behind reconnect."""
        if self.product_id != PRODUCT_ID_350K:
            raise TuyaBLEDeviceError(0)
        return await self._run_resilient_350k_control(
            "refresh_status",
            bytes,
            code=TuyaBLECode.FUN_SENDER_DEVICE_STATUS,
            detail="device status request",
        )

    async def _send_response(
        self,
        code: TuyaBLECode,
        data: bytes,
        response_to: int,
    ) -> None:
        """Best-effort protocol reply when the proxy vanishes mid-frame."""
        try:
            await super()._send_response(code, data, response_to)
        except BLEAK_EXCEPTIONS as ex:
            _LOGGER.debug(
                "%s: dropped Tuya protocol reply because BLE transport disconnected: %s",
                self.address,
                ex,
            )

    async def _execute_disconnect(self) -> None:
        """Treat proxy EOF during an intentional disconnect as already closed."""
        try:
            await super()._execute_disconnect()
        except BLEAK_EXCEPTIONS as ex:
            aborted = self._abort_transport_waiters()
            # If Bleak's normal disconnected callback already ran while
            # disconnect() was in flight, _is_paired is already False and HA
            # has already been notified. Only synthesize the callback when the
            # proxy vanished before Bleak could deliver it.
            if self._is_paired:
                self._is_paired = False
                super()._fire_disconnected_callbacks()
            async with self._seq_num_lock:
                self._current_seq_num = 1
            _LOGGER.debug(
                "%s: BLE proxy disappeared during disconnect; treating link as closed%s: %s",
                self.address,
                f"; aborted {aborted} pending waiter(s)" if aborted else "",
                ex,
            )

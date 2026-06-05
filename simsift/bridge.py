"""
bridge.py - Serial communication with SimSift firmware.

Handles:
  - Connection / auto-detect port
  - Special commands (+++POWERKEY, +++RESET, +++BOARD)
  - AT command send + response read with timeout
  - Raw passthrough mode
"""

import serial
import time
import re
from typing import Optional


READY_MARKER = b"+SIMSIFT:READY"
DEFAULT_BAUD  = 115200
DEFAULT_TIMEOUT = 0.1   # seconds between read polls


class BridgeError(Exception):
    pass


class Bridge:
    def __init__(self, port: str, baud: int = DEFAULT_BAUD, timeout: float = 5.0):
        self.port    = port
        self.baud    = baud
        self.timeout = timeout
        self._serial: Optional[serial.Serial] = None
        self.board: Optional[str] = None

    # ── Connection ─────────────────────────────────────────────────────────────

    def connect(self, wait_ready: bool = True) -> None:
        self._serial = serial.Serial(
            port     = self.port,
            baudrate = self.baud,
            timeout  = DEFAULT_TIMEOUT,
            dsrdtr   = False,   # do NOT assert DTR - prevents ESP32 auto-reset
            rtscts   = False,   # do NOT assert RTS
        )
        # Belt-and-suspenders: also deassert after open
        self._serial.setDTR(False)
        self._serial.setRTS(False)
        time.sleep(0.5)
        self._serial.reset_input_buffer()

        if wait_ready:
            self._wait_ready()

        # Give FreeRTOS tasks time to start after +SIMSIFT:READY
        time.sleep(0.5)
        self._serial.reset_input_buffer()
        self.board = self.get_board()
        self._ensure_modem_on()

    def _wait_ready(self) -> None:
        deadline = time.time() + self.timeout
        buf = b""
        while time.time() < deadline:
            chunk = self._serial.read(256)
            if chunk:
                buf += chunk
                if READY_MARKER in buf:
                    return
        # Not fatal - modem might already be up from a previous session

    def _ensure_modem_on(self) -> None:
        """Send AT - if no response, trigger POWERKEY and wait for modem boot.

        T-SIM7070G auto-powers its modem at board startup. We give it extra
        time before concluding it needs a powerkey pulse, to avoid accidentally
        toggling it off when it's already running.
        """
        self._serial.reset_input_buffer()
        self._write("AT\r\n")
        # Longer timeout for boards that auto-power the modem (e.g. T-SIM7070G)
        wait = 5.0 if self.board == "t-sim7070g" else 3.0
        resp = self._read_response(timeout=wait, end_markers=("OK", "ERROR"))
        if "OK" not in resp:
            self.powerkey()
            time.sleep(5.0)
            self._serial.reset_input_buffer()

    def disconnect(self) -> None:
        if self._serial and self._serial.is_open:
            self._serial.close()

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.disconnect()

    # ── Special commands ───────────────────────────────────────────────────────

    def powerkey(self) -> None:
        self._send_special("+++POWERKEY")
        self._read_until("+OK:POWERKEY", timeout=6.0)

    def reset(self) -> None:
        self._send_special("+++RESET")
        self._read_until("+OK:RESET", timeout=6.0)

    def get_board(self) -> str:
        self._send_special("+++BOARD")
        resp = self._read_until("+BOARD:", timeout=2.0)
        m = re.search(r"\+BOARD:(\S+)", resp)
        return m.group(1) if m else "unknown"

    def set_baud(self, baud: int) -> None:
        self._send_special(f"+++BAUD:{baud}")
        self._read_until("+OK:BAUD", timeout=2.0)
        self._serial.baudrate = baud

    # ── AT commands ────────────────────────────────────────────────────────────

    def at(self, cmd: str, timeout: float = 5.0,
           end_markers: tuple = ("OK", "ERROR", "+CME ERROR", "+CMS ERROR")) -> str:
        """Send AT command, return full response as string."""
        self._write(cmd.rstrip("\r\n") + "\r\n")
        return self._read_response(timeout=timeout, end_markers=end_markers)

    def at_multi(self, cmd: str, lines: int = 1,
                 timeout: float = 5.0) -> list[str]:
        """Send AT command, return response split into lines."""
        resp = self.at(cmd, timeout=timeout)
        return [l.strip() for l in resp.splitlines() if l.strip()]

    # ── Low-level I/O ──────────────────────────────────────────────────────────

    def _write(self, data: str) -> None:
        if not self._serial or not self._serial.is_open:
            raise BridgeError("Not connected")
        self._serial.write(data.encode())

    def _send_special(self, cmd: str) -> None:
        self._write(cmd + "\n")

    def _read_response(self, timeout: float,
                       end_markers: tuple) -> str:
        buf = ""
        deadline = time.time() + timeout
        while time.time() < deadline:
            chunk = self._serial.read(256)
            if chunk:
                buf += chunk.decode(errors="ignore")
                for marker in end_markers:
                    if marker in buf:
                        return buf
            else:
                time.sleep(0.01)
        return buf

    def _read_until(self, marker: str, timeout: float) -> str:
        buf = ""
        deadline = time.time() + timeout
        while time.time() < deadline:
            chunk = self._serial.read(256)
            if chunk:
                buf += chunk.decode(errors="ignore")
                if marker in buf:
                    return buf
        return buf

    def read_raw(self, size: int = 256, timeout: float = 0.1) -> bytes:
        self._serial.timeout = timeout
        return self._serial.read(size)

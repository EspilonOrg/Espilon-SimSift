"""
watch - Continuous network anomaly monitoring.

Detects changes and irregularities in the cellular environment.
These are INDICATORS - not proof of any specific attack.
Every event has a legitimate explanation in normal network operation.

Events reported:
  CELL_CHANGE      Cell tower changed (normal during movement or handover)
  2G_DOWNGRADE     Network switched from LTE/LTE-M to GSM (coverage or forced)
  NEW_STRONG_CELL  Unknown cell appeared with strong signal (normal or suspicious)
  FWD_ACTIVE       Call forwarding active on SIM (operator VM or configured)
  SIGNAL_LOST      Signal dropped completely
"""

import time
import json
import os
from dataclasses import dataclass
from typing import Optional
from ..modem import Modem, CellInfo


# ── Event definitions ──────────────────────────────────────────────────────────

EVENTS = {
    "CELL_CHANGE":      "Cell tower changed",
    "2G_DOWNGRADE":     "Network downgraded to 2G",
    "NEW_STRONG_CELL":  "Unknown cell with strong signal appeared",
    "FWD_ACTIVE":       "Call forwarding is active on SIM",
    "SIGNAL_LOST":      "Signal lost",
    "SIGNAL_RESTORED":  "Signal restored",
}

# Minimum RSSI difference (dBm) for a new cell to trigger NEW_STRONG_CELL
STRONG_CELL_THRESHOLD = 10


# ── Baseline persistence ───────────────────────────────────────────────────────

def _baseline_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".simsift_baseline.json")


def _load_baseline() -> dict:
    try:
        with open(_baseline_path()) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"known_cells": [], "session_count": 0}


def _save_baseline(baseline: dict) -> None:
    try:
        with open(_baseline_path(), "w") as f:
            json.dump(baseline, f, indent=2)
    except OSError:
        pass


def _cell_key(mcc, mnc, lac, cell_id) -> str:
    return f"{mcc}-{mnc}-{lac}-{cell_id}"


# ── Main watch loop ────────────────────────────────────────────────────────────

def run(modem: Modem, interval: int = 10, callback=None,
        use_neighbors: bool = True) -> None:
    """
    Monitor cellular environment continuously.

    callback(event_type, detail, level) is called on each event.
    level: "info" | "warn"

    Ctrl-C to stop.
    """

    def emit(event: str, detail: str, level: str = "info"):
        if callback:
            callback(event, detail, level)
        else:
            prefix = "[!]" if level == "warn" else "[~]"
            print(f"  {prefix} {event}: {detail}")

    # ── Baseline ──────────────────────────────────────────────────────────────
    baseline = _load_baseline()
    known_cells: set = set(baseline.get("known_cells", []))

    # ── Initial call forward check ─────────────────────────────────────────────
    try:
        forwards = modem.get_call_forwards()
        for f in [fw for fw in forwards if fw.active]:
            emit("FWD_ACTIVE",
                 f"{f.service} → {f.number or 'unknown number'}",
                 level="warn")
    except Exception:
        pass

    # ── State ─────────────────────────────────────────────────────────────────
    prev_cell_key = None
    prev_rat      = None
    had_signal    = True

    try:
        while True:
            cell = modem.get_cell()
            rssi, _ = modem.get_signal()

            # ── Signal lost / restored ─────────────────────────────────────
            has_signal = rssi is not None and rssi > -113
            if not has_signal and had_signal:
                emit("SIGNAL_LOST", "No signal", level="info")
            elif has_signal and not had_signal:
                emit("SIGNAL_RESTORED", f"{rssi} dBm", level="info")
            had_signal = has_signal

            if not has_signal:
                time.sleep(interval)
                continue

            current_key = _cell_key(cell.mcc, cell.mnc, cell.lac, cell.cell_id)

            # ── 2G downgrade ───────────────────────────────────────────────
            if (prev_rat and prev_rat not in ("GSM", None)
                    and cell.rat == "GSM"):
                emit("2G_DOWNGRADE",
                     f"{prev_rat} → GSM  (rssi={rssi} dBm)",
                     level="warn")

            # ── Cell change ────────────────────────────────────────────────
            if prev_cell_key and current_key != prev_cell_key:
                emit("CELL_CHANGE",
                     f"{prev_cell_key} → {current_key}",
                     level="info")

            # Add to baseline
            if current_key not in known_cells:
                known_cells.add(current_key)

            # ── Neighbor scan for unknown strong cells ─────────────────────
            if use_neighbors:
                try:
                    neighbors = modem.get_neighbors()
                    for n in neighbors:
                        nkey = _cell_key(n["mcc"], n["mnc"],
                                         n["lac"], n["cell_id"])
                        if (nkey not in known_cells
                                and n["rssi"] is not None
                                and rssi is not None
                                and n["rssi"] > rssi + STRONG_CELL_THRESHOLD):
                            emit("NEW_STRONG_CELL",
                                 f"cell={nkey}  rssi={n['rssi']} dBm  "
                                 f"(current={rssi} dBm) - not in baseline",
                                 level="warn")
                except Exception:
                    pass  # AT+CENG not supported on this modem

            prev_cell_key = current_key
            prev_rat      = cell.rat
            time.sleep(interval)

    except KeyboardInterrupt:
        pass
    finally:
        # Persist learned cells
        baseline["known_cells"]    = list(known_cells)
        baseline["session_count"]  = baseline.get("session_count", 0) + 1
        _save_baseline(baseline)

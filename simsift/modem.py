"""
modem.py - AT command library for SIM800 / SIM7070G.

All methods return parsed Python objects - no raw AT strings leak to the CLI.
"""

import re
import time
from dataclasses import dataclass, field
from typing import Optional
from .bridge import Bridge


# ── Data types ─────────────────────────────────────────────────────────────────

@dataclass
class SimIdentity:
    pin_status: Optional[str] = None  # READY / SIM PIN / SIM PUK
    imsi:       Optional[str] = None  # 15-digit subscriber identity
    iccid:      Optional[str] = None  # 19-20 digit card serial
    imei:       Optional[str] = None  # 15-digit device identity
    msisdn:     Optional[str] = None  # phone number (if stored on SIM)
    operator:   Optional[str] = None  # operator name
    mcc:        Optional[str] = None  # mobile country code
    mnc:        Optional[str] = None  # mobile network code
    smsc:       Optional[str] = None  # SMS service center address
    network_time: Optional[str] = None  # clock from network

@dataclass
class CellInfo:
    mcc:       Optional[str] = None
    mnc:       Optional[str] = None
    lac:       Optional[str] = None   # location area code (hex)
    cell_id:   Optional[str] = None   # cell ID (hex)
    rssi:      Optional[int] = None   # dBm
    ber:       Optional[int] = None   # bit error rate (0-7)
    rat:       Optional[str] = None   # GSM / LTE-M / NB-IoT
    band:      Optional[str] = None   # SIM7070G only
    rsrp:      Optional[int] = None   # LTE reference signal power (dBm)
    rsrq:      Optional[int] = None   # LTE reference signal quality (dB)
    sinr:      Optional[int] = None   # signal/noise ratio (dB)
    ta:        Optional[int] = None   # timing advance

@dataclass
class GnssInfo:
    fix:        bool = False
    latitude:   Optional[float] = None
    longitude:  Optional[float] = None
    altitude:   Optional[float] = None
    speed:      Optional[float] = None
    timestamp:  Optional[str] = None

@dataclass
class Operator:
    name:   str = ""
    mcc:    str = ""
    mnc:    str = ""
    status: str = ""   # available / current / forbidden

@dataclass
class SMS:
    index:     int = 0
    status:    str = ""
    sender:    str = ""
    timestamp: str = ""
    text:      str = ""

@dataclass
class CallForward:
    service:   str = ""
    active:    bool = False
    number:    Optional[str] = None


# ── Modem class ────────────────────────────────────────────────────────────────

class Modem:
    def __init__(self, bridge: Bridge):
        self.b = bridge

    # ── Basic ──────────────────────────────────────────────────────────────────

    def ping(self) -> bool:
        return "OK" in self.b.at("AT")

    def flush(self) -> None:
        self.b._serial.reset_input_buffer()
        self.b.at("AT", timeout=1.0)
        self.b._serial.reset_input_buffer()

    def get_pin_status(self) -> str:
        """Return PIN status: READY / SIM PIN / SIM PUK / unknown."""
        r = self.b.at("AT+CPIN?")
        m = re.search(r'\+CPIN:\s*(.+)', r)
        return m.group(1).strip() if m else "unknown"

    def unlock_pin(self, pin: str) -> bool:
        """Unlock SIM PIN. Returns True on success."""
        r = self.b.at(f'AT+CPIN="{pin}"', timeout=5.0)
        if "OK" in r:
            time.sleep(1.0)   # modem needs a moment after unlock
            return True
        return False

    def get_signal(self) -> tuple[Optional[int], Optional[int]]:
        """Return (rssi_dbm, ber). ber 0-7 or None if unknown."""
        r = self.b.at("AT+CSQ")
        m = re.search(r"\+CSQ:\s*(\d+),(\d+)", r)
        if not m:
            return None, None
        raw_rssi = int(m.group(1))
        raw_ber  = int(m.group(2))
        rssi = None if raw_rssi == 99 else -113 + raw_rssi * 2
        ber  = None if raw_ber  == 99 else raw_ber
        return rssi, ber

    # ── Identity ───────────────────────────────────────────────────────────────

    def get_identity(self) -> SimIdentity:
        identity = SimIdentity()
        self.b._serial.reset_input_buffer()

        # PIN status
        identity.pin_status = self.get_pin_status()
        pin_ready = (identity.pin_status == "READY")

        # ICCID - always available, no PIN needed
        r = self.b.at("AT+CCID")
        m = re.search(r"(\d{18,22})", r)
        if m:
            identity.iccid = m.group(1)

        # IMEI - device identifier, no PIN needed
        r = self.b.at("AT+CGSN")
        m = re.search(r"(\d{15})", r)
        if m:
            identity.imei = m.group(1)

        if pin_ready:
            # IMSI - requires PIN unlocked
            r = self.b.at("AT+CIMI")
            m = re.search(r"(\d{14,15})", r)
            if m:
                raw = m.group(1)
                identity.imsi = raw
                identity.mcc  = raw[:3]
                identity.mnc  = raw[3:5]

            # Phone number
            r = self.b.at("AT+CNUM")
            m = re.search(r'\+CNUM:[^,]*,"([^"]+)"', r)
            if m:
                identity.msisdn = m.group(1)

            # SMS Service Center Address
            r = self.b.at("AT+CSCA?")
            m = re.search(r'\+CSCA:\s*"([^"]+)"', r)
            if m:
                identity.smsc = m.group(1)

        # Operator name (works even when searching)
        r = self.b.at('AT+COPS=3,0')  # set text format
        self.b.at('AT+COPS=3,0')
        r = self.b.at('AT+COPS?')
        m = re.search(r'\+COPS:\d,\d,"([^"]+)"', r)
        if m:
            identity.operator = m.group(1)

        # Network clock (only available when registered)
        r = self.b.at("AT+CCLK?")
        m = re.search(r'\+CCLK:\s*"([^"]+)"', r)
        if m and not m.group(1).startswith("80"):
            identity.network_time = m.group(1)

        return identity

    # ── Cell info ──────────────────────────────────────────────────────────────

    def get_cell(self) -> CellInfo:
        cell = CellInfo()
        cell.rssi, cell.ber = self.get_signal()

        # Set verbose CREG then query
        self.b.at("AT+CREG=2")
        r = self.b.at("AT+CREG?")

        # Verbose: +CREG: 2,1,"LAC","CID",AcT
        m = re.search(r'\+CREG:\s*2,\d,"([0-9A-Fa-f]+)","([0-9A-Fa-f]+)",?(\d*)', r)
        if m:
            cell.lac     = m.group(1)
            cell.cell_id = m.group(2)
            rat_map = {"0":"GSM","1":"GSM_COMPACT","3":"EDGE",
                       "7":"LTE-M","9":"NB-IoT"}
            cell.rat = rat_map.get(m.group(3), m.group(3) or "GSM")
        else:
            m2 = re.search(r'\+CREG:\s*(?:\d+,)?(\d+)', r)
            if m2:
                cell.rat = "GSM" if m2.group(1) in ("1","5") else None

        # Also try GPRS registration for cell data
        self.b.at("AT+CGREG=2")
        r2 = self.b.at("AT+CGREG?")
        m3 = re.search(r'\+CGREG:\s*2,\d,"([0-9A-Fa-f]+)","([0-9A-Fa-f]+)"', r2)
        if m3 and not cell.lac:
            cell.lac     = m3.group(1)
            cell.cell_id = m3.group(2)

        # MCC/MNC - try numeric COPS first, then parse from IMSI (no full identity call)
        self.b.at('AT+COPS=3,2')
        r = self.b.at('AT+COPS?')
        m = re.search(r'\+COPS:\s*\d,2,"(\d{3})(\d{2,3})"', r)
        if m:
            cell.mcc = m.group(1)
            cell.mnc = m.group(2)
        else:
            # Derive from IMSI directly - no need for full get_identity()
            r_imsi = self.b.at("AT+CIMI")
            m_imsi = re.search(r"(\d{5,6})", r_imsi)
            if m_imsi:
                cell.mcc = m_imsi.group(1)[:3]
                cell.mnc = m_imsi.group(1)[3:5]

        return cell

    # ── SIM7070G extended cell info ────────────────────────────────────────────

    def get_cell_extended(self) -> dict:
        """AT+CPSI - SIM7070G extended: band, freq, RSRP, RSRQ, SINR, TA."""
        r = self.b.at("AT+CPSI?")
        # +CPSI: LTE CAT-M1,Online,460-11,0x779B,167909897,65,EUTRAN-BAND3,
        #        1850,3,3,-109,-11,-79,13
        result = {}
        m = re.search(
            r'\+CPSI:\s*([^,]+),([^,]+),(\d+)-(\d+),\S+,\S+,\S+,([^,]+),\S+,\S+,\S+,(-?\d+),(-?\d+),(-?\d+)',
            r
        )
        if m:
            result["rat"]      = m.group(1).strip()
            result["status"]   = m.group(2).strip()
            result["mcc"]      = m.group(3)
            result["mnc"]      = m.group(4)
            result["band"]     = m.group(5).strip()
            result["rsrp_dbm"] = int(m.group(6))
            result["rsrq_db"]  = int(m.group(7))
            result["sinr_db"]  = int(m.group(8))
        return result

    # ── GNSS (SIM7070G) ────────────────────────────────────────────────────────

    def gnss_start(self) -> bool:
        """Power on GNSS module."""
        r = self.b.at("AT+CGNSPWR=1", timeout=3.0)
        return "OK" in r

    def gnss_stop(self) -> None:
        self.b.at("AT+CGNSPWR=0")

    def get_gnss(self, timeout: float = 60.0) -> GnssInfo:
        """Wait for GNSS fix and return position."""
        self.gnss_start()
        info = GnssInfo()
        deadline = time.time() + timeout

        while time.time() < deadline:
            r = self.b.at("AT+CGNSINF")
            # +CGNSINF: 1,1,20240101120000.000,48.8566,2.3522,35.0,0.0,...
            m = re.search(
                r'\+CGNSINF:\s*\d,(\d),(\d{14}\.\d+)?,([-\d.]+)?,([-\d.]+)?,([-\d.]+)?,([-\d.]+)?',
                r
            )
            if m and m.group(1) == "1":   # fix acquired
                info.fix       = True
                info.timestamp = m.group(2)
                try:
                    info.latitude  = float(m.group(3))
                    info.longitude = float(m.group(4))
                    info.altitude  = float(m.group(5)) if m.group(5) else None
                    info.speed     = float(m.group(6)) if m.group(6) else None
                except (TypeError, ValueError):
                    pass
                break
            time.sleep(2.0)

        return info

    # ── Neighbor cell scan (SIM800 AT+CENG) ───────────────────────────────────

    def get_neighbors(self) -> list[dict]:
        """Return list of visible cells via AT+CENG (serving + neighbors).
        Each entry: {lac, cell_id, rssi, mcc, mnc}
        Returns empty list if modem doesn't support AT+CENG.
        """
        self.b.at("AT+CENG=1,1")   # enable engineering mode, include neighbors
        r = self.b.at("AT+CENG?", timeout=3.0)
        cells = []
        # +CENG: <index>,"<arfcn>,<rxlev>,<bsic>,<mcc>,<mnc>,<lac>,<cellid>,..."
        for m in re.finditer(
            r'\+CENG:\s*\d+,"(\w+),(\d+),\w+,(\d+),(\d+),(\w+),(\w+)',
            r
        ):
            try:
                rssi_raw = int(m.group(2))
                cells.append({
                    "arfcn":   m.group(1),
                    "rssi":    -113 + rssi_raw * 2 if rssi_raw < 99 else None,
                    "mcc":     m.group(3),
                    "mnc":     m.group(4),
                    "lac":     m.group(5),
                    "cell_id": m.group(6),
                })
            except (ValueError, IndexError):
                continue
        return cells

    # ── Network scan ───────────────────────────────────────────────────────────

    def scan_operators(self, timeout: float = 60.0) -> list[Operator]:
        r = self.b.at("AT+COPS=?", timeout=timeout)
        operators = []
        status_map = {"0":"unknown","1":"available","2":"current","3":"forbidden"}
        for m in re.finditer(r'\((\d),"([^"]*)","[^"]*","(\d{3})(\d{2,3})"', r):
            operators.append(Operator(
                status = status_map.get(m.group(1), m.group(1)),
                name   = m.group(2),
                mcc    = m.group(3),
                mnc    = m.group(4),
            ))
        return operators

    # ── SMS ────────────────────────────────────────────────────────────────────

    def list_sms(self) -> list[SMS]:
        self.b.at('AT+CMGF=1')
        r = self.b.at('AT+CMGL="ALL"', timeout=10.0)
        messages = []
        lines = r.splitlines()
        i = 0
        while i < len(lines):
            m = re.match(
                r'\+CMGL:\s*(\d+),"([^"]*)","([^"]*)",[^,]*,"([^"]*)"',
                lines[i].strip()
            )
            if m:
                text = lines[i + 1].strip() if i + 1 < len(lines) else ""
                messages.append(SMS(
                    index     = int(m.group(1)),
                    status    = m.group(2),
                    sender    = m.group(3),
                    timestamp = m.group(4),
                    text      = text,
                ))
                i += 2
            else:
                i += 1
        return messages

    # ── SMS send ───────────────────────────────────────────────────────────────

    def send_sms(self, number: str, text: str) -> bool:
        """Send SMS. Returns True on success."""
        self.b.at('AT+CMGF=1')
        self.b._write(f'AT+CMGS="{number}"\r\n')
        time.sleep(0.5)
        resp = self.b._read_response(timeout=3.0, end_markers=(">",))
        if ">" not in resp:
            return False
        self.b._write(text + "\x1A")   # message + Ctrl-Z to send
        r = self.b._read_response(timeout=15.0,
                                   end_markers=("+CMGS:", "ERROR", "OK"))
        return "+CMGS:" in r

    # ── USSD ───────────────────────────────────────────────────────────────────

    def ussd(self, code: str, timeout: float = 15.0) -> str:
        self.b._serial.reset_input_buffer()
        self.b.at(f'AT+CUSD=1,"{code}",15', timeout=5.0)
        resp = self.b._read_until("+CUSD:", timeout=timeout)
        m = re.search(r'\+CUSD:\s*\d,"([^"]*)"', resp)
        if m:
            return m.group(1)
        m2 = re.search(r'\+CUSD:\s*(\d)', resp)
        status_map = {"0":"OK (no text)","1":"further input needed",
                      "2":"USSD terminated by network","3":"not supported"}
        if m2:
            return status_map.get(m2.group(1), f"status={m2.group(1)}")
        return resp.strip() or "no response"

    # ── Call forwarding ────────────────────────────────────────────────────────

    def get_call_forwards(self) -> list[CallForward]:
        results = []
        for reason, name in [(0,"unconditional"),(1,"busy"),
                             (2,"no_reply"),(3,"unreachable")]:
            r = self.b.at(f"AT+CCFC={reason},2")
            m = re.search(r'\+CCFC:\s*(\d),\d+,"?([^",\r\n]*)"?', r)
            if m:
                results.append(CallForward(
                    service = name,
                    active  = m.group(1) == "1",
                    number  = m.group(2) if m.group(2) else None,
                ))
        return results

    # ── Raw AT passthrough ─────────────────────────────────────────────────────

    def raw(self, cmd: str, timeout: float = 5.0) -> str:
        return self.b.at(cmd, timeout=timeout)

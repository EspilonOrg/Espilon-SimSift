"""identity - Who is this SIM?"""
from ..modem import Modem


def run(modem: Modem) -> dict:
    identity    = modem.get_identity()
    rssi, ber   = modem.get_signal()

    return {
        "pin_status":   identity.pin_status,
        "imsi":         identity.imsi,
        "iccid":        identity.iccid,
        "imei":         identity.imei,
        "msisdn":       identity.msisdn,
        "operator":     identity.operator,
        "mcc":          identity.mcc,
        "mnc":          identity.mnc,
        "smsc":         identity.smsc,
        "network_time": identity.network_time,
        "rssi_dbm":     rssi,
        "ber":          ber,
    }

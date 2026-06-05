"""status - Full readable dashboard, everything at once."""
from ..modem import Modem


def run(modem: Modem) -> dict:
    # get_cell() already calls get_signal() - no duplicate
    identity = modem.get_identity()
    cell     = modem.get_cell()
    forwards = modem.get_call_forwards()
    msgs     = modem.list_sms()

    try:
        operators = modem.scan_operators(timeout=45.0)
    except Exception:
        operators = []

    return {
        "identity":          identity,
        "cell":              cell,
        "call_forwards":     forwards,
        "sms_count":         len(msgs),
        "visible_operators": operators,
    }

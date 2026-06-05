"""forensics - Full SIM dump."""
from ..modem import Modem
from . import identity, cells


def run(modem: Modem) -> dict:
    result = {}

    result["identity"]      = identity.run(modem)
    result["cell"]          = cells.run(modem)
    result["sms"]           = [vars(s) for s in modem.list_sms()]
    result["call_forwards"] = [vars(f) for f in modem.get_call_forwards()]

    operators = modem.scan_operators(timeout=60.0)
    result["visible_operators"] = [vars(o) for o in operators]

    return result

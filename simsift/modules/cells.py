"""cells - Current cell tower + passive geolocation hint."""
from ..modem import Modem

OPENCELLID_URL = "https://opencellid.org/cell/get?key=YOUR_KEY&mcc={mcc}&mnc={mnc}&lac={lac}&cellid={cid}&format=json"

def run(modem: Modem) -> dict:
    # get_cell() already calls get_signal() internally - no duplicate call
    cell = modem.get_cell()

    result = {
        "mcc":      cell.mcc,
        "mnc":      cell.mnc,
        "lac":      cell.lac,
        "cell_id":  cell.cell_id,
        "rssi_dbm": cell.rssi,
        "ber":      cell.ber,
        "rat":      cell.rat,
    }

    if all([cell.mcc, cell.mnc, cell.lac, cell.cell_id]):
        try:
            result["opencellid_url"] = OPENCELLID_URL.format(
                mcc=cell.mcc, mnc=cell.mnc,
                lac=int(cell.lac, 16),
                cid=int(cell.cell_id, 16),
            )
        except (ValueError, TypeError):
            pass

    return result

"""
SimSift CLI
"""

import argparse
import json
import sys
from .bridge import Bridge, BridgeError
from .modem  import Modem
from .        import modules
from .ui      import (console, print_banner, print_board, print_section,
                      kv_table, operator_table, sms_list, watch_event,
                      ok, info, error)


def cmd_status(modem: Modem, args) -> None:
    """Full dashboard - everything in one shot."""
    from rich.progress import Progress, SpinnerColumn, TextColumn
    with Progress(SpinnerColumn(), TextColumn("[muted]{task.description}"),
                  console=console, transient=True) as p:
        p.add_task("Collecting all SIM data (scanning operators - up to 45s)...")
        data = modules.status.run(modem)

    if args.json:
        import dataclasses
        def _serial(o):
            if dataclasses.is_dataclass(o):
                return dataclasses.asdict(o)
            return str(o)
        import json
        console.print_json(json.dumps(data, default=_serial))
        return

    ident = data["identity"]
    cell  = data["cell"]

    # ── SIM Identity ─────────────────────────────────────────────────────────
    print_section("SIM Identity")
    id_data = {
        "pin_status":  ident.pin_status,
        "imsi":        ident.imsi,
        "iccid":       ident.iccid,
        "imei":        ident.imei,
        "msisdn":      ident.msisdn,
        "operator":    ident.operator,
        "mcc / mnc":   f"{ident.mcc} / {ident.mnc}" if ident.mcc else None,
        "smsc":        ident.smsc,
        "network_time":ident.network_time,
    }
    kv_table({k: v for k, v in id_data.items() if v is not None})

    # ── Signal & Cell ─────────────────────────────────────────────────────────
    print_section("Signal & Cell")
    cell_data = {
        "rssi":    f"{cell.rssi} dBm" if cell.rssi else "no signal",
        "ber":     str(cell.ber) if cell.ber is not None else None,
        "rat":     cell.rat,
        "mcc/mnc": f"{cell.mcc}/{cell.mnc}" if cell.mcc else None,
        "lac":     cell.lac,
        "cell_id": cell.cell_id,
    }
    kv_table({k: v for k, v in cell_data.items() if v is not None})
    if cell.lac and cell.cell_id and cell.mcc:
        from .modules.cells import OPENCELLID_URL
        console.print(f"  [muted]Lookup →[/] [dim]{OPENCELLID_URL.format(mcc=cell.mcc,mnc=cell.mnc,lac=int(cell.lac,16),cid=int(cell.cell_id,16))}[/]\n")

    # ── SMS ───────────────────────────────────────────────────────────────────
    print_section("SMS")
    count = data["sms_count"]
    if count == 0:
        console.print("  [muted]No SMS on SIM.[/]\n")
    else:
        console.print(f"  [accent]{count}[/] [muted]message(s) stored on SIM - run[/] [data]sms[/] [muted]to list.[/]\n")

    # ── Call Forwards ─────────────────────────────────────────────────────────
    active_fwd = [f for f in data["call_forwards"] if f.active]
    print_section("Call Forwards")
    if not active_fwd:
        console.print("  [ok]None active.[/]\n")
    else:
        for f in active_fwd:
            console.print(f"  [err]⚠ {f.service}[/] [muted]→[/] [data]{f.number or 'unknown'}[/]")
        console.print()

    # ── Visible Operators ─────────────────────────────────────────────────────
    ops = data["visible_operators"]
    if ops:
        operator_table([vars(o) for o in ops])


def cmd_identity(modem: Modem, args) -> None:
    data = modules.identity.run(modem)
    if args.json:
        console.print_json(json.dumps(data, default=str))
    else:
        kv_table(data, "SIM Identity")


def cmd_cells(modem: Modem, args) -> None:
    data = modules.cells.run(modem)
    if args.json:
        console.print_json(json.dumps(data, default=str))
    else:
        kv_table(data, "Cell Info")
        if "opencellid_url" in data:
            console.print(
                f"  [muted]Lookup →[/] [dim]{data['opencellid_url']}[/]\n"
            )


def cmd_scan(modem: Modem, args) -> None:
    info("Scanning operators - may take up to 60s...")
    ops = modem.scan_operators()
    if args.json:
        console.print_json(json.dumps([vars(o) for o in ops], default=str))
    else:
        operator_table([vars(o) for o in ops])


def cmd_sms(modem: Modem, args) -> None:
    if hasattr(args, 'action') and args.action == "send":
        info(f"Sending SMS to [accent]{args.number}[/] ...")
        ok_sent = modem.send_sms(args.number, args.text)
        if ok_sent:
            ok("SMS sent successfully")
        else:
            error("SMS send failed")
        return

    msgs = modem.list_sms()
    if args.json:
        console.print_json(json.dumps([vars(m) for m in msgs], default=str))
    else:
        sms_list([vars(m) for m in msgs])


def cmd_ussd(modem: Modem, args) -> None:
    info(f"Sending USSD [accent]{args.code}[/] ...")
    resp = modem.ussd(args.code)
    print_section("USSD Response")
    console.print(f"  [data]{resp}[/]\n")


def cmd_watch(modem: Modem, args) -> None:
    from datetime import datetime
    print_section(f"Watch  [muted](interval={args.interval}s - Ctrl-C to stop)[/]")
    console.print("  [muted]Monitoring network anomalies. Events have legitimate explanations.[/]\n")

    def on_event(kind: str, detail: str, level: str = "info"):
        ts = datetime.now().strftime("%H:%M:%S")
        watch_event(kind, detail, ts, level)

    modules.watch.run(modem, interval=args.interval, callback=on_event)


def cmd_forensics(modem: Modem, args) -> None:
    from rich.progress import Progress, SpinnerColumn, TextColumn
    with Progress(SpinnerColumn(), TextColumn("[muted]{task.description}"),
                  console=console, transient=True) as p:
        p.add_task("Running full forensics dump...")
        data = modules.forensics.run(modem)

    if args.output:
        with open(args.output, "w") as f:
            json.dump(data, f, indent=2, default=str)
        ok(f"Report saved → [accent]{args.output}[/]")
    else:
        console.print_json(json.dumps(data, default=str))


def cmd_at(modem: Modem, args) -> None:
    resp = modem.raw(args.cmd, timeout=args.timeout)
    console.print(f"[muted]{resp}[/]")


def main():
    parser = argparse.ArgumentParser(
        prog="simsift",
        description="SimSift - SIM OSINT & cellular recon  [Espilon]",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  simsift -p /dev/ttyUSB0 identity\n"
            "  simsift -p /dev/ttyACM0 forensics -o report.json\n"
            "  simsift -p /dev/ttyUSB0 watch --interval 5\n"
            "  simsift -p /dev/ttyUSB0 ussd \"*100#\"\n"
            "  simsift -p /dev/ttyUSB0 scan\n"
        ),
    )
    parser.add_argument("-p", "--port",  required=True,
                        help="Serial port  e.g. /dev/ttyUSB0 or COM3")
    parser.add_argument("-b", "--baud",  type=int, default=115200)
    parser.add_argument("--pin",         default=None,
                        help="SIM PIN to unlock (e.g. 0000)")
    parser.add_argument("--json",        action="store_true",
                        help="Output raw JSON (pipe-friendly)")
    parser.add_argument("--no-banner",   action="store_true",
                        help="Skip the ASCII banner")

    sub = parser.add_subparsers(dest="command", required=True,
                                metavar="command")

    sub.add_parser("status",
                   help="Full dashboard - identity · signal · SMS · forwards · operators")
    sub.add_parser("identity",
                   help="SIM identity - IMSI · ICCID · IMEI · operator")
    sub.add_parser("cells",
                   help="Current cell tower · LAC · RSSI · geolocation hint")
    sub.add_parser("scan",
                   help="Scan all visible operators  (slow - up to 60s)")
    p_sms = sub.add_parser("sms", help="List SMS or send SMS")
    sms_sub = p_sms.add_subparsers(dest="action")
    p_sms_send = sms_sub.add_parser("send", help="Send SMS")
    p_sms_send.add_argument("number", help="Destination number")
    p_sms_send.add_argument("text",   help="Message text")

    p_ussd = sub.add_parser("ussd", help="Send USSD query  e.g. *100#")
    p_ussd.add_argument("code", help="USSD code  e.g. *100#")

    p_watch = sub.add_parser("watch",
                              help="Continuous monitoring · anomaly detection")
    p_watch.add_argument("--interval", type=int, default=10,
                         help="Poll interval in seconds  (default 10)")

    p_foren = sub.add_parser("forensics",
                              help="Full SIM dump - identity · cells · SMS · forwards · operators")
    p_foren.add_argument("-o", "--output",
                         help="Save JSON report to file")

    p_at = sub.add_parser("at", help="Send raw AT command")
    p_at.add_argument("cmd",     help="AT command  e.g. AT+CIMI")
    p_at.add_argument("--timeout", type=float, default=5.0)

    args = parser.parse_args()

    if not args.json and not args.no_banner:
        print_banner()

    try:
        with Bridge(args.port, args.baud) as bridge:
            if not args.json:
                board = bridge.board or "unknown"
                print_board(board, args.port)

            modem = Modem(bridge)

            # Auto-unlock PIN if provided
            if args.pin:
                status = modem.get_pin_status()
                if status == "SIM PIN":
                    if not args.json:
                        info("Unlocking PIN...")
                    if not modem.unlock_pin(args.pin):
                        error("PIN unlock failed")
                        sys.exit(1)
                    if not args.json:
                        ok("PIN unlocked")

            dispatch = {
                "status":    cmd_status,
                "identity":  cmd_identity,
                "cells":     cmd_cells,
                "scan":      cmd_scan,
                "sms":       cmd_sms,
                "ussd":      cmd_ussd,
                "watch":     cmd_watch,
                "forensics": cmd_forensics,
                "at":        cmd_at,
            }
            dispatch[args.command](modem, args)

    except BridgeError as e:
        error(str(e))
        sys.exit(1)
    except KeyboardInterrupt:
        console.print("\n  [muted]Interrupted.[/]")

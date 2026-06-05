"""
ui.py - SimSift visual layer (Rich)

Palette from espilon.net:
  accent  #0099ff   - blue electric
  text    #e4e4e7   - primary
  muted   #8a8a96   - secondary
  dim     #52525a   - tertiary
  border  #27272a
"""

from rich.console import Console
from rich.table   import Table
from rich.panel   import Panel
from rich.text    import Text
from rich.theme   import Theme
from rich         import box
import sys

THEME = Theme({
    "accent":  "#0099ff bold",
    "muted":   "#8a8a96",
    "dim":     "#52525a",
    "ok":      "#22c55e bold",
    "warn":    "#f59e0b bold",
    "err":     "#ef4444 bold",
    "data":    "#e4e4e7",
})

console = Console(theme=THEME, highlight=False)

BANNER = """\
[accent]  ███████╗██╗███╗   ███╗███████╗██╗███████╗████████╗[/]
[accent]  ██╔════╝██║████╗ ████║██╔════╝██║██╔════╝╚══██╔══╝[/]
[accent]  ███████╗██║██╔████╔██║███████╗██║█████╗     ██║   [/]
[accent]  ╚════██║██║██║╚██╔╝██║╚════██║██║██╔══╝     ██║   [/]
[accent]  ███████║██║██║ ╚═╝ ██║███████║██║██║        ██║   [/]
[accent]  ╚══════╝╚═╝╚═╝     ╚═╝╚══════╝╚═╝╚═╝        ╚═╝   [/]
[muted]  SIM OSINT & Cellular Recon  ·  github.com/Espilon-Org[/]
"""


def print_banner():
    console.print(BANNER)


def print_board(board: str, port: str):
    console.print(
        f"  [accent]▸[/] [data]Board[/] [muted]{board}[/]  "
        f"[dim]·[/]  [data]Port[/] [muted]{port}[/]\n"
    )


def print_section(title: str):
    console.rule(f"[accent]{title}[/]", style="dim")
    console.print()


def kv_table(data: dict, title: str = "") -> None:
    """Print a key/value table, skip None values."""
    t = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    t.add_column(style="muted",  no_wrap=True, min_width=20)
    t.add_column(style="data",   no_wrap=False)

    for k, v in data.items():
        if v is None:
            continue
        # Colour specific keys
        if k == "rssi_dbm" and isinstance(v, int):
            if v >= -70:
                val = f"[ok]{v} dBm[/]"
            elif v >= -90:
                val = f"[warn]{v} dBm[/]"
            else:
                val = f"[err]{v} dBm[/]"
        elif k in ("imsi", "iccid", "imei", "cell_id", "lac"):
            val = f"[accent]{v}[/]"
        elif k == "opencellid_url":
            val = f"[muted]{v}[/]"
        else:
            val = str(v)
        t.add_row(k, val)

    if title:
        print_section(title)
    console.print(t)


def operator_table(operators: list) -> None:
    print_section("Visible Operators")
    t = Table(box=box.SIMPLE, show_header=True, header_style="muted",
              padding=(0, 2))
    t.add_column("Status",   style="data",  min_width=12)
    t.add_column("MCC",      style="muted", min_width=5)
    t.add_column("MNC",      style="muted", min_width=5)
    t.add_column("Operator", style="data")

    status_style = {
        "current":   "ok",
        "available": "accent",
        "forbidden": "err",
    }
    for o in operators:
        style = status_style.get(o.get("status", ""), "muted")
        t.add_row(
            f"[{style}]{o.get('status','')}[/]",
            o.get("mcc", ""),
            o.get("mnc", ""),
            o.get("name", ""),
        )
    console.print(t)


def sms_list(messages: list) -> None:
    print_section("SMS")
    if not messages:
        console.print("  [muted]No SMS on SIM.[/]\n")
        return
    for m in messages:
        console.print(
            f"  [dim][{m.get('index')}][/] "
            f"[muted]{m.get('status','')}[/]  "
            f"[accent]{m.get('sender','')}[/]  "
            f"[dim]{m.get('timestamp','')}[/]"
        )
        console.print(f"  [data]{m.get('text','')}[/]\n")


def watch_event(kind: str, detail: str, ts: str, level: str = "info") -> None:
    if level == "warn":
        icon, style = "[warn]▲[/]", "warn"
    elif level == "err":
        icon, style = "[err]![/]", "err"
    else:
        icon, style = "[dim]·[/]", "muted"

    console.print(
        f"  [dim]{ts}[/]  {icon}  [{style}]{kind}[/]  [muted]{detail}[/]"
    )


def anomaly_banner(kind: str, detail: str) -> None:
    console.print(Panel(
        f"[err]{kind}[/]\n[muted]{detail}[/]",
        border_style="err",
        expand=False,
        padding=(0, 2),
    ))


def ok(msg: str) -> None:
    console.print(f"  [ok]✓[/]  [data]{msg}[/]")


def info(msg: str) -> None:
    console.print(f"  [muted]{msg}[/]")


def error(msg: str) -> None:
    console.print(f"  [err]✗[/]  {msg}")

import subprocess
import time
from pathlib import Path

from rich.console import Console
from rich.table import Table

console = Console()

DATA_DIR = Path(__file__).parent.parent / "data"
PEERS_FILE = DATA_DIR / "peers.json"


def _svc_is_active(name: str) -> bool:
    r = subprocess.run(
        ["systemctl", "is-active", name],
        capture_output=True, text=True
    )
    return r.stdout.strip() == "active"


def _svc_uptime(name: str) -> str:
    try:
        r = subprocess.run(
            ["systemctl", "show", name, "--property=ActiveEnterTimestamp"],
            capture_output=True, text=True, check=True
        )
        line = r.stdout.strip()
        if "=" in line:
            ts_str = line.split("=", 1)[1].strip()
            if not ts_str:
                return "—"
            import datetime
            fmt = "%a %Y-%m-%d %H:%M:%S %Z"
            try:
                started = datetime.datetime.strptime(ts_str, fmt)
                delta = datetime.datetime.now() - started.replace(tzinfo=None)
                secs = int(delta.total_seconds())
                if secs < 60:
                    return f"{secs}s"
                if secs < 3600:
                    return f"{secs // 60}m {secs % 60}s"
                return f"{secs // 3600}h {(secs % 3600) // 60}m"
            except ValueError:
                return ts_str
    except Exception:
        return "—"
    return "—"


def _get_handshakes() -> dict:
    try:
        result = subprocess.run(
            ["wg", "show", "wg0", "dump"],
            capture_output=True, text=True, check=True
        )
    except subprocess.CalledProcessError:
        return {}

    hs = {}
    for line in result.stdout.strip().splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) >= 5:
            try:
                hs[parts[0]] = int(parts[4])
            except ValueError:
                hs[parts[0]] = 0
    return hs


def _format_hs(epoch: int) -> str:
    if epoch == 0:
        return "never"
    delta = int(time.time()) - epoch
    if delta < 60:
        return f"{delta}s ago"
    if delta < 3600:
        return f"{delta // 60}m ago"
    if delta < 86400:
        return f"{delta // 3600}h ago"
    return f"{delta // 86400}d ago"


def show_status():
    import json

    wg_active = _svc_is_active("wg-quick@wg0")
    nitrox_active = _svc_is_active("nitrox")
    nitrox_uptime = _svc_uptime("nitrox") if nitrox_active else "—"

    try:
        r = subprocess.run(
            ["curl", "-s", "--max-time", "5", "ifconfig.me"],
            capture_output=True, text=True
        )
        public_ip = r.stdout.strip() or "unknown"
    except Exception:
        public_ip = "unknown"

    try:
        peers = json.loads(PEERS_FILE.read_text()) if PEERS_FILE.exists() else []
    except Exception:
        peers = []

    handshakes = _get_handshakes() if wg_active else {}
    now = int(time.time())
    active_peers = [
        p for p in peers
        if handshakes.get(p["public_key"], 0) > 0
        and now - handshakes.get(p["public_key"], 0) <= 180
    ]

    wg_label = "[green]active[/green]" if wg_active else "[red]inactive[/red]"
    nitrox_label = "[green]active[/green]" if nitrox_active else "[red]inactive[/red]"

    console.print("\n[bold]Nitrox Server Status[/bold]")
    console.print("=" * 52)
    console.print(f"  [cyan]WireGuard:[/cyan]   {wg_label}")
    console.print(f"  [cyan]Nitrox:[/cyan]      {nitrox_label}  uptime: {nitrox_uptime}")
    console.print(f"  [cyan]Public IP:[/cyan]   {public_ip}")
    console.print(
        f"  [cyan]Peers:[/cyan]       {len(peers)} total, "
        f"[green]{len(active_peers)}[/green] active (handshake ≤3m)"
    )

    if not peers:
        console.print("\n[yellow]No peers configured.[/yellow]")
        return

    table = Table(show_lines=True, expand=False)
    table.add_column("Name", style="bold cyan")
    table.add_column("VPN IP", style="green")
    table.add_column("Handshake", style="yellow")
    table.add_column("Status", style="white")

    for p in peers:
        ts = handshakes.get(p["public_key"], 0)
        hs_str = _format_hs(ts) if wg_active else "—"
        is_active = wg_active and ts > 0 and (now - ts) <= 180
        status_str = "[green]●[/green]" if is_active else "[dim]○[/dim]"
        table.add_row(p["name"], p["vpn_ip"], hs_str, status_str)

    console.print()
    console.print(table)

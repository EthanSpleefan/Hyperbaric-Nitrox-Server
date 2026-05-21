import json
import subprocess
import time
from pathlib import Path

from rich.console import Console
from rich.table import Table

console = Console()

DATA_DIR = Path(__file__).parent.parent / "data"
PEERS_FILE = DATA_DIR / "peers.json"
NITROX_SERVICE = "nitrox"
WG_SERVICE = "wg-quick@wg0"


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


def _load_peers() -> list:
    try:
        return json.loads(PEERS_FILE.read_text()) if PEERS_FILE.exists() else []
    except Exception:
        return []


def get_status_dict() -> dict:
    from modules.endpoint import get_wireguard_endpoint, read_endpoint_config

    wg_active = _svc_is_active(WG_SERVICE)
    nitrox_active = _svc_is_active(NITROX_SERVICE)
    nitrox_uptime = _svc_uptime(NITROX_SERVICE) if nitrox_active else None

    endpoint_cfg = read_endpoint_config()
    wg_endpoint = get_wireguard_endpoint()

    peers = _load_peers()
    handshakes = _get_handshakes() if wg_active else {}
    now = int(time.time())
    active_count = sum(
        1 for p in peers
        if handshakes.get(p["public_key"], 0) > 0
        and now - handshakes.get(p["public_key"], 0) <= 180
    )

    peer_rows = []
    for p in peers:
        ts = handshakes.get(p["public_key"], 0)
        peer_rows.append({
            "name": p["name"],
            "vpn_ip": p["vpn_ip"],
            "handshake": _format_hs(ts) if wg_active else "—",
            "online": bool(wg_active and ts > 0 and (now - ts) <= 180),
        })

    return {
        "wireguard": {
            "running": wg_active,
            "service": WG_SERVICE,
        },
        "nitrox": {
            "running": nitrox_active,
            "service": NITROX_SERVICE,
            "uptime": nitrox_uptime,
            "game_port": 11000,
        },
        "endpoint": {
            "host": wg_endpoint,
            "port": 51820,
            "source": (endpoint_cfg or {}).get("source"),
        },
        "peers": {
            "total": len(peers),
            "active": active_count,
            "items": peer_rows,
        },
    }


def control_nitrox(action: str) -> dict:
    """Start or stop the nitrox systemd unit. Requires root."""
    if action not in ("start", "stop"):
        return {"ok": False, "error": f"Invalid action: {action}"}

    try:
        r = subprocess.run(
            ["systemctl", action, NITROX_SERVICE],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip()
        hint = ""
        if "Access denied" in err or "Interactive authentication" in err:
            hint = " Run the web UI with sudo: sudo nitrox web"
        return {"ok": False, "error": err or f"systemctl {action} failed", "hint": hint}

    status = get_status_dict()
    return {
        "ok": True,
        "action": action,
        "nitrox": status["nitrox"],
    }


def show_status():
    data = get_status_dict()
    wg_active = data["wireguard"]["running"]
    nitrox_active = data["nitrox"]["running"]
    nitrox_uptime = data["nitrox"]["uptime"] or "—"
    peers = _load_peers()
    active_peers = data["peers"]["active"]
    wg_endpoint = data["endpoint"]["host"]

    wg_label = "[green]active[/green]" if wg_active else "[red]inactive[/red]"
    nitrox_label = "[green]active[/green]" if nitrox_active else "[red]inactive[/red]"

    console.print("\n[bold]Nitrox Server Status[/bold]")
    console.print("=" * 52)
    console.print(f"  [cyan]WireGuard:[/cyan]   {wg_label}")
    console.print(f"  [cyan]Nitrox:[/cyan]      {nitrox_label}  uptime: {nitrox_uptime}")
    console.print(f"  [cyan]Endpoint:[/cyan]    {wg_endpoint}:51820")
    console.print(
        f"  [cyan]Peers:[/cyan]       {len(peers)} total, "
        f"[green]{active_peers}[/green] active (handshake ≤3m)"
    )

    if not peers:
        console.print("\n[yellow]No peers configured.[/yellow]")
        return

    table = Table(show_lines=True, expand=False)
    table.add_column("Name", style="bold cyan")
    table.add_column("VPN IP", style="green")
    table.add_column("Handshake", style="yellow")
    table.add_column("Status", style="white")

    for row in data["peers"]["items"]:
        status_str = "[green]●[/green]" if row["online"] else "[dim]○[/dim]"
        table.add_row(row["name"], row["vpn_ip"], row["handshake"], status_str)

    console.print()
    console.print(table)

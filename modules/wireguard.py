import fcntl
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

console = Console()

WG_DIR = Path("/etc/wireguard")
DATA_DIR = Path(__file__).parent.parent / "data"
CONFIGS_DIR = Path(__file__).parent.parent / "configs"
PEERS_FILE = DATA_DIR / "peers.json"
LOCK_FILE = DATA_DIR / ".peers.lock"
WG_CONF = WG_DIR / "wg0.conf"
SERVER_PUB = WG_DIR / "server.pub"

_NAME_RE = re.compile(r"^[a-z0-9]+$")


# ---------------------------------------------------------------------------
# Peer registry helpers
# ---------------------------------------------------------------------------

def _ensure_dirs():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
    LOCK_FILE.touch(exist_ok=True)


def read_peers() -> list:
    _ensure_dirs()
    with open(LOCK_FILE, "r") as lock:
        fcntl.flock(lock, fcntl.LOCK_SH)
        try:
            if PEERS_FILE.exists():
                with open(PEERS_FILE, "r") as f:
                    return json.load(f)
            return []
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def write_peers(peers: list):
    _ensure_dirs()
    tmp = PEERS_FILE.with_suffix(".tmp")
    with open(LOCK_FILE, "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            with open(tmp, "w") as f:
                json.dump(peers, f, indent=2)
            tmp.replace(PEERS_FILE)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _next_ip(peers: list) -> str:
    used = {p["vpn_ip"] for p in peers}
    for i in range(2, 255):
        candidate = f"10.8.0.{i}"
        if candidate not in used:
            return candidate
    console.print("[red]No available IPs in 10.8.0.0/24.[/red]")
    sys.exit(1)


def _get_wireguard_endpoint() -> str:
    from modules.endpoint import get_wireguard_endpoint

    return get_wireguard_endpoint()


def _require_root():
    if os.geteuid() != 0:
        console.print("[red]Error: this command must be run as root (use sudo).[/red]")
        sys.exit(1)


# ---------------------------------------------------------------------------
# WireGuard conf manipulation
# ---------------------------------------------------------------------------

def _append_peer_to_conf(name: str, pubkey: str, ip: str):
    block = f"\n# {name}\n[Peer]\nPublicKey = {pubkey}\nAllowedIPs = {ip}/32\n"
    content = WG_CONF.read_text()
    new_content = content + block
    tmp = WG_CONF.with_suffix(".tmp")
    old_umask = os.umask(0o177)
    try:
        tmp.write_text(new_content)
        tmp.chmod(0o600)
        tmp.rename(WG_CONF)
    finally:
        os.umask(old_umask)


def _remove_peer_from_conf(name: str, pubkey: str, ip: str):
    content = WG_CONF.read_text()
    block = f"\n# {name}\n[Peer]\nPublicKey = {pubkey}\nAllowedIPs = {ip}/32\n"
    if block in content:
        new_content = content.replace(block, "\n", 1)
    else:
        # Fallback: line-by-line removal matching by name
        new_content = _remove_block_by_name(content, name)

    tmp = WG_CONF.with_suffix(".tmp")
    old_umask = os.umask(0o177)
    try:
        tmp.write_text(new_content)
        tmp.chmod(0o600)
        tmp.rename(WG_CONF)
    finally:
        os.umask(old_umask)


def _remove_block_by_name(content: str, name: str) -> str:
    lines = content.splitlines(keepends=True)
    result = []
    i = 0
    while i < len(lines):
        stripped = lines[i].rstrip("\n\r")
        if stripped == f"# {name}":
            j = i + 1
            while j < len(lines) and lines[j].rstrip("\n\r") == "":
                j += 1
            if j < len(lines) and lines[j].rstrip("\n\r") == "[Peer]":
                k = j + 1
                while k < len(lines):
                    kl = lines[k].rstrip("\n\r")
                    if kl == "" or kl.startswith("#") or kl.startswith("["):
                        break
                    k += 1
                if k < len(lines) and lines[k].rstrip("\n\r") == "":
                    k += 1
                i = k
                continue
        result.append(lines[i])
        i += 1
    return "".join(result)


def _wg_reload():
    subprocess.run(
        ["bash", "-c", "wg syncconf wg0 <(wg-quick strip wg0)"],
        check=True
    )


# ---------------------------------------------------------------------------
# Handshake parsing
# ---------------------------------------------------------------------------

def _get_handshakes() -> dict:
    """Return {pubkey: last_handshake_epoch} from wg show wg0 dump."""
    try:
        result = subprocess.run(
            ["wg", "show", "wg0", "dump"],
            capture_output=True, text=True, check=True
        )
    except subprocess.CalledProcessError:
        return {}

    handshakes = {}
    lines = result.stdout.strip().splitlines()
    for line in lines[1:]:  # Skip interface line
        parts = line.split("\t")
        if len(parts) >= 5:
            pubkey = parts[0]
            try:
                ts = int(parts[4])
            except ValueError:
                ts = 0
            handshakes[pubkey] = ts
    return handshakes


def _format_handshake(epoch: int) -> str:
    if epoch == 0:
        return "never"
    now = int(time.time())
    delta = now - epoch
    if delta < 60:
        return f"{delta}s ago"
    if delta < 3600:
        return f"{delta // 60}m ago"
    if delta < 86400:
        return f"{delta // 3600}h ago"
    return f"{delta // 86400}d ago"


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def add_peer(name: str):
    _require_root()

    if not _NAME_RE.match(name):
        console.print(
            f"[red]Invalid peer name '{name}'. "
            "Use lowercase letters and digits only.[/red]"
        )
        sys.exit(1)

    peers = read_peers()
    if any(p["name"] == name for p in peers):
        console.print(f"[red]Peer '{name}' already exists.[/red]")
        sys.exit(1)

    vpn_ip = _next_ip(peers)
    console.print(f"[cyan]Assigning VPN IP {vpn_ip} to peer '{name}'…[/cyan]")

    # Generate peer keypair
    key_path = WG_DIR / f"{name}.key"
    pub_path = WG_DIR / f"{name}.pub"

    old_umask = os.umask(0o077)
    try:
        key_result = subprocess.run(["wg", "genkey"], capture_output=True, check=True)
        key_path.write_bytes(key_result.stdout)
        key_path.chmod(0o600)
        pub_result = subprocess.run(
            ["wg", "pubkey"], input=key_result.stdout,
            capture_output=True, check=True
        )
        pub_path.write_bytes(pub_result.stdout)
    finally:
        os.umask(old_umask)

    peer_privkey = key_path.read_text().strip()
    peer_pubkey = pub_path.read_text().strip()
    server_pubkey = SERVER_PUB.read_text().strip()
    public_ip = _get_wireguard_endpoint()

    # Update wg0.conf and reload
    _append_peer_to_conf(name, peer_pubkey, vpn_ip)
    try:
        _wg_reload()
    except subprocess.CalledProcessError:
        console.print("[yellow]⚠ Could not reload WireGuard live — changes saved to conf.[/yellow]")

    # Write client config
    CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
    client_conf = (
        f"[Interface]\n"
        f"PrivateKey = {peer_privkey}\n"
        f"Address = {vpn_ip}/24\n"
        f"DNS = 1.1.1.1\n"
        f"\n"
        f"[Peer]\n"
        f"PublicKey = {server_pubkey}\n"
        f"Endpoint = {public_ip}:51820\n"
        f"AllowedIPs = 10.8.0.0/24\n"
        f"PersistentKeepalive = 25\n"
    )
    conf_path = CONFIGS_DIR / f"{name}.conf"
    conf_path.write_text(client_conf)

    # Save peer record
    peers.append({
        "name": name,
        "vpn_ip": vpn_ip,
        "public_key": peer_pubkey,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    write_peers(peers)

    console.print(f"[green]✓ Peer '{name}' added.[/green]")
    console.print(f"  VPN IP:     [cyan]{vpn_ip}[/cyan]")
    console.print(f"  Config:     [cyan]{conf_path}[/cyan]")
    console.print(
        "  Share the config file or run [green]nitrox peer qr " + name + "[/green] to show a QR code."
    )
    console.print(
        "  Run [green]nitrox web[/green] to serve configs via the web UI."
    )


def remove_peer(name: str):
    _require_root()

    peers = read_peers()
    record = next((p for p in peers if p["name"] == name), None)
    if record is None:
        console.print(f"[red]Peer '{name}' not found.[/red]")
        sys.exit(1)

    if not click.confirm(f"Remove peer '{name}'?", default=False):
        console.print("[yellow]Aborted.[/yellow]")
        return

    _remove_peer_from_conf(name, record["public_key"], record["vpn_ip"])
    try:
        _wg_reload()
    except subprocess.CalledProcessError:
        console.print("[yellow]⚠ Could not reload WireGuard live — conf updated.[/yellow]")

    for path in [
        WG_DIR / f"{name}.key",
        WG_DIR / f"{name}.pub",
        CONFIGS_DIR / f"{name}.conf",
    ]:
        if path.exists():
            path.unlink()

    updated = [p for p in peers if p["name"] != name]
    write_peers(updated)

    console.print(f"[green]✓ Peer '{name}' removed.[/green]")


def list_peers():
    peers = read_peers()
    handshakes = _get_handshakes()

    table = Table(title="WireGuard Peers", show_lines=True)
    table.add_column("Name", style="bold cyan")
    table.add_column("VPN IP", style="green")
    table.add_column("Public Key", style="dim")
    table.add_column("Added", style="white")
    table.add_column("Last Handshake", style="yellow")

    for p in peers:
        pk = p["public_key"]
        pk_short = pk[:12] + "…" + pk[-4:] if len(pk) > 16 else pk

        ts = handshakes.get(p["public_key"], None)
        if ts is None:
            hs = "—"
        else:
            hs = _format_handshake(ts)

        added = p.get("created_at", "—")
        if "T" in added:
            added = added.split("T")[0]

        table.add_row(p["name"], p["vpn_ip"], pk_short, added, hs)

    if not peers:
        console.print("[yellow]No peers configured. Use 'nitrox peer add <name>'.[/yellow]")
        return

    console.print(table)


def show_qr(name: str):
    conf_path = CONFIGS_DIR / f"{name}.conf"
    if not conf_path.exists():
        console.print(
            f"[red]Config for peer '{name}' not found at {conf_path}.[/red]"
        )
        sys.exit(1)

    try:
        import qrcode
    except ImportError:
        console.print("[red]qrcode package not installed. Run: pip install qrcode[terminal][/red]")
        sys.exit(1)

    content = conf_path.read_text()
    qr = qrcode.QRCode()
    qr.add_data(content)
    qr.make(fit=True)

    console.print(f"\n[bold cyan]WireGuard config QR for '{name}':[/bold cyan]\n")
    qr.print_ascii(invert=True)
    console.print(
        "\n[green]Scan with the WireGuard mobile app to import.[/green]"
    )

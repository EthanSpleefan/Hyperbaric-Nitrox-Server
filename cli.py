#!/usr/bin/env python3
#!/home/nitrox/hyperbaric-nitrox-server/.venv/bin/python3
import sys
import click
from rich.console import Console

console = Console()


@click.group()
def nitrox():
    """Nitrox Subnautica Server + WireGuard management tool."""
    pass


@nitrox.command()
def setup():
    """Fully provision the server from scratch (idempotent)."""
    from modules.setup import run_setup
    try:
        run_setup()
    except KeyboardInterrupt:
        console.print("\n[yellow]Setup interrupted.[/yellow]")
        sys.exit(1)


@nitrox.group()
def peer():
    """Manage WireGuard VPN peers."""
    pass


@peer.command("add")
@click.argument("name")
def peer_add(name):
    """Add a new WireGuard peer by NAME."""
    from modules.wireguard import add_peer
    try:
        add_peer(name)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
        sys.exit(1)


@peer.command("remove")
@click.argument("name")
def peer_remove(name):
    """Remove a WireGuard peer by NAME."""
    from modules.wireguard import remove_peer
    try:
        remove_peer(name)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
        sys.exit(1)


@peer.command("list")
def peer_list():
    """List all WireGuard peers with live handshake status."""
    from modules.wireguard import list_peers
    try:
        list_peers()
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
        sys.exit(1)


@peer.command("qr")
@click.argument("name")
def peer_qr(name):
    """Print a QR code for peer NAME's WireGuard config."""
    from modules.wireguard import show_qr
    try:
        show_qr(name)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
        sys.exit(1)


@nitrox.command()
def status():
    """Show server and VPN status summary."""
    from modules.systemd import show_status
    try:
        show_status()
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
        sys.exit(1)


@nitrox.command()
def web():
    """Start the web UI for peer config distribution (LAN/VPN only)."""
    from modules.web import start_web
    try:
        start_web()
    except KeyboardInterrupt:
        console.print("\n[yellow]Web server stopped.[/yellow]")
        sys.exit(0)


if __name__ == "__main__":
    nitrox()

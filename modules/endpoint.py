"""WireGuard client endpoint (hostname or public IPv4) for peer configs."""

import json
import re
import subprocess
from pathlib import Path

import click
from rich.console import Console

console = Console()

DATA_DIR = Path(__file__).parent.parent / "data"
ENDPOINT_FILE = DATA_DIR / "endpoint.json"

_IPV4_RE = re.compile(
    r"^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}"
    r"(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$"
)
_HOSTNAME_RE = re.compile(
    r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$",
    re.IGNORECASE,
)


def _ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _is_ipv4(value: str) -> bool:
    return bool(_IPV4_RE.match(value.strip()))


def detect_public_ipv4() -> str:
    """Detect public IPv4 only (never prefers IPv6)."""
    urls = [
        "https://api4.ipify.org",
        "https://ipv4.icanhazip.com",
        "https://v4.ident.me",
    ]
    for url in urls:
        try:
            result = subprocess.run(
                ["curl", "-4", "-s", "--max-time", "5", url],
                capture_output=True,
                text=True,
                check=False,
            )
            candidate = result.stdout.strip()
            if _is_ipv4(candidate):
                return candidate
        except Exception:
            continue
    return "unknown"


def read_endpoint_config() -> dict | None:
    if not ENDPOINT_FILE.exists():
        return None
    try:
        data = json.loads(ENDPOINT_FILE.read_text())
        if isinstance(data, dict) and data.get("endpoint"):
            return data
        return None
    except Exception:
        return None


def save_endpoint_config(endpoint: str, source: str):
    _ensure_data_dir()
    payload = {"endpoint": endpoint.strip(), "source": source}
    tmp = ENDPOINT_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n")
    tmp.replace(ENDPOINT_FILE)


def get_wireguard_endpoint() -> str:
    """Return configured endpoint host, or auto-detect IPv4 if unset."""
    saved = read_endpoint_config()
    if saved:
        return saved["endpoint"]
    detected = detect_public_ipv4()
    if detected != "unknown":
        console.print(
            "[yellow]⚠ No WireGuard endpoint saved — using detected public IPv4. "
            "Re-run [green]nitrox setup[/green] to set a hostname or confirm the IP.[/yellow]"
        )
    return detected


def prompt_wireguard_endpoint(*, reconfigure: bool = False) -> str:
    """
    Ask whether to use a hostname (DDNS) or auto-detected public IPv4.
    Saves choice to data/endpoint.json and returns the endpoint host.
    """
    existing = read_endpoint_config()
    if existing and not reconfigure:
        keep = click.confirm(
            f"Keep WireGuard endpoint ({existing['endpoint']})?",
            default=True,
        )
        if keep:
            _ok_saved(existing["endpoint"], existing.get("source", "saved"))
            return existing["endpoint"]

    console.print(
        "\n[bold]WireGuard endpoint[/bold]\n"
        "Peer configs need an address friends use to reach your server "
        "(UDP 51820 on your router).\n"
    )
    mode = click.prompt(
        "Use a hostname (e.g. DDNS) or auto-detect public IPv4?",
        type=click.Choice(["hostname", "ip"], case_sensitive=False),
        default="ip",
        show_choices=True,
    ).lower()

    if mode == "hostname":
        while True:
            host = click.prompt(
                "Hostname (e.g. home.example.com)",
                type=str,
            ).strip().rstrip(".")
            if _HOSTNAME_RE.match(host):
                save_endpoint_config(host, "hostname")
                _ok_saved(host, "hostname")
                return host
            console.print(
                "[red]Invalid hostname. Use letters, digits, dots, and hyphens only.[/red]"
            )
    else:
        console.print("[cyan]Detecting public IPv4 (IPv6 is not used)…[/cyan]")
        ip = detect_public_ipv4()
        if ip == "unknown":
            console.print(
                "[yellow]⚠ Could not detect public IPv4 automatically.[/yellow]"
            )
            while True:
                ip = click.prompt("Enter your public IPv4 address", type=str).strip()
                if _is_ipv4(ip):
                    break
                console.print("[red]Enter a valid IPv4 address (e.g. 203.0.113.1).[/red]")
        else:
            console.print(f"[dim]Detected:[/dim] [cyan]{ip}[/cyan]")
            if not click.confirm("Use this IPv4 address?", default=True):
                while True:
                    ip = click.prompt("Enter your public IPv4 address", type=str).strip()
                    if _is_ipv4(ip):
                        break
                    console.print(
                        "[red]Enter a valid IPv4 address (e.g. 203.0.113.1).[/red]"
                    )
        save_endpoint_config(ip, "ipv4")
        _ok_saved(ip, "public IPv4")
        return ip


def _ok_saved(endpoint: str, label: str):
    console.print(f"[green]✓ WireGuard endpoint set to {endpoint} ({label})[/green]")

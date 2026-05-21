import os
import sys
import subprocess
from pathlib import Path

import click
import requests
from rich.console import Console

console = Console()

NITROX_DIR = "/opt/nitrox"
SUBNAUTICA_DIR = "/opt/subnautica"
WG_DIR = "/etc/wireguard"
SYSTEMD_DIR = "/etc/systemd/system"
STEAMCMD = "/usr/games/steamcmd"


def _step(msg):
    console.print(f"\n[bold cyan]▶ {msg}[/bold cyan]")


def _ok(msg):
    console.print(f"[green]✓ {msg}[/green]")


def _warn(msg):
    console.print(f"[yellow]⚠ {msg}[/yellow]")


def _run(cmd, check=True, **kwargs):
    return subprocess.run(cmd, check=check, **kwargs)


def _steam_login_banner():
    console.print(
        "\n[bold yellow]"
        "╔══════════════════════════════════════════════════╗\n"
        "║  STEAM LOGIN REQUIRED                            ║\n"
        "║                                                  ║\n"
        "║  SteamCMD will now prompt for your Steam         ║\n"
        "║  username. Enter it, then your password, and     ║\n"
        "║  any Steam Guard code when asked.                ║\n"
        "║                                                  ║\n"
        "║  The account must own Subnautica (App 264710).   ║\n"
        "╚══════════════════════════════════════════════════╝"
        "[/bold yellow]\n"
    )


def _steamcmd_install(install_dir):
    _steam_login_banner()
    steam_user = click.prompt("Steam username")
    _run([
        STEAMCMD,
        "+force_install_dir", install_dir,
        "+@sSteamCmdForcePlatformType", "linux",
        "+login", steam_user,
        "+app_update", "264710", "validate",
        "+quit",
    ])


def run_setup():
    # Step 1: Must be root
    if os.geteuid() != 0:
        console.print("[red]Error: nitrox setup must be run as root (use sudo).[/red]")
        sys.exit(1)

    console.print("\n[bold]Nitrox Server Setup[/bold]")
    console.print("=" * 52)
    _ok("Running as root")

    # Step 2: Base packages
    _step("Installing base packages (wireguard, unzip, curl)…")
    _run(["apt-get", "update", "-y"])
    _run(["apt-get", "install", "-y", "wireguard", "wireguard-tools", "unzip", "curl"])
    _ok("Base packages installed")

    # Step 3: .NET 9 runtime
    _step("Installing .NET 9 runtime…")
    result = _run(["apt-get", "install", "-y", "dotnet-runtime-9.0"], check=False)
    if result.returncode != 0:
        _warn(".NET 9 not in default repos — adding Microsoft package feed…")
        ubuntu_ver = subprocess.check_output(
            ["lsb_release", "-rs"], text=True
        ).strip()
        deb_url = (
            f"https://packages.microsoft.com/config/ubuntu"
            f"/{ubuntu_ver}/packages-microsoft-prod.deb"
        )
        _run(["curl", "-fsSL", deb_url, "-o", "/tmp/packages-microsoft-prod.deb"])
        _run(["dpkg", "-i", "/tmp/packages-microsoft-prod.deb"])
        _run(["apt-get", "update", "-y"])
        _run(["apt-get", "install", "-y", "dotnet-runtime-9.0"])
    _ok(".NET 9 runtime installed")

    # Step 4: SteamCMD
    _step("Installing SteamCMD…")
    _run(["add-apt-repository", "multiverse", "-y"], check=False)
    _run(["dpkg", "--add-architecture", "i386"])
    _run(
        ["bash", "-c",
         'echo "steam steam/question select I AGREE" | debconf-set-selections']
    )
    _run(
        ["bash", "-c",
         'echo "steam steam/license note " | debconf-set-selections']
    )
    _run(["apt-get", "update", "-y"])
    _run(["apt-get", "install", "-y", "steamcmd"])
    _ok("SteamCMD installed")

    # Step 5: Subnautica game files (auto-detect existing installs)
    from modules.detect import detect_subnautica, detect_nitrox_saves

    _step("Auto-detecting Subnautica game files…")
    found = detect_subnautica(SUBNAUTICA_DIR)
    subnautica_dir = SUBNAUTICA_DIR
    if found:
        subnautica_dir = str(found[0])
        _ok(f"Detected Subnautica install at {subnautica_dir}")
        for extra in found[1:]:
            _warn(f"Also found: {extra} (ignored)")
        choice = click.prompt(
            "Check for update (recommended) or skip?",
            type=click.Choice(["update", "skip"], case_sensitive=False),
            default="update",
            show_choices=True,
        ).lower()
        if choice == "update":
            _step("Validating / updating Subnautica via SteamCMD…")
            _steamcmd_install(subnautica_dir)
            _ok("Subnautica updated / validated")
        else:
            _warn("Skipping update; using existing game files as-is.")
    else:
        _warn("No existing Subnautica install detected.")
        Path(SUBNAUTICA_DIR).mkdir(parents=True, exist_ok=True)
        _step("Downloading Subnautica game files via SteamCMD…")
        _steamcmd_install(SUBNAUTICA_DIR)
        _ok("Subnautica download complete")

    # Step 6: Download latest Nitrox server + create system user
    _step("Setting up nitrox system user…")
    if _run(["id", "nitrox"], check=False, capture_output=True).returncode != 0:
        _run(["useradd", "-r", "-s", "/bin/false", "nitrox"])
        _ok("Created nitrox system user")
    else:
        _ok("nitrox user already exists")

    nitrox_path = Path(NITROX_DIR)
    nitrox_binary = nitrox_path / "Nitrox.Server.Subnautica"
    if nitrox_binary.exists():
        _warn("Nitrox server binary already present; skipping download.")
    else:
        _step("Downloading latest Nitrox server release from GitHub…")
        resp = requests.get(
            "https://api.github.com/repos/SubnauticaNitrox/Nitrox/releases/latest",
            timeout=30,
        )
        resp.raise_for_status()
        release = resp.json()

        asset = next(
            (
                a for a in release.get("assets", [])
                if "linux" in a["name"].lower()
                and "x64" in a["name"].lower()
                and a["name"].lower().endswith(".zip")
            ),
            None,
        )
        if asset is None:
            console.print("[red]No Linux x64 Nitrox release asset found.[/red]")
            sys.exit(1)

        console.print(f"[cyan]Downloading {asset['name']}…[/cyan]")
        nitrox_path.mkdir(parents=True, exist_ok=True)
        zip_tmp = "/tmp/nitrox-release.zip"
        _run(["curl", "-L", "-o", zip_tmp, asset["browser_download_url"]])
        _run(["unzip", "-o", zip_tmp, "-d", NITROX_DIR])
        os.unlink(zip_tmp)
        _ok("Nitrox server downloaded and extracted")

    _run(["chown", "-R", "nitrox:nitrox", NITROX_DIR])
    _run(["chown", "-R", "nitrox:nitrox", subnautica_dir], check=False)
    _ok("Ownership set to nitrox user")

    # Detect existing Nitrox save files
    _step("Scanning for existing Nitrox save files…")
    saves = detect_nitrox_saves()
    if saves:
        _ok(f"Found {len(saves)} existing Nitrox save(s):")
        for name, path in saves:
            console.print(f"    [cyan]{name}[/cyan]  ({path})")
        console.print(
            "[dim]Existing saves are preserved; the server reuses them on start.[/dim]"
        )
    else:
        _warn("No existing Nitrox saves found — a new world is created on first start.")

    # Step 7: WireGuard server keys
    _step("Generating WireGuard server keys…")
    wg_dir = Path(WG_DIR)
    wg_dir.mkdir(mode=0o700, exist_ok=True)
    server_key_path = wg_dir / "server.key"
    server_pub_path = wg_dir / "server.pub"

    if not server_key_path.exists():
        saved_umask = os.umask(0o077)
        try:
            key_result = subprocess.run(["wg", "genkey"], capture_output=True, check=True)
            server_key_path.write_bytes(key_result.stdout)
            server_key_path.chmod(0o600)
            pub_result = subprocess.run(
                ["wg", "pubkey"], input=key_result.stdout,
                capture_output=True, check=True
            )
            server_pub_path.write_bytes(pub_result.stdout)
        finally:
            os.umask(saved_umask)
        _ok("WireGuard server keys generated")
    else:
        _ok("WireGuard server keys already exist")

    server_key = server_key_path.read_text().strip()
    server_pub = server_pub_path.read_text().strip()

    # Step 8: wg0.conf
    _step("Writing WireGuard server config…")
    wg_conf_path = wg_dir / "wg0.conf"
    if not wg_conf_path.exists():
        wg_conf = (
            f"[Interface]\n"
            f"Address = 10.8.0.1/24\n"
            f"ListenPort = 51820\n"
            f"PrivateKey = {server_key}\n"
        )
        _atomic_write(wg_conf_path, wg_conf, mode=0o600)
        _ok("WireGuard config written")
    else:
        _ok("WireGuard config already exists")

    # Step 9: WireGuard endpoint for peer configs
    from modules.endpoint import prompt_wireguard_endpoint

    _step("WireGuard endpoint for peer configs…")
    wg_endpoint = prompt_wireguard_endpoint()

    # Step 10: Enable WireGuard
    _step("Enabling and starting WireGuard (wg-quick@wg0)…")
    _run(["systemctl", "enable", "--now", "wg-quick@wg0"])
    _ok("WireGuard enabled and started")

    # Step 11: Nitrox systemd service
    _step("Writing Nitrox systemd service file…")
    service_path = Path(SYSTEMD_DIR) / "nitrox.service"
    service_content = (
        "[Unit]\n"
        "Description=Nitrox Subnautica Dedicated Server\n"
        "After=network.target\n"
        "\n"
        "[Service]\n"
        "User=nitrox\n"
        "WorkingDirectory=/opt/nitrox\n"
        "ExecStart=/opt/nitrox/Nitrox.Server.Subnautica"
        f" --subnautica-path {subnautica_dir}\n"
        "Restart=on-failure\n"
        "RestartSec=10\n"
        "\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )
    _atomic_write(service_path, service_content)
    _ok("Nitrox service file written")

    # Step 12: Reload systemd and enable nitrox
    _step("Enabling Nitrox service…")
    _run(["systemctl", "daemon-reload"])
    _run(["systemctl", "enable", "nitrox"])
    _ok("Nitrox service enabled (not started — run: systemctl start nitrox)")

    # Summary
    wg_status = subprocess.run(
        ["systemctl", "is-active", "wg-quick@wg0"],
        capture_output=True, text=True
    ).stdout.strip()

    console.print(
        f"\n[bold green]"
        f"╔══════════════════════════════════════════════════╗\n"
        f"║               Setup Complete!                    ║\n"
        f"╚══════════════════════════════════════════════════╝"
        f"[/bold green]"
    )
    console.print(f"  [cyan]WireGuard status:[/cyan] {wg_status}")
    console.print(f"  [cyan]Server public key:[/cyan] {server_pub}")
    console.print(f"  [cyan]WireGuard endpoint:[/cyan] {wg_endpoint}:51820")
    console.print("\n[bold]Next steps:[/bold]")
    console.print("  Start the game server:  [green]systemctl start nitrox[/green]")
    console.print("  Add VPN peers:          [green]nitrox peer add <name>[/green]")
    console.print("  Share peer configs:     [green]nitrox web[/green]")
    console.print(
        "  Friends connect to:     [green]10.8.0.1:11000[/green] (after joining VPN)"
    )
    console.print("\n[yellow]Ports to forward on your router:[/yellow]")
    console.print("  UDP 51820  → WireGuard")
    console.print("  UDP 11000  → Nitrox (only if not using VPN-only access)")


def _atomic_write(path: Path, content: str, mode: int = 0o644):
    tmp = path.with_suffix(".tmp")
    saved_umask = os.umask(0o177 if mode == 0o600 else 0o022)
    try:
        tmp.write_text(content)
        tmp.chmod(mode)
        tmp.rename(path)
    finally:
        os.umask(saved_umask)



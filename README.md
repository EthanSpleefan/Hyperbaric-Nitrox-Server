# Nitrox Server CLI Tool

Automates the full setup and management of a [Nitrox](https://nitrox.rux.gg/) Subnautica dedicated server on Ubuntu 22.04/24.04, with integrated WireGuard VPN peer management and a local web UI for distributing client configs.

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Ubuntu 22.04 or 24.04 | Tested on both |
| `sudo` / root access | All management commands require root |
| Steam account | Must own **Subnautica** (App ID 264710) |
| Public IPv4 address | For WireGuard endpoint |

### Ports to forward on your router

| Port | Protocol | Purpose |
|------|----------|---------|
| 51820 | UDP | WireGuard VPN |
| 11000 | UDP | Nitrox game server (only if not using VPN-only access) |

---

## Installation

```bash
git clone https://github.com/ethanspleefan/hyperbaric-nitrox-server.git
cd hyperbaric-nitrox-server
sudo bash install.sh
```

`install.sh` will:
- Install Python dependencies (`pip install -r requirements.txt`)
- Make `cli.py` executable
- Symlink it to `/usr/local/bin/nitrox`
- Create `data/` and `configs/` directories

---

## Quick Start

```bash
sudo nitrox setup        # Full server provisioning (idempotent)
sudo systemctl start nitrox
sudo nitrox peer add hamish
nitrox web               # Start web UI for config distribution
```

---

## Commands

### `nitrox setup`

Fully provisions the server from scratch. Safe to re-run (idempotent).

Steps performed:
1. Installs `wireguard`, `wireguard-tools`, `unzip`, `curl`
2. Installs .NET 9 runtime (adds Microsoft package feed if needed)
3. Installs SteamCMD
4. Downloads Subnautica game files (prompts for Steam login interactively)
5. Downloads the latest Nitrox server release from GitHub
6. Generates WireGuard server keys
7. Writes `/etc/wireguard/wg0.conf`
8. Enables and starts `wg-quick@wg0`
9. Writes and enables the `nitrox.service` systemd unit

```bash
sudo nitrox setup
```

---

### `nitrox peer add <name>`

Adds a new WireGuard peer. `<name>` must be lowercase alphanumeric (e.g. `hamish`).

- Assigns the next available IP in `10.8.0.0/24` (starting from `10.8.0.2`)
- Generates a WireGuard keypair
- Appends the peer to `/etc/wireguard/wg0.conf` and reloads live
- Writes a ready-to-import client config to `configs/<name>.conf`
- Saves the peer record to `data/peers.json`

```bash
sudo nitrox peer add hamish
sudo nitrox peer add rupert
```

---

### `nitrox peer remove <name>`

Removes a peer (prompts for confirmation).

- Removes the `[Peer]` block from `wg0.conf` and reloads WireGuard
- Deletes key files and `configs/<name>.conf`
- Removes the entry from `data/peers.json`

```bash
sudo nitrox peer remove hamish
```

---

### `nitrox peer list`

Prints a formatted table of all peers with live handshake status (fetched from `wg show wg0 dump`).

```
┌──────────┬────────────┬─────────────────┬────────────┬──────────────┐
│ Name     │ VPN IP     │ Public Key       │ Added      │ Last Handshake│
├──────────┼────────────┼─────────────────┼────────────┼──────────────┤
│ hamish   │ 10.8.0.2   │ abc123xyz…ef12  │ 2026-05-20 │ 2m ago       │
│ rupert   │ 10.8.0.3   │ def456uvw…gh34  │ 2026-05-20 │ never        │
└──────────┴────────────┴─────────────────┴────────────┴──────────────┘
```

```bash
nitrox peer list
```

---

### `nitrox peer qr <name>`

Prints a QR code for the peer's WireGuard config to the terminal, ready to scan with the WireGuard mobile app.

```bash
nitrox peer qr hamish
```

---

### `nitrox status`

Shows a status summary:

- WireGuard service status
- Nitrox service status and uptime
- Public IP
- Peer count and how many have an active handshake (≤3 minutes)
- Per-peer handshake table

```bash
nitrox status
```

---

### `nitrox web`

Starts a Flask web server on `http://0.0.0.0:5000`. Provides a dark-themed admin panel listing all peers with download buttons for their `.conf` files.

**This has no authentication — only use on LAN or VPN. Never expose port 5000 to the internet.**

```bash
nitrox web
```

---

## Sharing Peer Configs

Friends need a WireGuard config to connect. Two options:

**Option A — Web UI (easiest)**

1. Run `nitrox web` on the server
2. Have friends open `http://<server-lan-ip>:5000` on your LAN (or `http://10.8.0.1:5000` from within the VPN)
3. They click the download button for their name and import the `.conf` into the WireGuard app

**Option B — QR code**

```bash
nitrox peer qr hamish
```

Show your friend the terminal QR code to scan directly with the WireGuard mobile app.

**Option C — File transfer**

```bash
scp configs/hamish.conf hamish@192.168.1.x:~/hamish.conf
```

---

## Connecting to the Game

Once a friend has their WireGuard config imported and the tunnel active:

1. Open Subnautica
2. In the Nitrox multiplayer menu, connect to: **`10.8.0.1:11000`**

That's it — they're playing over an encrypted VPN tunnel.

---

## File Layout

```
nitrox-tool/
├── cli.py               Entry point (symlinked to /usr/local/bin/nitrox)
├── modules/
│   ├── setup.py         Server provisioning
│   ├── wireguard.py     Peer management
│   ├── systemd.py       Service status
│   └── web.py           Flask web UI
├── templates/
│   └── index.html       Web UI template
├── data/
│   └── peers.json       Peer registry (created at runtime)
├── configs/             Generated WireGuard .conf files (created at runtime)
├── requirements.txt
├── install.sh
└── README.md
```

---

## Troubleshooting

**WireGuard won't start**
```bash
systemctl status wg-quick@wg0
journalctl -xe -u wg-quick@wg0
```

**Nitrox won't start**
```bash
systemctl status nitrox
journalctl -xe -u nitrox
```

**Peer can't handshake**
- Confirm UDP 51820 is forwarded on your router to the server's LAN IP
- Check the peer imported the correct `.conf` and the tunnel is active
- Run `wg show` on the server to see raw peer state

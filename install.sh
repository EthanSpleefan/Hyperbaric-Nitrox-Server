#!/usr/bin/env bash
set -euo pipefail

apt install pip
sudo apt install -y python3-venv python3-full

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Installing Python dependencies…"
python3 -m venv "$SCRIPT_DIR/.venv"
"$SCRIPT_DIR/.venv/bin/pip" install -r "$SCRIPT_DIR/requirements.txt"

echo "==> Making cli.py executable…"
chmod +x "$SCRIPT_DIR/cli.py"

echo "==> Creating symlink at /usr/local/bin/nitrox…"
ln -sf "$SCRIPT_DIR/.venv/bin/python3" /usr/local/bin/nitrox-python
ln -sf "$SCRIPT_DIR/cli.py" /usr/local/bin/nitrox

echo "==> Creating data/ and configs/ directories…"
mkdir -p "$SCRIPT_DIR/data"
mkdir -p "$SCRIPT_DIR/configs"
chmod 750 "$SCRIPT_DIR/data"
chmod 750 "$SCRIPT_DIR/configs"

echo ""
echo "nitrox command is now available. Run 'nitrox setup' to begin."

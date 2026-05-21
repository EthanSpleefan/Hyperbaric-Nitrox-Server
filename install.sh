#!/usr/bin/env bash
set -euo pipefail

apt install pip

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Installing Python dependencies…"
pip install -r "$SCRIPT_DIR/requirements.txt" --break-system-packages

echo "==> Making cli.py executable…"
chmod +x "$SCRIPT_DIR/cli.py"

echo "==> Creating symlink at /usr/local/bin/nitrox…"
ln -sf "$SCRIPT_DIR/cli.py" /usr/local/bin/nitrox

echo "==> Creating data/ and configs/ directories…"
mkdir -p "$SCRIPT_DIR/data"
mkdir -p "$SCRIPT_DIR/configs"
chmod 750 "$SCRIPT_DIR/data"
chmod 750 "$SCRIPT_DIR/configs"

echo ""
echo "nitrox command is now available. Run 'nitrox setup' to begin."

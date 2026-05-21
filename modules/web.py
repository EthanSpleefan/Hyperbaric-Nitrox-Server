import json
import os
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, send_file
from rich.console import Console

console = Console()

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
CONFIGS_DIR = BASE_DIR / "configs"
PEERS_FILE = DATA_DIR / "peers.json"


def _load_peers() -> list:
    try:
        return json.loads(PEERS_FILE.read_text()) if PEERS_FILE.exists() else []
    except Exception:
        return []


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=str(BASE_DIR / "templates"),
    )

    @app.route("/")
    def index():
        peers = _load_peers()
        return render_template("index.html", peers=peers)

    @app.route("/download/<name>")
    def download(name: str):
        if not name.replace("-", "").replace("_", "").isalnum():
            abort(400)
        conf_path = CONFIGS_DIR / f"{name}.conf"
        if not conf_path.exists():
            abort(404)
        return send_file(
            str(conf_path),
            as_attachment=True,
            download_name=f"{name}.conf",
            mimetype="text/plain",
        )

    @app.route("/api/status")
    def api_status():
        from modules.systemd import get_status_dict

        return jsonify(get_status_dict())

    @app.route("/api/server/<action>", methods=["POST"])
    def api_server_control(action: str):
        if action not in ("start", "stop"):
            abort(404)
        if os.geteuid() != 0:
            return jsonify({
                "ok": False,
                "error": "Server controls require root.",
                "hint": "Run: sudo nitrox web",
            }), 403

        from modules.systemd import control_nitrox

        result = control_nitrox(action)
        code = 200 if result.get("ok") else 500
        return jsonify(result), code

    return app


def start_web():
    root_note = ""
    if os.geteuid() != 0:
        root_note = (
            "\n[yellow]Note: Running without root — peer downloads work, "
            "but server start/stop controls need [green]sudo nitrox web[/green].[/yellow]\n"
        )

    console.print(
        "\n[bold yellow]"
        "⚠  WARNING: The web UI has no authentication.\n"
        "   Only expose it on your LAN or WireGuard VPN interface.\n"
        "   Do NOT forward port 5000 to the internet."
        "[/bold yellow]"
        f"{root_note}"
    )
    console.print("[cyan]Starting web UI on http://0.0.0.0:5000[/cyan]")
    console.print("Press Ctrl+C to stop.\n")

    app = create_app()
    app.run(host="0.0.0.0", port=5000, debug=False)

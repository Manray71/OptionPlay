#!/usr/bin/env python3
"""
OptionPlay Claude Desktop Setup Script
=======================================

Automatische Integration von OptionPlay mit Claude Desktop.

Verwendung:
    python3 scripts/setup_claude.py

Was dieses Skript macht:
1. Prüft Python-Version und Abhängigkeiten
2. Erstellt/aktualisiert claude_desktop_config.json
3. Lädt API-Key aus .env oder fragt danach
4. Validiert die Installation
"""

import json
import os
import sys
import subprocess
from pathlib import Path


def get_project_root() -> Path:
    """Ermittle das Projekt-Root-Verzeichnis."""
    return Path(__file__).parent.parent.resolve()


def get_claude_config_path() -> Path:
    """Ermittle den Pfad zur Claude Desktop Konfiguration."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    elif sys.platform == "win32":
        return Path(os.environ["APPDATA"]) / "Claude" / "claude_desktop_config.json"
    else:
        return Path.home() / ".config" / "claude" / "claude_desktop_config.json"


def find_python() -> str:
    """Finde den besten Python-Interpreter."""
    candidates = [
        "/opt/homebrew/bin/python3.12",
        "/opt/homebrew/bin/python3.11",
        "/usr/local/bin/python3.12",
        "/usr/local/bin/python3.11",
        sys.executable,
    ]

    for python in candidates:
        if os.path.exists(python):
            try:
                result = subprocess.run(
                    [python, "--version"],
                    capture_output=True,
                    text=True
                )
                version = result.stdout.strip()
                print(f"  Gefunden: {python} ({version})")
                return python
            except Exception:
                continue

    return sys.executable


def load_env_file(project_root: Path) -> dict:
    """Lade Variablen aus .env Datei."""
    env_file = project_root / ".env"
    env_vars = {}

    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    env_vars[key.strip()] = value.strip().strip('"').strip("'")

    return env_vars


def check_dependencies(python: str, project_root: Path) -> bool:
    """Prüfe ob alle Abhängigkeiten installiert sind."""
    print("\n2. Prüfe Abhängigkeiten...")

    result = subprocess.run(
        [python, "-c", "import mcp; import fastmcp; import aiohttp; import numpy"],
        capture_output=True,
        cwd=project_root
    )

    if result.returncode != 0:
        print("  ⚠️  Abhängigkeiten fehlen. Installiere...")
        install_result = subprocess.run(
            [python, "-m", "pip", "install", "-e", "."],
            cwd=project_root
        )
        return install_result.returncode == 0

    print("  ✅ Alle Abhängigkeiten installiert")
    return True


def create_config(project_root: Path, python: str, api_key: str) -> dict:
    """Erstelle die MCP-Server Konfiguration."""
    return {
        "mcpServers": {
            "optionplay": {
                "command": python,
                "args": ["-m", "src.mcp_main"],
                "cwd": str(project_root),
                "env": {
                    "PYTHONPATH": str(project_root),
                    "MARKETDATA_API_KEY": api_key
                }
            }
        }
    }


def merge_config(existing: dict, new_config: dict) -> dict:
    """Merge neue Konfiguration in bestehende."""
    if "mcpServers" not in existing:
        existing["mcpServers"] = {}

    existing["mcpServers"]["optionplay"] = new_config["mcpServers"]["optionplay"]
    return existing


def main():
    print("=" * 60)
    print("OptionPlay Claude Desktop Setup")
    print("=" * 60)

    project_root = get_project_root()
    print(f"\nProjekt: {project_root}")

    # 1. Python finden
    print("\n1. Suche Python-Interpreter...")
    python = find_python()

    # 2. Abhängigkeiten prüfen
    if not check_dependencies(python, project_root):
        print("  ❌ Konnte Abhängigkeiten nicht installieren")
        sys.exit(1)

    # 3. API-Key laden
    print("\n3. Lade API-Konfiguration...")
    env_vars = load_env_file(project_root)
    api_key = env_vars.get("MARKETDATA_API_KEY", "")

    if not api_key:
        print("  ⚠️  Kein MARKETDATA_API_KEY in .env gefunden")
        api_key = input("  Bitte API-Key eingeben (oder Enter zum Überspringen): ").strip()

        if api_key:
            # Speichere in .env
            env_file = project_root / ".env"
            with open(env_file, "a") as f:
                f.write(f"\nMARKETDATA_API_KEY={api_key}\n")
            print(f"  ✅ API-Key in {env_file} gespeichert")
    else:
        print(f"  ✅ API-Key gefunden ({api_key[:8]}...)")

    # 4. Claude Desktop Config erstellen
    print("\n4. Konfiguriere Claude Desktop...")
    config_path = get_claude_config_path()

    # Erstelle Verzeichnis falls nötig
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # Lade existierende Config oder erstelle neue
    existing_config = {}
    if config_path.exists():
        try:
            with open(config_path) as f:
                existing_config = json.load(f)
            print(f"  📄 Existierende Config gefunden")
        except json.JSONDecodeError:
            print(f"  ⚠️  Ungültige Config, wird überschrieben")

    # Erstelle neue Config
    new_config = create_config(project_root, python, api_key)
    final_config = merge_config(existing_config, new_config)

    # Speichere
    with open(config_path, "w") as f:
        json.dump(final_config, f, indent=2)

    print(f"  ✅ Config gespeichert: {config_path}")

    # 5. Auch im Projekt speichern
    project_config = project_root / "claude_desktop_config.json"
    with open(project_config, "w") as f:
        json.dump(new_config, f, indent=2)
    print(f"  ✅ Backup gespeichert: {project_config}")

    # 6. Validierung
    print("\n5. Validiere Installation...")
    result = subprocess.run(
        [python, "-c", "from src.mcp_main import app; print('MCP Server OK')"],
        capture_output=True,
        text=True,
        cwd=project_root,
        env={**os.environ, "PYTHONPATH": str(project_root)}
    )

    if result.returncode == 0:
        print("  ✅ MCP Server kann geladen werden")
    else:
        print(f"  ❌ Fehler: {result.stderr}")
        sys.exit(1)

    # Erfolg
    print("\n" + "=" * 60)
    print("✅ Setup erfolgreich!")
    print("=" * 60)
    print("""
Nächste Schritte:

1. Claude Desktop neu starten

2. In Claude Desktop testen:
   - "Wie ist der aktuelle VIX?"
   - "Scanne nach Pullback-Kandidaten"
   - "Analysiere AAPL"

Verfügbare Tools:
   - vix, scan, quote, options, earnings
   - analyze, recommend_strikes
   - scan_multi, scan_bounce, scan_breakout
   - earnings_prefilter, portfolio, health
""")


if __name__ == "__main__":
    main()

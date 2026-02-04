#!/bin/bash
#
# OptionPlay Training Dashboard starten
# ======================================
#
# Startet das Streamlit Dashboard für Live-Monitoring.
#
# Optionen:
#   --background    Im Hintergrund starten
#   --port PORT     Alternativer Port (default: 8501)
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

PORT=8501
BACKGROUND=false

# Args parsen
while [[ $# -gt 0 ]]; do
    case $1 in
        --background)
            BACKGROUND=true
            shift
            ;;
        --port)
            PORT="$2"
            shift 2
            ;;
        *)
            shift
            ;;
    esac
done

cd "$PROJECT_DIR"
source venv/bin/activate

# IP-Adresse für Netzwerkzugriff
IP=$(ipconfig getifaddr en0 2>/dev/null || echo "localhost")

echo ""
echo "╔════════════════════════════════════════════════════════════╗"
echo "║           OPTIONPLAY TRAINING DASHBOARD                    ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""
echo "  🌐 Lokal:    http://localhost:$PORT"
echo "  🌐 Netzwerk: http://$IP:$PORT"
echo ""

if [ "$BACKGROUND" = true ]; then
    echo "  ▶️  Starte im Hintergrund..."
    nohup streamlit run scripts/training_dashboard.py \
        --server.port $PORT \
        --server.address 0.0.0.0 \
        --server.headless true \
        > ~/.optionplay/dashboard.log 2>&1 &

    echo "  PID: $!"
    echo "  Log: ~/.optionplay/dashboard.log"
    echo ""
    echo "  Stoppen mit: pkill -f 'streamlit.*training_dashboard'"
else
    echo "  Starte Dashboard... (Ctrl+C zum Beenden)"
    echo ""
    streamlit run scripts/training_dashboard.py \
        --server.port $PORT \
        --server.address 0.0.0.0
fi

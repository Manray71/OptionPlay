#!/bin/bash
# ============================================================
# OptionPlay Refactoring Setup
# Erstellt Tag + Branch für sicheres Refactoring
# ============================================================

set -e  # Bei Fehler sofort stoppen

REPO_DIR="$HOME/OptionPlay"
TAG_NAME="v1.0-pre-refactoring"
BRANCH_NAME="refactoring/recursive-strategy"

echo "================================================"
echo "  OptionPlay Refactoring Setup"
echo "================================================"
echo ""

# 1. Ins Repo wechseln
cd "$REPO_DIR" || { echo "❌ Verzeichnis $REPO_DIR nicht gefunden!"; exit 1; }
echo "📁 Arbeitsverzeichnis: $(pwd)"
echo ""

# 2. Prüfen ob uncommitted changes existieren
if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "⚠️  Es gibt uncommitted changes:"
    git status --short
    echo ""
    read -p "Soll ich alles committen? (j/n): " answer
    if [[ "$answer" == "j" ]]; then
        git add -A
        git commit -m "chore: save working state before refactoring"
        echo "✅ Changes committed"
    else
        echo "❌ Bitte erst manuell committen. Abbruch."
        exit 1
    fi
else
    echo "✅ Working tree ist clean"
fi
echo ""

# 3. Aktuellen Branch prüfen
CURRENT_BRANCH=$(git branch --show-current)
echo "📌 Aktueller Branch: $CURRENT_BRANCH"
echo ""

# 4. Auf GitHub pushen
echo "🔄 Pushe aktuellen Stand auf GitHub..."
git push origin "$CURRENT_BRANCH"
echo "✅ Push erfolgreich"
echo ""

# 5. Tag erstellen
if git tag -l "$TAG_NAME" | grep -q "$TAG_NAME"; then
    echo "⚠️  Tag '$TAG_NAME' existiert bereits - überspringe"
else
    git tag -a "$TAG_NAME" -m "Working state before recursive strategy refactoring"
    echo "✅ Tag '$TAG_NAME' erstellt"
fi
git push origin --tags
echo "✅ Tags auf GitHub gepusht"
echo ""

# 6. Refactoring-Branch erstellen
if git branch --list "$BRANCH_NAME" | grep -q "$BRANCH_NAME"; then
    echo "⚠️  Branch '$BRANCH_NAME' existiert bereits"
    read -p "Dorthin wechseln? (j/n): " answer
    if [[ "$answer" == "j" ]]; then
        git checkout "$BRANCH_NAME"
    fi
else
    git checkout -b "$BRANCH_NAME"
    echo "✅ Branch '$BRANCH_NAME' erstellt und ausgecheckt"
fi
echo ""

# 7. Branch auf GitHub pushen
git push -u origin "$BRANCH_NAME"
echo "✅ Branch auf GitHub gepusht"
echo ""

# 8. Zusammenfassung
echo "================================================"
echo "  ✅ Setup abgeschlossen!"
echo "================================================"
echo ""
echo "  Sicherungs-Tag:    $TAG_NAME"
echo "  Refactoring-Branch: $BRANCH_NAME"
echo "  Main-Branch:        $CURRENT_BRANCH (unverändert)"
echo ""
echo "  Nützliche Befehle:"
echo "  ─────────────────────────────────────────────"
echo "  git checkout $CURRENT_BRANCH          # Zurück zum stabilen Stand"
echo "  git checkout $BRANCH_NAME   # Weiter refactoren"
echo "  git diff $CURRENT_BRANCH              # Alle Änderungen sehen"
echo "  git log --oneline $CURRENT_BRANCH..$BRANCH_NAME  # Neue Commits"
echo "  git checkout $TAG_NAME       # Notfall: exakter Snapshot"
echo ""
echo "  Viel Erfolg beim Refactoring! 🚀"

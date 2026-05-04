#!/bin/bash
# ratethat.tennis — Generate Match Intelligence
# Fetches upcoming matches without intelligence text, generates journalistic
# previews via Claude, and stores them back to the database.

cd "$(dirname "$0")"

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║     ratethat.tennis — Match Intelligence         ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# Load existing saved settings if present
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs 2>/dev/null)
fi

# If no Anthropic API key saved yet, ask for it once and save it
if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "  First-time setup: I need your Anthropic API key."
    echo ""
    echo "  To get one:"
    echo "  1. Go to https://console.anthropic.com"
    echo "  2. Sign in (use your Google or email account)"
    echo "  3. Click 'API Keys' in the left menu → 'Create Key'"
    echo "  4. Copy the key (starts with sk-ant-...)"
    echo ""
    read -p "  Paste your Anthropic API key here and press Enter: " ENTERED_KEY
    echo ""

    if [ -z "$ENTERED_KEY" ]; then
        echo "❌  No key entered. Please run this script again when you have your key."
        echo ""
        read -p "Press Enter to close..."
        exit 1
    fi

    # Save it so you never have to enter it again
    echo "ANTHROPIC_API_KEY=$ENTERED_KEY" >> .env
    export ANTHROPIC_API_KEY="$ENTERED_KEY"
    echo "  ✓  Key saved — you won't be asked again."
    echo ""
fi

python3 -m pipeline.intelligence

echo ""
read -p "Press Enter to close..."

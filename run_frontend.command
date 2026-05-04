#!/bin/bash
# ratethat.tennis — Frontend dev server
# Requires: API running at http://localhost:8000 (run_api.command)
cd "$(dirname "$0")/frontend"

echo "============================================"
echo " ratethat.tennis — Frontend Dev Server"
echo "============================================"
echo ""
echo "Installing dependencies (first run may take a moment)..."
npm install
if [ $? -ne 0 ]; then
  echo "ERROR: npm install failed."
  read -n 1
  exit 1
fi

echo ""
echo "Starting Vite dev server at http://localhost:3000 ..."
echo "(Proxies /api/* → http://localhost:8000)"
echo ""
npm run dev

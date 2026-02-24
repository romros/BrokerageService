#!/bin/bash
# Test demo: Node.js CLI → Python bridge

set -e

cd /mnt/volume-SQ/dev/BrokerageService/lab/node-gtrade

echo "=" | head -c 80
echo ""
echo "🧪 DEMO: Node.js + Python Bridge Test"
echo "=" | head -c 80
echo ""
echo ""

# Step 1: Install Node.js deps (if needed)
if [ ! -d "node_modules" ]; then
    echo "📦 Installing Node.js dependencies..."
    docker compose run --rm gtrade-cli npm install
    echo ""
fi

# Step 2: Test Node.js CLI directly
echo "🔧 Test 1: Node.js CLI directly"
echo "=" | head -c 80
echo ""

docker compose run --rm gtrade-cli node simpleQuote.js 2>&1 | grep -A 30 "^{"

echo ""
echo ""

# Step 3: Test Python calling Node.js
echo "🐍 Test 2: Python bridge calling Node.js"
echo "=" | head -c 80
echo ""

docker compose run --rm gtrade-cli sh -c "python3 bridge_demo.py"

echo ""
echo ""
echo "=" | head -c 80
echo "✅ DEMO COMPLETED!"
echo "=" | head -c 80

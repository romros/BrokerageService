#!/bin/bash
# T8.27 — Decompila SQTradingLib.jar amb jadx
#
# Prerequisits: Java 11+ i jadx
#   sudo apt install openjdk-17-jdk-headless
#   curl -sL https://github.com/skylot/jadx/releases/download/v1.5.1/jadx-1.5.1.zip -o /tmp/jadx.zip
#   unzip /tmp/jadx.zip -d /tmp/jadx-dist
#
# Ús: ./decompile_sqtradinglib.sh

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
JAR="$SCRIPT_DIR/sq_decompiled/internal/libs/SQTradingLib.jar"
OUT="$SCRIPT_DIR/sq_decompiled/src"

if [ ! -f "$JAR" ]; then
  echo "ERROR: $JAR no existeix. Executa: unzip ... sq.zip internal/libs/SQTradingLib.jar -d sq_decompiled"
  exit 1
fi

JADX="/tmp/bin/jadx"
if [ ! -f "$JADX" ]; then
  echo "Descarregant jadx..."
  mkdir -p /tmp
  curl -sL "https://github.com/skylot/jadx/releases/download/v1.5.1/jadx-1.5.1.zip" -o /tmp/jadx.zip
  unzip -o /tmp/jadx.zip -d /tmp
fi

if ! command -v java &>/dev/null; then
  echo "ERROR: Java no instal·lat. Executa: sudo apt install openjdk-17-jdk-headless"
  exit 1
fi

echo "Decompilant $JAR → $OUT"
/tmp/bin/jadx -d "$OUT" --no-res "$JAR"
echo "Fet. Codi a: $OUT"
echo ""
echo "Classes indicadors:"
find "$OUT" -type f -name "*.java" | grep -iE "indicator|ema|rsi|atr|ma|wild" | head -30

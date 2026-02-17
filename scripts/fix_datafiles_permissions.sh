#!/bin/bash
# Arregla permisos de datafiles i logs quan Docker els ha creat com root.
# Executar des de l'arrel del projecte: ./scripts/fix_datafiles_permissions.sh
# Requereix sudo per chown.

set -e
cd "$(dirname "$0")/.."

USER="${SUDO_USER:-$(whoami)}"
echo "Ajustant permisos de datafiles/ i logs/ per a l'usuari: $USER"

if [ -d "datafiles" ]; then
  sudo chown -R "$USER:$USER" datafiles
  chmod -R u+rwX datafiles
  echo "  ✓ datafiles"
fi

if [ -d "logs" ]; then
  sudo chown -R "$USER:$USER" logs
  chmod -R u+rwX logs
  echo "  ✓ logs"
fi

echo "Fet. Ara pots obrir els CSV des de l'IDE."

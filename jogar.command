#!/bin/zsh
set -e

cd "$(dirname "$0")"

if [[ ! -x .venv/bin/python ]]; then
  echo "Ambiente nao encontrado. Execute instalar_dependencias.command primeiro."
  read -k 1 "?Pressione qualquer tecla para fechar..."
  exit 1
fi

exec .venv/bin/python main.py

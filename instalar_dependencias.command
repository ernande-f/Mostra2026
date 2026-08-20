#!/bin/zsh
set -e

cd "$(dirname "$0")"

if command -v uv >/dev/null 2>&1; then
  if [[ ! -x .venv/bin/python ]] || ! .venv/bin/python -c 'import sys; raise SystemExit(sys.version_info[:2] != (3, 12))'; then
    uv venv --python 3.12 .venv
  fi
  UV_CACHE_DIR="${TMPDIR:-/tmp}/mostra2026-uv-cache" uv pip install --python .venv/bin/python -r requirements.txt
else
  PYTHON_BIN="$(command -v python3.12 || true)"
  if [[ -z "$PYTHON_BIN" ]]; then
    echo "Python 3.12 nao encontrado. Instale-o ou instale o uv: https://docs.astral.sh/uv/"
    exit 1
  fi
  "$PYTHON_BIN" -m venv .venv
  .venv/bin/python -m pip install -r requirements.txt
fi

echo
echo "Dependencias instaladas. Agora abra jogar.command."
read -k 1 "?Pressione qualquer tecla para fechar..."

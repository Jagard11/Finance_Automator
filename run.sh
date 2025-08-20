#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

if command -v python3 >/dev/null 2>&1; then
	PYTHON=python3
elif command -v python >/dev/null 2>&1; then
	PYTHON=python
else
	echo "Python 3 not found. Please install Python 3." >&2
	exit 1
fi

if [ ! -d "$VENV_DIR" ]; then
	"$PYTHON" -m venv "$VENV_DIR"
fi

. "$VENV_DIR/bin/activate"

python -m pip install -r "$SCRIPT_DIR/requirements.txt"

# Forward only `--*` flags to the app
forward_args=()
for arg in "$@"; do
	case "$arg" in
		--*) forward_args+=("$arg") ;;
	esac
done

exec python "$SCRIPT_DIR/app.py" "${forward_args[@]}"

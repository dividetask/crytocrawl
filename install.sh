#!/usr/bin/env bash
# Bootstrap crytocrawl on a fresh Debian/Ubuntu server.
# Run from inside the cloned repo:  bash install.sh
set -euo pipefail

if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update
    # python3 + venv to install into; sqlite3 is OPTIONAL (only for querying the
    # DB directly without Python). The tool itself uses Python's built-in sqlite3.
    sudo apt-get install -y python3 python3-venv python3-pip git sqlite3
fi

VENV="${VENV:-$HOME/crytocrawl-venv}"
python3 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip
"$VENV/bin/pip" install .

cat <<EOF

crytocrawl installed into $VENV

Activate it and check the CLI:
    source "$VENV/bin/activate"
    crytocrawl --help

(Or run without activating: "$VENV/bin/crytocrawl --help")
EOF

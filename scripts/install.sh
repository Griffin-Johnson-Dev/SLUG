#!/bin/sh
set -eu
ROOT=$(CDPATH= cd "$(dirname "$0")/.." && pwd)
PREFIX=${PREFIX:-"$HOME/.local"}
CC_BIN=${CC:-cc}
python3 "$ROOT/tools/build_install_tree.py" --prefix "$PREFIX" --cc "$CC_BIN"
printf '\nSLUG installed under %s\n' "$PREFIX"
printf 'Add %s/bin to PATH if necessary.\n' "$PREFIX"
printf 'Verify with: slug --version && slug --language-version\n'

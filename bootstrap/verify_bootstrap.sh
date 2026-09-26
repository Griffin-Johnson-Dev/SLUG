#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
CC_BIN=${CC:-cc}
GC_INTERVAL=${SLUG_GC_INTERVAL:-262144}
B=build/bootstrap_verify
rm -rf "$B"; mkdir -p "$B"
VERSION_EXPECTED=$(cat VERSION)
LANG_EXPECTED=$(cat LANGUAGE_VERSION)
compile(){ "$CC_BIN" "$1" -std=c11 -O2 -o "$2" -lm; }

printf '[1/9] compile canonical seed\n'
compile bootstrap/slug_seed.c "$B/slug_seed"
printf '[2/9] verify seed identity\n'
[ "$("$B/slug_seed" --version)" = "$VERSION_EXPECTED" ]
[ "$("$B/slug_seed" --language-version)" = "$LANG_EXPECTED" ]
printf '[3/9] seed checks maintained compiler root\n'
SLUG_GC_INTERVAL="$GC_INTERVAL" "$B/slug_seed" check compiler/stage2/app.slg
printf '[4/9] seed regenerates compiler C\n'
SLUG_GC_INTERVAL="$GC_INTERVAL" "$B/slug_seed" emit-c compiler/stage2/app.slg "$B/generation1.c"
printf '[5/9] generation 1 equals canonical seed\n'
cmp -s bootstrap/slug_seed.c "$B/generation1.c"
printf '[6/9] compile generation 1\n'
compile "$B/generation1.c" "$B/slug_generation1"
printf '[7/9] generation 1 checks maintained compiler root\n'
SLUG_GC_INTERVAL="$GC_INTERVAL" "$B/slug_generation1" check compiler/stage2/app.slg
printf '[8/9] generation 1 emits generation 2\n'
SLUG_GC_INTERVAL="$GC_INTERVAL" "$B/slug_generation1" emit-c compiler/stage2/app.slg "$B/generation2.c"
printf '[9/9] generation 2 is byte-identical\n'
cmp -s "$B/generation1.c" "$B/generation2.c"
sha256sum bootstrap/slug_seed.c "$B/generation1.c" "$B/generation2.c" > "$B/fixed_point.sha256"
printf 'SLUG BOOTSTRAP PASS\n'

#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
fail(){ echo "LINUX CERTIFICATION FAIL: $*" >&2; exit 1; }

[[ -f VERSION && -f LANGUAGE_VERSION && -f SOURCE_SHA256SUMS.txt ]] || fail "run against an exact extracted SLUG release source root"
command -v python3 >/dev/null || fail "python3 not found"
command -v node >/dev/null || fail "node not found"
command -v gcc >/dev/null || fail "gcc not found"
command -v clang >/dev/null || fail "clang not found"
command -v sha256sum >/dev/null || fail "sha256sum not found"

VERSION_EXPECTED=$(cat VERSION)
LANG_EXPECTED=$(cat LANGUAGE_VERSION)
B=build/linux_certification
rm -rf "$B"; mkdir -p "$B"

echo "[1/8] verify exact source manifest ($VERSION_EXPECTED / language $LANG_EXPECTED)"
sha256sum -c SOURCE_SHA256SUMS.txt >/dev/null

echo "[2/8] verify canonical seed"
sha256sum -c bootstrap/CANONICAL_SEED_SHA256.txt >/dev/null
SEED_SHA=$(sha256sum bootstrap/slug_seed.c | awk '{print $1}')
MANIFEST_SHA=$(sha256sum SOURCE_SHA256SUMS.txt | awk '{print $1}')

echo "[3/8] GCC bootstrap fixed point"
CC=gcc bash bootstrap/verify_bootstrap.sh | tee "$B/gcc-bootstrap.log"

echo "[4/8] GCC installed distribution + full release gate"
python3 tools/build_install_tree.py --prefix "$B/gcc-prefix" --cc gcc | tee "$B/gcc-install.log"
python3 tools/run_release_gate.py --slug "$ROOT/$B/gcc-prefix/bin/slug" --prefix "$ROOT/$B/gcc-prefix" | tee "$B/gcc-release-gate.log"

echo "[5/8] Clang bootstrap fixed point"
CC=clang bash bootstrap/verify_bootstrap.sh | tee "$B/clang-bootstrap.log"

echo "[6/8] Clang installed distribution + full release gate"
python3 tools/build_install_tree.py --prefix "$B/clang-prefix" --cc clang | tee "$B/clang-install.log"
python3 tools/run_release_gate.py --slug "$ROOT/$B/clang-prefix/bin/slug" --prefix "$ROOT/$B/clang-prefix" | tee "$B/clang-release-gate.log"

echo "[7/8] write certification record"
export ROOT VERSION_EXPECTED LANG_EXPECTED SEED_SHA MANIFEST_SHA
python3 - <<'PY2'
import hashlib, json, os, platform, subprocess
from datetime import datetime, timezone
from pathlib import Path
root=Path(os.environ['ROOT'])
def first(cmd): return subprocess.check_output(cmd,text=True,stderr=subprocess.STDOUT).strip().splitlines()[0]
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1<<20),b''): h.update(b)
    return h.hexdigest()
b=root/'build'/'linux_certification'
record={
  'schema':2,'status':'PASS','certified_at_utc':datetime.now(timezone.utc).isoformat(),
  'compiler_version':os.environ['VERSION_EXPECTED'],'language_version':os.environ['LANG_EXPECTED'],
  'os':platform.platform(),'architecture':platform.machine(),
  'gcc_version':first(['gcc','--version']),'clang_version':first(['clang','--version']),
  'python_version':first(['python3','--version']),'node_version':first(['node','--version']),
  'canonical_seed_sha256':os.environ['SEED_SHA'],'source_manifest_sha256':os.environ['MANIFEST_SHA'],
  'gcc_installed_compiler_sha256':sha(b/'gcc-prefix'/'bin'/'slug'),
  'clang_installed_compiler_sha256':sha(b/'clang-prefix'/'bin'/'slug'),
  'installed_devkit_sha256':sha(b/'gcc-prefix'/'share'/'slug'/'1.0'/'tooling'/'vscode'/'slug-language.vsix'),
  'gcc_bootstrap':'PASS','gcc_full_release_gate':'PASS','clang_bootstrap':'PASS','clang_full_release_gate':'PASS'
}
out=root/'build'/f"LINUX_CERTIFICATION_SLUG-{os.environ['VERSION_EXPECTED']}.json"
out.write_text(json.dumps(record,indent=2,sort_keys=True)+'\n',encoding='utf-8')
print(out)
PY2

echo "[8/8] final identity"
CERT="$ROOT/build/LINUX_CERTIFICATION_SLUG-$VERSION_EXPECTED.json"
sha256sum "$CERT"
cat "$CERT"
echo "LINUX CERTIFICATION PASS"

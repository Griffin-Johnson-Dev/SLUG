#!/usr/bin/env python3
from __future__ import annotations
import argparse
import subprocess
import tempfile
from pathlib import Path


def run(cmd: list[str], cwd: Path, *, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, input=stdin, text=True, encoding='utf-8', errors='strict', stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)


def main() -> int:
    ap = argparse.ArgumentParser(description='SLUG v1 UTF-8 platform boundary gate')
    ap.add_argument('--slug', required=True, type=Path)
    a = ap.parse_args()
    slug = a.slug.resolve()
    if not slug.is_file():
        raise SystemExit(f'missing compiler: {slug}')

    passed = 0
    total = 4
    def need(ok: bool, name: str, detail: str = '') -> None:
        nonlocal passed
        if not ok:
            raise SystemExit(f'FAIL {name}: {detail}')
        passed += 1
        print(f'PASS {name}', flush=True)

    with tempfile.TemporaryDirectory(prefix='slug-utf8-') as raw:
        root = Path(raw) / 'π-雪-🙂'
        src = root / 'src'
        lib = src / '库'
        lib.mkdir(parents=True)

        plain = src / 'λ-main-雪.slg'
        plain.write_text("co['λ雪🙂']\n", encoding='utf-8')
        p = run([str(slug), 'check', str(plain)], root)
        need(p.returncode == 0, 'unicode-source-path', repr((p.returncode, p.stdout, p.stderr)))

        helper = lib / '工具-λ.slg'
        helper.write_text("~tw x {rv x 2 *;}\n", encoding='utf-8')
        imported = src / '导入.slg'
        imported.write_text(">'库/工具-λ.slg':MA\nco[MA.tw[21]]\n", encoding='utf-8')
        p = run([str(slug), 'run', str(imported)], src)
        need(p.returncode == 0 and p.stdout == '42\n', 'unicode-import-path', repr((p.returncode, p.stdout, p.stderr)))

        p = run([str(slug), 'run', str(plain)], root)
        need(p.returncode == 0 and p.stdout == 'λ雪🙂\n', 'utf8-redirected-stdout', repr((p.returncode, p.stdout, p.stderr)))

        echo = src / '输入.slg'
        echo.write_text("a:=ci[];co[a]\n", encoding='utf-8')
        p = run([str(slug), 'run', str(echo)], root, stdin='é雪🙂\n')
        need(p.returncode == 0 and p.stdout == 'é雪🙂\n', 'utf8-redirected-stdin', repr((p.returncode, p.stdout, p.stderr)))

    print(f'UTF8 PLATFORM PASS {passed}/{total}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

#!/usr/bin/env python3
"""Synchronize/verify SLUG's authoritative release metadata.

VERSION and LANGUAGE_VERSION are authoritative.  This script deliberately treats
VS Code's package version as an editor-client version rather than the compiler
version.
"""
from __future__ import annotations
import argparse, re, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def read(name:str)->str: return (ROOT/name).read_text(encoding='utf-8').strip()

def pep440(v:str)->str:
    m=re.fullmatch(r'(\d+\.\d+\.\d+)-dev\+([0-9A-Za-z.-]+)',v)
    if m:return f'{m.group(1)}.dev0+{m.group(2).lower().replace("-",".")}'
    m=re.fullmatch(r'(\d+\.\d+\.\d+)-rc\.(\d+)',v)
    if m:return f'{m.group(1)}rc{m.group(2)}'
    if re.fullmatch(r'\d+\.\d+\.\d+',v):return v
    raise SystemExit(f'unsupported VERSION syntax: {v!r}')

def replacements(version:str,lang:str):
    return [
      ('src/sluglang/__init__.py', re.compile(r'__version__\s*=\s*"[^"]+"'), f'__version__ = "{version}"'),
      ('pyproject.toml', re.compile(r'(?m)^version\s*=\s*"[^"]+"'), f'version = "{pep440(version)}"'),
      ('tooling/lsp/slug-lsp.js', re.compile(r"const SERVER_VERSION = '[^']+';"), f"const SERVER_VERSION = '{version}';"),
    ]

def expected_app(text:str,version:str,lang:str)->str:
    text=re.sub(r'(?<=SLUG compiler )[0-9A-Za-z.+-]+(?= — language)',version,text)
    text=re.sub(r'(?<=\"compiler_version\":\")[^\"]+',version,text)
    text=re.sub(r"(\?c=='--version' \{ \?n!=1\{pd\['usage: slug --version'\];\}co\[')[^']+('\];rv; \})",rf'\g<1>{version}\g<2>',text)
    text=re.sub(r"(\?c=='version' \{ \?n!=1\{pd\['usage: slug --version'\];\}co\[')[^']+('\];rv; \})",rf'\g<1>{version}\g<2>',text)
    text=re.sub(r"(\?c=='--language-version' \{ \?n!=1\{pd\['usage: slug --language-version'\];\}co\[')[^']+('\];rv; \})",rf'\g<1>{lang}\g<2>',text)
    return text
def expected_cli(text:str,lang:str)->str:
    text=re.sub(r'print\("[0-9]+\.[0-9]+"\)(?=\n\s*return 0\n\s*if ns\.cmd)',f'print("{lang}")',text,count=1)
    text=re.sub(r'"language_version":\s*"[0-9]+\.[0-9]+"',f'"language_version": "{lang}"',text,count=1)
    return text

def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument('--write',action='store_true'); ns=ap.parse_args()
    version,lang=read('VERSION'),read('LANGUAGE_VERSION')
    problems=[]
    for rel,rx,repl in replacements(version,lang):
        p=ROOT/rel; old=p.read_text(encoding='utf-8'); new,n=rx.subn(repl,old,count=1)
        if n!=1: problems.append(f'{rel}: expected exactly one metadata field')
        elif new!=old:
            if ns.write:p.write_text(new,encoding='utf-8')
            else:problems.append(f'{rel}: metadata drift')
    for rel,fn in [('compiler/stage2/app.slg',lambda s:expected_app(s,version,lang)),('src/sluglang/cli.py',lambda s:expected_cli(s,lang))]:
        p=ROOT/rel; old=p.read_text(encoding='utf-8'); new=fn(old)
        if new!=old:
            if ns.write:p.write_text(new,encoding='utf-8')
            else:problems.append(f'{rel}: metadata drift')
    if problems:
        print('RELEASE METADATA FAIL',file=sys.stderr)
        for x in problems:print(' - '+x,file=sys.stderr)
        return 1
    print(f'RELEASE METADATA PASS compiler={version} language={lang} pyproject={pep440(version)}')
    return 0
if __name__=='__main__':raise SystemExit(main())

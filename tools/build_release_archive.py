#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, shutil, subprocess, sys, tempfile, zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
EXCLUDE_DIRS={'.git','build','__pycache__','.pytest_cache','.mypy_cache'}
EXCLUDE_SUFFIXES={'.pyc','.pyo','.vsix'}
EXCLUDE_NAMES={'SOURCE_SHA256SUMS.txt'}

def sha_bytes(b:bytes)->str:return hashlib.sha256(b).hexdigest()
def sha_file(p:Path)->str:
    h=hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda:f.read(1<<20),b''):h.update(chunk)
    return h.hexdigest()

def wanted(p:Path)->bool:
    rel=p.relative_to(ROOT)
    if any(part in EXCLUDE_DIRS for part in rel.parts):return False
    if p.name in EXCLUDE_NAMES:return False
    if p.suffix in EXCLUDE_SUFFIXES:return False
    if p.name.endswith('.slug-tmp') or '.slug-run-' in p.name or (p.name.startswith('.') and '.slug-lsp-' in p.name):return False
    return p.is_file()

def files()->list[Path]:return sorted((p for p in ROOT.rglob('*') if wanted(p)),key=lambda p:p.relative_to(ROOT).as_posix())

def canonical_manifest(fs:list[Path])->bytes:
    lines=[f"{sha_file(p)}  {p.relative_to(ROOT).as_posix()}" for p in fs]
    return ('\n'.join(lines)+'\n').encode('utf-8')

def add(z:zipfile.ZipFile,name:str,data:bytes,mode:int=0o100644):
    zi=zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0));zi.compress_type=zipfile.ZIP_DEFLATED;zi.external_attr=mode<<16;z.writestr(zi,data)

def verify_archive(out:Path,prefix:str,manifest:bytes):
    with tempfile.TemporaryDirectory(prefix='slug-release-verify-') as td:
        td=Path(td)
        with zipfile.ZipFile(out) as z:z.extractall(td)
        root=td/prefix
        got=(root/'SOURCE_SHA256SUMS.txt').read_bytes()
        if got!=manifest:raise SystemExit('archive manifest bytes changed')
        listed=[]
        for line in got.decode().splitlines():
            digest,rel=line.split('  ',1);p=root/rel
            if not p.is_file():raise SystemExit(f'archive missing manifest file: {rel}')
            if sha_file(p)!=digest:raise SystemExit(f'archive hash mismatch: {rel}')
            listed.append(rel)
        actual=sorted(p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and p.name!='SOURCE_SHA256SUMS.txt')
        if sorted(listed)!=actual:raise SystemExit('archive manifest coverage mismatch')

def main()->int:
    ap=argparse.ArgumentParser(description='Build deterministic clean SLUG source archive')
    ap.add_argument('--out',type=Path)
    a=ap.parse_args()
    subprocess.run([sys.executable,str(ROOT/'tools/release_metadata.py')],cwd=ROOT,check=True)
    subprocess.run([sys.executable,str(ROOT/'tools/verify_public_contract.py')],cwd=ROOT,check=True,stdout=subprocess.DEVNULL)
    subprocess.run([sys.executable,str(ROOT/'tools/verify_install_layout.py')],cwd=ROOT,check=True,stdout=subprocess.DEVNULL)
    version=(ROOT/'VERSION').read_text().strip();prefix=f'SLUG-{version}'
    fs=files();manifest=canonical_manifest(fs);(ROOT/'SOURCE_SHA256SUMS.txt').write_bytes(manifest)
    out=(a.out or ROOT/'build'/f'{prefix}.zip').resolve();out.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(out,'w') as z:
        for p in fs:
            rel=p.relative_to(ROOT).as_posix();mode=0o100755 if (p.stat().st_mode & 0o111) else 0o100644
            add(z,f'{prefix}/{rel}',p.read_bytes(),mode)
        add(z,f'{prefix}/SOURCE_SHA256SUMS.txt',manifest)
    verify_archive(out,prefix,manifest)
    info={'file':out.name,'bytes':out.stat().st_size,'sha256':sha_file(out),'tree_files':len(fs)+1,'manifest_covered':len(fs),'prefix':prefix}
    print(json.dumps(info,separators=(',',':')))
    return 0
if __name__=='__main__':raise SystemExit(main())

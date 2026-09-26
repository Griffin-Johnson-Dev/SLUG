#!/usr/bin/env python3
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
s=(ROOT/'tools'/'build_install_tree.py').read_text(encoding='utf-8')
checks=[
 ('prefix-never-recursively-deleted','shutil.rmtree(prefix' not in s),
 ('only-versioned-owned-trees-refreshed',"shutil.rmtree(libdir" in s and "shutil.rmtree(shared" in s),
 ('owned-launchers-only',"bindir/'slug'" in s and "bindir/'slug.exe'" in s),
 ('build-before-commit',"TemporaryDirectory(prefix='slug-install-stage-')" in s and 'populate(root,stage' in s and 'commit(stage,prefix)' in s),
]
for name,ok in checks:
    if not ok:raise AssertionError(name)
    print('PASS',name)
print(f'INSTALL SAFETY PASS {len(checks)}/{len(checks)}')

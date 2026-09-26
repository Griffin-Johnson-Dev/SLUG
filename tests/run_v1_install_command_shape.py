#!/usr/bin/env python3
from __future__ import annotations
import importlib.util
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('build_install_tree',ROOT/'tools'/'build_install_tree.py')
mod=importlib.util.module_from_spec(spec); assert spec.loader; spec.loader.exec_module(mod)
seed=Path('seed.c'); exe=Path('slug.exe')

linux=mod.compile_command('gcc',seed,Path('slug'),False)
assert linux == ['gcc','seed.c','-std=c11','-O2','-o','slug','-lm'], linux
print('PASS linux-gcc-shape')

clangcl=mod.compile_command('clang-cl',seed,exe,True)
assert clangcl[:5] == ['clang-cl','/nologo','/std:c11','/O2','seed.c'], clangcl
assert '/Fe:slug.exe' in clangcl and 'ws2_32.lib' in clangcl and '-lws2_32' not in clangcl, clangcl
print('PASS windows-clang-cl-shape')

msvc=mod.compile_command('cl.exe',seed,exe,True)
assert msvc[0]=='cl.exe' and '/Fe:slug.exe' in msvc and 'winmm.lib' in msvc, msvc
print('PASS windows-msvc-shape')

mingw=mod.compile_command('gcc',seed,exe,True)
assert '-std=c11' in mingw and '-lws2_32' in mingw and '/std:c11' not in mingw, mingw
print('PASS windows-gnu-shape')
print('INSTALL COMMAND SHAPE PASS 4/4')

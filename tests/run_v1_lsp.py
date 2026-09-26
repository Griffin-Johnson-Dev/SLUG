#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import queue
import subprocess
import tempfile
import threading
import time
from urllib.parse import urljoin
from urllib.request import pathname2url

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / 'tooling' / 'lsp' / 'slug-lsp.js'


def file_uri(path: Path) -> str:
    return urljoin('file:', pathname2url(str(path.resolve())))


class LspClient:
    def __init__(self, slug: Path):
        self.p = subprocess.Popen(
            ['node', str(SERVER), '--slug', str(slug)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=ROOT, env=os.environ.copy(),
        )
        assert self.p.stdin and self.p.stdout and self.p.stderr
        self.q: queue.Queue[dict] = queue.Queue()
        self.err: list[bytes] = []
        threading.Thread(target=self._reader, daemon=True).start()
        threading.Thread(target=self._err_reader, daemon=True).start()
        self.next_id = 1

    def _reader(self):
        f = self.p.stdout
        while True:
            headers = {}
            while True:
                line = f.readline()
                if not line:
                    return
                if line == b'\r\n':
                    break
                k, v = line.decode('ascii').split(':', 1)
                headers[k.lower()] = v.strip()
            n = int(headers['content-length'])
            body = f.read(n)
            self.q.put(json.loads(body.decode('utf-8')))

    def _err_reader(self):
        assert self.p.stderr
        for line in self.p.stderr:
            self.err.append(line)

    def send(self, obj: dict):
        data = json.dumps(obj, separators=(',', ':')).encode()
        self.p.stdin.write(f'Content-Length: {len(data)}\r\n\r\n'.encode() + data)
        self.p.stdin.flush()

    def request(self, method: str, params=None, timeout=120):
        i = self.next_id; self.next_id += 1
        self.send({'jsonrpc':'2.0','id':i,'method':method,'params':params or {}})
        deadline = time.time() + timeout
        stash = []
        try:
            while time.time() < deadline:
                try: m = self.q.get(timeout=min(0.25, max(0.01, deadline-time.time())))
                except queue.Empty: continue
                if m.get('id') == i:
                    if 'error' in m: raise RuntimeError(m['error'])
                    return m.get('result')
                stash.append(m)
        finally:
            for m in stash: self.q.put(m)
        raise TimeoutError(f'LSP request timed out: {method}')

    def notify(self, method: str, params=None):
        self.send({'jsonrpc':'2.0','method':method,'params':params or {}})

    def wait_notification(self, method: str, predicate=lambda m: True, timeout=120):
        deadline = time.time() + timeout
        stash=[]
        try:
            while time.time() < deadline:
                try: m=self.q.get(timeout=min(0.25,max(0.01,deadline-time.time())))
                except queue.Empty: continue
                if m.get('method') == method and predicate(m): return m
                stash.append(m)
        finally:
            for m in stash: self.q.put(m)
        raise TimeoutError(f'LSP notification timed out: {method}')

    def close(self):
        try:
            self.request('shutdown', {}, timeout=10)
            self.notify('exit', {})
            self.p.wait(timeout=10)
        except Exception:
            self.p.kill(); self.p.wait(timeout=5)


def main() -> int:
    global SERVER
    ap=argparse.ArgumentParser(description='SLUG K9J LSP diagnostic protocol gate')
    ap.add_argument('--slug', required=True); ap.add_argument('--server', default=str(SERVER))
    ns=ap.parse_args(); slug=Path(ns.slug).resolve(); SERVER=Path(ns.server).resolve()
    if not slug.is_file(): print(f'missing native compiler: {slug}'); return 2
    passed=total=0; failures=[]
    def rec(name, ok, detail=''):
        nonlocal passed,total
        total += 1
        if ok: passed += 1; print('PASS',name)
        else: failures.append(name + (': '+detail if detail else '')); print('FAIL',name,detail)

    with tempfile.TemporaryDirectory(prefix='slug-k9g-lsp-') as td0:
        td=Path(td0); proj=td/'proj'; srcdir=proj/'src'; libdir=proj/'lib'; srcdir.mkdir(parents=True); libdir.mkdir()
        (proj/'vendor'/'lib').mkdir(parents=True); (proj/'vendor'/'lib'/'api.slg').write_text('~tr x {rv x 3 *;}\n',encoding='utf-8'); (proj/'slug.json').write_text('{"schema":1,"name":"demo","entry":"src/main.slg","dependencies":{"lib":"vendor/lib"}}\n',encoding='utf-8')
        (libdir/'helper.slg').write_text('~tw a {rv a 2 *;}\n',encoding='utf-8')
        main=srcdir/'main.slg'; main.write_text(">'../lib/helper.slg':HE\nco[HE.tw[21]]\n",encoding='utf-8')
        uri=file_uri(main)
        c=LspClient(slug)
        try:
            init=c.request('initialize', {'processId':None,'rootUri':file_uri(proj),'capabilities':{}}, timeout=30)
            caps=init.get('capabilities',{})
            rec('initialize', init.get('serverInfo',{}).get('name')=='slug-lsp')
            rec('full-sync-capability', caps.get('textDocumentSync',{}).get('change')==1)
            rec('formatting-capability', caps.get('documentFormattingProvider') is True)
            rec('stdin-overlay-advertised', caps.get('experimental',{}).get('unsavedBufferMode')=='stdin-overlay')
            rec('failure-provenance-diagnostics-advertised', caps.get('experimental',{}).get('nativeDiagnosticPositions')=='failure-provenance-v2')
            c.notify('initialized',{})

            ti=c.request('slug/toolingInfo',{},timeout=30)
            rec('tooling-info',ti.get('schema')==1 and ti.get('capabilities',{}).get('project_discovery') is True)
            pi=c.request('slug/projectInfo',{'uri':uri},timeout=30)
            rec('project-info',pi.get('found') is True and pi.get('name')=='demo' and pi.get('entry')=='src/main.slg' and pi.get('dependency_count')==1)

            text=main.read_text(encoding='utf-8')
            c.notify('textDocument/didOpen',{'textDocument':{'uri':uri,'languageId':'slug','version':1,'text':text}})
            n=c.wait_notification('textDocument/publishDiagnostics',lambda m:m.get('params',{}).get('uri')==uri,timeout=120)
            rec('open-valid-diagnostics',n['params'].get('diagnostics')==[])
            shadows=list(srcdir.glob('.*.slug-lsp-*.slg'))
            rec('open-shadow-cleanup',not shadows,repr(shadows))

            bad="if ? {\n"
            c.notify('textDocument/didChange',{'textDocument':{'uri':uri,'version':2},'contentChanges':[{'text':bad}]})
            n=c.wait_notification('textDocument/publishDiagnostics',lambda m:m.get('params',{}).get('version')==2,timeout=120)
            ds=n['params'].get('diagnostics',[])
            rec('change-invalid-diagnostic',len(ds)==1 and ds[0].get('source') in ('slug','slug-lsp'),repr(ds))
            rec('diagnostic-range-shape',bool(ds) and 'range' in ds[0] and 'start' in ds[0]['range'])
            rec('diagnostic-exact-unmatched-opener',bool(ds) and ds[0]['range']=={'start':{'line':0,'character':5},'end':{'line':0,'character':6}},repr(ds))
            rec('diagnostic-position-mode',bool(ds) and ds[0].get('data',{}).get('positionMode')=='failure-provenance-v2',repr(ds))

            messy="a:=1;co[a]\n"
            c.notify('textDocument/didChange',{'textDocument':{'uri':uri,'version':3},'contentChanges':[{'text':messy}]})
            n=c.wait_notification('textDocument/publishDiagnostics',lambda m:m.get('params',{}).get('version')==3,timeout=120)
            rec('change-valid-clears',n['params'].get('diagnostics')==[])
            edits=c.request('textDocument/formatting',{'textDocument':{'uri':uri},'options':{'tabSize':4,'insertSpaces':True}},timeout=120)
            rec('formatting-edit',isinstance(edits,list) and len(edits)==1 and edits[0]['newText'].endswith('\n'),repr(edits))
            rec('formatting-does-not-mutate-disk',main.read_text(encoding='utf-8')==text)
            rec('format-shadow-cleanup',not list(srcdir.glob('.*.slug-lsp-*.slg')))

            deptext=">'../lib/helper.slg':HE\nco[HE.tw[7]]\n"
            c.notify('textDocument/didChange',{'textDocument':{'uri':uri,'version':4},'contentChanges':[{'text':deptext}]})
            n=c.wait_notification('textDocument/publishDiagnostics',lambda m:m.get('params',{}).get('version')==4,timeout=120)
            rec('unsaved-relative-import',n['params'].get('diagnostics')==[],repr(n['params'].get('diagnostics')))

            deptext=">'@dep/lib/api.slg':DP\nco[DP.tr[14]]\n"
            c.notify('textDocument/didChange',{'textDocument':{'uri':uri,'version':5},'contentChanges':[{'text':deptext}]})
            n=c.wait_notification('textDocument/publishDiagnostics',lambda m:m.get('params',{}).get('version')==5,timeout=120)
            rec('unsaved-dependency-import',n['params'].get('diagnostics')==[],repr(n['params'].get('diagnostics')))

            imported_bad=">'../lib/helper.slg':HE\nco[HE.tw[7]]\nif1{co1}\n"
            c.notify('textDocument/didChange',{'textDocument':{'uri':uri,'version':6},'contentChanges':[{'text':imported_bad}]})
            n=c.wait_notification('textDocument/publishDiagnostics',lambda m:m.get('params',{}).get('version')==6,timeout=120)
            ds=n['params'].get('diagnostics',[])
            rec('imported-buffer-failure-location',bool(ds) and ds[0]['range']['start']=={'line':2,'character':2},repr(ds))

            unicode_bad="co['🙂'];if1{co1}\n"
            expected_utf16=len(unicode_bad[:unicode_bad.index('1')].encode('utf-16-le'))//2
            c.notify('textDocument/didChange',{'textDocument':{'uri':uri,'version':7},'contentChanges':[{'text':unicode_bad}]})
            n=c.wait_notification('textDocument/publishDiagnostics',lambda m:m.get('params',{}).get('version')==7,timeout=120)
            ds=n['params'].get('diagnostics',[])
            rec('unicode-utf16-diagnostic-column',bool(ds) and ds[0]['range']['start']=={'line':0,'character':expected_utf16},repr((expected_utf16,ds)))

            lexical_bad='a:=1\n€\n'
            c.notify('textDocument/didChange',{'textDocument':{'uri':uri,'version':8},'contentChanges':[{'text':lexical_bad}]})
            n=c.wait_notification('textDocument/publishDiagnostics',lambda m:m.get('params',{}).get('version')==8,timeout=120)
            ds=n['params'].get('diagnostics',[])
            rec('lexical-provenance-range',bool(ds) and ds[0]['range']=={'start':{'line':1,'character':0},'end':{'line':1,'character':1}},repr(ds))
            rec('lexical-provenance-mode',bool(ds) and ds[0].get('data',{}).get('positionMode')=='failure-provenance-v2',repr(ds))

            semantic_bad='a:=1\nbl\n'
            c.notify('textDocument/didChange',{'textDocument':{'uri':uri,'version':9},'contentChanges':[{'text':semantic_bad}]})
            n=c.wait_notification('textDocument/publishDiagnostics',lambda m:m.get('params',{}).get('version')==9,timeout=120)
            ds=n['params'].get('diagnostics',[])
            rec('semantic-provenance-range',bool(ds) and ds[0]['range']=={'start':{'line':1,'character':0},'end':{'line':1,'character':1}},repr(ds))
            rec('semantic-provenance-mode',bool(ds) and ds[0].get('data',{}).get('positionMode')=='failure-provenance-v2',repr(ds))

            nested_semantic='?1{bl}\n'
            c.notify('textDocument/didChange',{'textDocument':{'uri':uri,'version':10},'contentChanges':[{'text':nested_semantic}]})
            n=c.wait_notification('textDocument/publishDiagnostics',lambda m:m.get('params',{}).get('version')==10,timeout=120)
            ds=n['params'].get('diagnostics',[])
            rec('semantic-provenance-nested-range',bool(ds) and ds[0]['range']=={'start':{'line':0,'character':3},'end':{'line':0,'character':4}},repr(ds))

            c.notify('textDocument/didClose',{'textDocument':{'uri':uri}})
            n=c.wait_notification('textDocument/publishDiagnostics',lambda m:m.get('params',{}).get('uri')==uri and 'version' not in m.get('params',{}),timeout=30)
            rec('close-clears-diagnostics',n['params'].get('diagnostics')==[])
            try:
                c.request('textDocument/formatting',{'textDocument':{'uri':uri},'options':{}},timeout=10)
                rec('closed-format-rejected',False,'request unexpectedly succeeded')
            except RuntimeError:
                rec('closed-format-rejected',True)
        finally:
            c.close()

    if failures:
        print(f'K9J LSP FAIL {passed}/{total}')
        for f in failures: print(' -',f)
        return 1
    print(f'K9J LSP PASS {passed}/{total}')
    return 0

if __name__=='__main__': raise SystemExit(main())

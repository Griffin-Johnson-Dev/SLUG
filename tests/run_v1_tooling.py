#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PYCLI = [sys.executable, str(ROOT / "slug.py")]
RUNTIME = str((ROOT / "compiler" / "stage2" / "runtime_stage2.c").resolve())


def run(cmd: list[str], cwd: Path, timeout: int = 90, input_text: str | None = None):
    env = os.environ.copy(); env["SLUG_RUNTIME"] = RUNTIME
    return subprocess.run(
        cmd, cwd=cwd, env=env, text=True, encoding="utf-8", errors="strict",
        input=input_text, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="SLUG v1 K9J editor/tooling boundary gate")
    ap.add_argument("--slug", required=True)
    ns = ap.parse_args()
    native = Path(ns.slug).resolve()
    if not native.is_file():
        print(f"missing native compiler: {native}", file=sys.stderr); return 2

    passed = total = 0; failures: list[str] = []
    def rec(name: str, ok: bool, detail: str = "") -> None:
        nonlocal passed,total
        total += 1
        if ok: passed += 1; print(f"PASS {name}")
        else: failures.append(name + (f": {detail}" if detail else "")); print(f"FAIL {name}: {detail}")

    with tempfile.TemporaryDirectory(prefix="slug-k9g-tooling-") as td0:
        td=Path(td0)
        src=td/"sample.slg"; src.write_text("## ordinary\n##! keep\na:=1;co[a]\n",encoding="utf-8")
        # 1 stdout formatting never mutates source
        before=src.read_bytes(); p=run([str(native),"fmt",str(src)],td)
        rec("fmt-stdout-safe",p.returncode==0 and p.stdout.endswith("\n") and src.read_bytes()==before,repr((p.returncode,p.stderr)))
        # 2 formatter output is idempotent
        f1=td/"f1.slg"; f1.write_bytes(p.stdout.encode("utf-8")); p2=run([str(native),"fmt",str(f1)],td)
        rec("fmt-idempotent",p2.returncode==0 and p2.stdout==p.stdout,repr((p2.returncode,p2.stderr)))
        # 3 check recognizes canonical form
        rec("fmt-check-canonical",run([str(native),"fmt",str(f1),"--check"],td).returncode==0)
        # 4 write canonicalizes in place
        messy=td/"messy.slg"; messy.write_text("a:=1;co[a]\n",encoding="utf-8"); p=run([str(native),"fmt",str(messy),"--write"],td)
        rec("fmt-write",p.returncode==0 and run([str(native),"fmt",str(messy),"--check"],td).returncode==0)
        # 5 CRLF input becomes canonical LF
        crlf=td/"crlf.slg"; crlf.write_bytes(b"a:=1;co[a]\r\n"); p=run([str(native),"fmt",str(crlf),"--write"],td)
        rec("fmt-crlf-normalize",p.returncode==0 and b"\r\n" not in crlf.read_bytes())
        # 6 unicode survives formatting
        uni=td/"unicode.slg"; uni.write_text("co['λ雪']\n",encoding="utf-8"); p=run([str(native),"fmt",str(uni)],td)
        rec("fmt-unicode",p.returncode==0 and "λ雪" in p.stdout)
        # 7 durable comments survive formatting
        rec("fmt-durable-comment", "##! keep" in run([str(native),"fmt",str(src)],td).stdout)
        # 8 write leaves no temp file
        rec("fmt-temp-clean", not Path(str(messy)+".slug-tmp").exists())
        # 9 explicit output protects source
        rec("fmt-overwrite-safety", run([str(native),"fmt",str(src),"-o",str(src)],td).returncode==64)
        # 10 crusher default keeps source
        original=src.read_bytes(); p=run([str(native),"crush",str(src)],td); crushed=src.with_suffix(".slgc")
        rec("crush-source-safe",p.returncode==0 and crushed.is_file() and src.read_bytes()==original)
        # 11 crusher drops ordinary comments, keeps durable
        ct=crushed.read_text(encoding="utf-8") if crushed.exists() else ""
        rec("crush-comment-policy","ordinary" not in ct and "##! keep" in ct)
        # 12 explicit crush overwrite rejected
        rec("crush-overwrite-safety",run([str(native),"crush",str(src),"-o",str(src)],td).returncode==64)
        # 13 crusher temp cleaned
        rec("crush-temp-clean",not Path(str(crushed)+".slug-tmp").exists())
        # 14 expansion to stdout doesn't mutate crushed file
        cb=crushed.read_bytes(); p=run([str(native),"expand",str(crushed)],td)
        rec("expand-stdout-safe",p.returncode==0 and p.stdout.endswith("\n") and crushed.read_bytes()==cb)
        # 15 expansion preserves durable comment
        rec("expand-durable-comment","##! keep" in p.stdout)
        # 16 explicit expansion output
        ex=td/"expanded.slg"; p=run([str(native),"expand",str(crushed),"-o",str(ex)],td)
        rec("expand-output",p.returncode==0 and ex.is_file())
        # 17 explicit expand overwrite rejected
        rec("expand-overwrite-safety",run([str(native),"expand",str(crushed),"-o",str(crushed)],td).returncode==64)
        # 18 crush->expand->crush canonical stability
        rec2=td/"recrushed.slgc"; p=run([str(native),"crush",str(ex),"-o",str(rec2)],td)
        rec("crush-expand-crush-stable",p.returncode==0 and rec2.read_text(encoding="utf-8")==ct)
        # 19 failed transform must not clobber an existing destination
        dest=td/"protected.slg"; dest.write_text("sentinel\n",encoding="utf-8"); missing=td/"missing.slg"
        p=run([str(native),"fmt",str(missing),"-o",str(dest)],td)
        rec("failed-transform-no-clobber",p.returncode!=0 and dest.read_text(encoding="utf-8")=="sentinel\n")
        # 20 machine diagnostic stays one valid schema-1 JSON object
        bad=td/"bad.slg"; bad.write_text("if ? {\n",encoding="utf-8")
        p=run([str(native),"check",str(bad),"--diagnostic-format","json"],td)
        try: obj=json.loads(p.stderr.strip()); ok=p.returncode==65 and obj.get("schema")==1 and obj.get("severity")=="error" and isinstance(obj.get("span"),dict)
        except Exception: ok=False
        rec("diagnostic-json-stable",ok,repr((p.returncode,p.stderr)))

        # 21 tooling capability object must be byte-identical native/reference
        py=run(PYCLI+["tooling-info"],td); na=run([str(native),"tooling-info"],td)
        
        try: tio=json.loads(na.stdout); caps=tio.get('capabilities',{}); tiok=py.returncode==0 and na.returncode==0 and py.stdout==na.stdout and tio.get('schema')==1 and caps.get('stdin_overlay') is True and caps.get('failure_locator') is True and caps.get('semantic_provenance') is True and caps.get('lexical_provenance') is True and caps.get('lsp') is True
        except Exception: tiok=False
        rec("tooling-info-parity",tiok,repr((py.stdout,na.stdout,py.stderr,na.stderr)))
        # 22 project-info no project is a successful found=false handshake
        py=run(PYCLI+["project-info"],td); na=run([str(native),"project-info"],td)
        rec("project-info-absent-parity",py.returncode==0 and na.returncode==0 and py.stdout==na.stdout and json.loads(na.stdout)=={"schema":1,"found":False},repr((py.stdout,na.stdout)))
        # 23 discovered project object native/reference parity
        proj=td/"proj"; (proj/"src").mkdir(parents=True); (proj/"vendor"/"lib").mkdir(parents=True)
        (proj/"slug.json").write_text('{"schema":1,"name":"demo","entry":"src/main.slg","dependencies":{"lib":"vendor/lib"}}\n',encoding="utf-8")
        main=proj/"src"/"main.slg"; main.write_text("co[1]\n",encoding="utf-8")
        py=run(PYCLI+["project-info",str(main.resolve())],td); na=run([str(native),"project-info",str(main.resolve())],td)
        try:
            po=json.loads(py.stdout); no=json.loads(na.stdout)
            # Filesystem paths are platform paths, not URI spellings.  The reference
            # and native implementations may compose equivalent Windows paths with
            # different slash spellings, so compare path identity after native
            # normalization while keeping every non-path field exact.
            path_fields=("manifest","root","entry_path")
            po_paths={k:os.path.normcase(os.path.normpath(po[k])) for k in path_fields}
            no_paths={k:os.path.normcase(os.path.normpath(no[k])) for k in path_fields}
            po_rest={k:v for k,v in po.items() if k not in path_fields}
            no_rest={k:v for k,v in no.items() if k not in path_fields}
            ok=(py.returncode==0 and na.returncode==0 and po_rest==no_rest and
                po_paths==no_paths and no["found"] is True and no["dependency_count"]==1)
        except Exception: ok=False
        rec("project-info-found-parity",ok,repr((py.stdout,na.stdout,py.stderr,na.stderr)))


        # 24 native stdin overlay checks unsaved source without mutating logical file
        overlay=proj/"src"/"overlay.slg"; overlay.write_text("if ? {\n",encoding="utf-8")
        before=overlay.read_bytes(); valid="co[42]\n"
        p=run([str(native),"tooling-check",str(overlay),"--diagnostic-format","json"],td,input_text=valid)
        rec("tooling-check-valid-overlay",p.returncode==0 and overlay.read_bytes()==before,repr((p.returncode,p.stdout,p.stderr)))

        # 25 importer-relative lookup uses the logical document path, not a temp path
        helper=proj/"src"/"helper.slg"; helper.write_text("~tw x {rv x 2 *;}\n",encoding="utf-8")
        unsaved=">'helper.slg':HE\nco[HE.tw[21]]\n"
        p=run([str(native),"tooling-check",str(overlay),"--diagnostic-format","json"],td,input_text=unsaved)
        rec("tooling-check-relative-import",p.returncode==0,repr((p.returncode,p.stdout,p.stderr)))

        # 26 dependency URI lookup also uses project context derived from the logical path
        depdir=proj/"vendor"/"lib"; depdir.mkdir(parents=True,exist_ok=True); (depdir/"api.slg").write_text("~tw x {rv x 3 *;}\n",encoding="utf-8")
        deptext=">'@dep/lib/api.slg':DP\nco[DP.tw[14]]\n"
        p=run([str(native),"tooling-check",str(overlay),"--diagnostic-format","json"],td,input_text=deptext)
        rec("tooling-check-dependency-import",p.returncode==0,repr((p.returncode,p.stdout,p.stderr)))

        # 27 invalid stdin source reports the normal machine diagnostic and still does not mutate disk
        p=run([str(native),"tooling-check",str(overlay),"--diagnostic-format","json"],td,input_text="if ? {\n")
        try: dio=json.loads(p.stderr.strip()); dok=p.returncode==65 and dio.get("schema")==1
        except Exception: dok=False
        rec("tooling-check-invalid-json",dok and overlay.read_bytes()==before,repr((p.returncode,p.stderr)))

        # 28 formatting stdin is source-safe
        p=run([str(native),"tooling-format",str(overlay)],td,input_text="a:=1;co[a]\n")
        rec("tooling-format-overlay",p.returncode==0 and p.stdout.endswith("\n") and overlay.read_bytes()==before,repr((p.returncode,p.stdout,p.stderr)))

        # 29 overlay tooling creates no sibling shadow/temp source files
        debris=list((proj/"src").glob(".*.slug-lsp-*.slg"))+list((proj/"src").glob("*.slug-tmp"))
        rec("tooling-overlay-no-debris",not debris,repr(debris))

        def locate(text):
            q=run([str(native),"tooling-locate",str(overlay)],td,input_text=text)
            return q, q.stdout.replace("\r","").splitlines()

        # 30 valid source has no failure location
        p,lines=locate("co[1]\n")
        rec("tooling-locate-valid-none",p.returncode==0 and lines[:1]==["0"],repr((p.returncode,lines,p.stderr)))

        # 31 unmatched opener localizes the opener, not the historical 1:1 placeholder
        p,lines=locate("a:=1\nco[a]\nif ? {\n")
        rec("tooling-locate-unmatched-opener",p.returncode==0 and lines[:6]==["1","3","6","3","7","{"],repr((p.returncode,lines,p.stderr)))

        # 32 balanced malformed slice assignment advances to the offending '=' token
        p,lines=locate("a[:]=1\n")
        rec("tooling-locate-balanced-invalid",p.returncode==0 and lines[:6]==["1","1","5","1","6","="],repr((p.returncode,lines,p.stderr)))

        # 33 locator retains importer-relative module context on the failure-only pass
        p,lines=locate(">'helper.slg':HE\nco[HE.tw[7]]\nif1{co1}\n")
        rec("tooling-locate-relative-import",p.returncode==0 and lines[:3]==["1","3","3"],repr((p.returncode,lines,p.stderr)))

        # 34 locator is an in-memory error path and leaves source/debris untouched
        debris=list((proj/"src").glob(".*.slug-lsp-*.slg"))+list((proj/"src").glob("*.slug-tmp"))
        rec("tooling-locate-no-debris",overlay.read_bytes()==before and not debris,repr(debris))

        # K9J lexical provenance: point at the illegal source token, not 1:1 by convention.
        p,lines=locate('"bad"\n')
        rec("tooling-locate-lexical-double-quote",p.returncode==0 and lines[:6]==["1","1","1","1","2",'"'],repr((p.returncode,lines,p.stderr)))

        # K9J lexical provenance remains line/column exact after preceding valid source.
        p,lines=locate("a:=1\n€\n")
        rec("tooling-locate-lexical-unicode",p.returncode==0 and lines[:5]==["1","2","1","2","2"],repr((p.returncode,lines,p.stderr)))

        # K9J semantic provenance replays only after parse success and finds the failing statement.
        p,lines=locate("a:=1\nbl\n")
        rec("tooling-locate-semantic-break",p.returncode==0 and lines[:5]==["1","2","1","2","2"],repr((p.returncode,lines,p.stderr)))

        p,lines=locate("a:=1\nrv\n")
        rec("tooling-locate-semantic-return",p.returncode==0 and lines[:5]==["1","2","1","2","2"],repr((p.returncode,lines,p.stderr)))

        p,lines=locate("?1{bl}\n")
        rec("tooling-locate-semantic-nested-break",p.returncode==0 and lines[:5]==["1","1","4","1","5"],repr((p.returncode,lines,p.stderr)))

        p,lines=locate("~ab{>'x.slg';rv}\n")
        rec("tooling-locate-semantic-nested-import",p.returncode==0 and lines[:5]==["1","1","5","1","6"],repr((p.returncode,lines,p.stderr)))

    if failures:
        print(f"K9J TOOLING FAIL {passed}/{total}",file=sys.stderr)
        for f in failures: print(" - "+f,file=sys.stderr)
        return 1
    print(f"K9J TOOLING PASS {passed}/{total}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

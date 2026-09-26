#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path

def need(c, label):
    if not c: raise SystemExit(f'FAIL: {label}')

def main()->int:
    root=Path(__file__).resolve().parents[1]
    layout=json.loads((root/'INSTALL_LAYOUT.json').read_text())
    public=json.loads((root/'PUBLIC_CONTRACT.json').read_text())
    std=json.loads((root/'distribution/std/registry.json').read_text())
    need(layout.get('schema')==1,'install layout schema')
    need(layout.get('language_version')==public.get('language_version')=='1.0','language version agreement')
    need(layout.get('runtime_support')=='lib/slug/1.0/runtime_stage2.c','versioned runtime location')
    need(layout.get('shared_root')=='share/slug/1.0','versioned shared root')
    need(layout.get('lsp_server')=='share/slug/1.0/tooling/slug-lsp.js','versioned LSP server location')
    need(layout.get('lsp_launcher')=='bin/slug-lsp','LSP launcher stem')
    need(layout.get('vscode_extension')=='share/slug/1.0/tooling/vscode/slug-language.vsix','versioned VS Code extension location')
    need(layout.get('license')=='share/slug/1.0/LICENSE','installed license location')
    need(layout.get('security')=='share/slug/1.0/SECURITY.md','installed security note location')
    need(layout.get('readme')=='share/slug/1.0/README.md','installed readme location')
    need(layout.get('examples')=='share/slug/1.0/examples','installed examples location')
    need(std.get('schema')==1 and std.get('language_version')=='1.0','std registry schema/version')
    need(std.get('implementation')=='host-capability','std implementation kind')
    need(std.get('modules')==public.get('standard_modules'),'exact std registry surface')
    pc=layout['project_convention']
    need(pc.get('source_root')=='src' and pc.get('conventional_entry')=='src/main.slg','project source/entry convention')
    need(pc.get('manifest_required') is False and pc.get('entry_must_be_explicit') is False,'manifest/explicit-entry compatibility')
    need(pc.get('manifest_name')=='slug.json' and pc.get('manifest_schema')==1,'project manifest identity')
    need(pc.get('project_command_discovery')=='upward-from-current-directory','project command discovery')
    need(pc.get('explicit_source_manifest_discovery')=='upward-from-source-file','explicit source manifest discovery')
    need(pc.get('dependency_uri_prefix')=='@dep/' and pc.get('dependency_resolution')=='root-manifest-local-relative-root-exact-source','dependency resolution contract')
    need(pc.get('network_dependency_resolution') is False and pc.get('implicit_source_suffix') is False,'deterministic local dependency policy')
    need(pc.get('source_import_resolution')=='relative-to-importing-file','relative source import rule')
    need(pc.get('standard_module_resolution')=='compiler-distribution-reserved-uri','reserved std rule')
    app=(root/'compiler/stage2/app.slg').read_text()
    need("../lib/slug/1.0/runtime_stage2.c" in app,'native compiler versioned runtime lookup')
    print(json.dumps({'status':'PASS','language_version':'1.0','install_schema':1,'std_modules':len(std['modules']),'project_entry':'src/main.slg'}))
    return 0
if __name__=='__main__': raise SystemExit(main())

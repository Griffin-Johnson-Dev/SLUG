#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, zipfile
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

FILES = [
    'package.json', 'extension.js', 'language-configuration.json',
    'README.md', 'CHANGELOG.md', 'icon.png',
    'src/discovery.js', 'src/lsp-client.js',
    'syntaxes/slug.tmLanguage.json',
]

def content_types():
    return '''<?xml version="1.0" encoding="utf-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n  <Default Extension="json" ContentType="application/json" />\n  <Default Extension="js" ContentType="application/javascript" />\n  <Default Extension="md" ContentType="text/markdown" />\n  <Default Extension="txt" ContentType="text/plain" />\n  <Default Extension="vsixmanifest" ContentType="text/xml" />\n</Types>\n'''

def manifest(pkg: dict):
    name = escape(pkg['name']); display = escape(pkg.get('displayName', pkg['name']))
    desc = escape(pkg.get('description', '')); version = escape(pkg['version']); publisher = escape(pkg['publisher'])
    engine = escape(pkg['engines']['vscode'])
    cats = ','.join(pkg.get('categories', [])); tags = ','.join(pkg.get('keywords', []))
    return f'''<?xml version="1.0" encoding="utf-8"?>\n<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011" xmlns:d="http://schemas.microsoft.com/developer/vsx-schema-design/2011">\n  <Metadata>\n    <Identity Language="en-US" Id={quoteattr(name)} Version={quoteattr(version)} Publisher={quoteattr(publisher)} />\n    <DisplayName>{display}</DisplayName>\n    <Description xml:space="preserve">{desc}</Description>\n    <Tags>{escape(tags)}</Tags>\n    <Categories>{escape(cats)}</Categories>\n    <GalleryFlags>Public</GalleryFlags>\n    <Properties>\n      <Property Id="Microsoft.VisualStudio.Code.Engine" Value={quoteattr(engine)} />\n      <Property Id="Microsoft.VisualStudio.Code.PreRelease" Value="false" />\n      <Property Id="Microsoft.VisualStudio.Code.ExecutesCode" Value="true" />\n      <Property Id="Microsoft.VisualStudio.Services.Content.Pricing" Value="Free" />\n    </Properties>\n  </Metadata>\n  <Installation><InstallationTarget Id="Microsoft.VisualStudio.Code" /></Installation>\n  <Dependencies />\n  <Assets>\n    <Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json" Addressable="true" />\n    <Asset Type="Microsoft.VisualStudio.Services.Content.Details" Path="extension/README.md" Addressable="true" />\n    <Asset Type="Microsoft.VisualStudio.Services.Content.Changelog" Path="extension/CHANGELOG.md" Addressable="true" />\n    <Asset Type="Microsoft.VisualStudio.Services.Icons.Default" Path="extension/icon.png" Addressable="true" />\n  </Assets>\n</PackageManifest>\n'''

def add_bytes(zf, name, data):
    zi = zipfile.ZipInfo(name, date_time=(1980,1,1,0,0,0))
    zi.compress_type = zipfile.ZIP_DEFLATED
    zi.external_attr = 0o100644 << 16
    zf.writestr(zi, data)

def build(root: Path, out: Path):
    ext = root/'tooling'/'vscode'
    pkg = json.loads((ext/'package.json').read_text(encoding='utf-8'))
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, 'w') as zf:
        add_bytes(zf, '[Content_Types].xml', content_types().encode())
        add_bytes(zf, 'extension.vsixmanifest', manifest(pkg).encode())
        for rel in FILES:
            p = ext/rel
            if not p.is_file(): raise SystemExit(f'missing extension file: {p}')
            add_bytes(zf, 'extension/'+rel.replace('\\','/'), p.read_bytes())
        add_bytes(zf, 'extension/LICENSE.txt', (root/'LICENSE').read_bytes())
    return out

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    ap.add_argument('--out', type=Path)
    a=ap.parse_args(); root=a.root.resolve()
    out=(a.out or root/'tooling'/'vscode'/'slug-language.vsix').resolve()
    build(root,out); print(out)
if __name__=='__main__': main()

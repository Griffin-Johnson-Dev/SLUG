'use strict';
const fs = require('fs');
const os = require('os');
const path = require('path');
const { discoverServer, deriveServerJsFromCompiler } = require('../src/discovery');
function touch(p) { fs.mkdirSync(path.dirname(p), { recursive: true }); fs.writeFileSync(p, '', 'utf8'); }
function must(cond, msg) { if (!cond) throw new Error(msg); }
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'slug-discovery-k9h-'));
try {
  const prefix = path.join(root, 'prefix');
  const slug = path.join(prefix, 'bin', 'slug');
  const server = path.join(prefix, 'share', 'slug', '1.0', 'tooling', 'slug-lsp.js');
  touch(slug); touch(server);
  must(deriveServerJsFromCompiler(slug) === server, 'derive server from compiler');
  let s = discoverServer({ compilerPath: slug, env: { PATH: '' }, platform: 'linux', electronExecutable: '/electron' });
  must(s.mode === 'node-js' && s.command === '/electron' && s.serverPath === server && s.compilerPath === slug, 'compiler-derived discovery');
  s = discoverServer({ lspPath: server, compilerPath: slug, env: { PATH: '' }, platform: 'linux', electronExecutable: '/electron' });
  must(s.mode === 'node-js' && s.args[0] === server, 'explicit js discovery');

  const winPrefix = path.join(root, 'win');
  const winSlug = path.join(winPrefix, 'bin', 'slug.exe');
  const winLauncher = path.join(winPrefix, 'bin', 'slug-lsp.cmd');
  const winServer = path.join(winPrefix, 'share', 'slug', '1.0', 'tooling', 'slug-lsp.js');
  touch(winSlug); touch(winLauncher); touch(winServer);
  s = discoverServer({ lspPath: winLauncher, compilerPath: winSlug, env: { PATH: '' }, platform: 'win32', electronExecutable: 'Code.exe' });
  must(s.mode === 'node-js' && s.serverPath === winServer && s.command === 'Code.exe', 'windows launcher upgraded to bundled js');

  // Exercise Windows PATH discovery with Windows executable naming/path-list rules.
  // This is intentionally separate from the host-native case below so the smoke
  // covers `slug.exe` even when the test itself is running on POSIX.
  s = discoverServer({ env: { PATH: path.join(winPrefix, 'bin') }, platform: 'win32', electronExecutable: 'Code.exe' });
  must(s.serverPath === winServer && s.compilerPath === winSlug, 'Windows PATH compiler discovery');

  // PATH fixtures must use the path syntax of the host they physically live on.
  // A previous smoke forced platform='linux' around a real `C:\...` temp path;
  // Linux ':' splitting then split the Windows drive designator and made a valid
  // installation undiscoverable.
  const pathPrefix = path.join(root, 'path');
  const hostSlugName = process.platform === 'win32' ? 'slug.exe' : 'slug';
  const pathSlug = path.join(pathPrefix, 'bin', hostSlugName);
  const pathServer = path.join(pathPrefix, 'share', 'slug', '1.0', 'tooling', 'slug-lsp.js');
  touch(pathSlug); touch(pathServer);
  s = discoverServer({ env: { PATH: path.join(pathPrefix, 'bin') }, platform: process.platform, electronExecutable: process.execPath });
  must(s.serverPath === pathServer && s.compilerPath === pathSlug, 'host PATH compiler discovery');

  let failed = false;
  try { discoverServer({ env: { PATH: '' }, platform: process.platform }); } catch (_) { failed = true; }
  must(failed, 'missing installation must fail');
  process.stdout.write('SLUG DISCOVERY SMOKE PASS\n');
} finally { fs.rmSync(root, { recursive: true, force: true }); }

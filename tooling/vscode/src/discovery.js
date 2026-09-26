'use strict';

const fs = require('fs');
const path = require('path');

function isFile(p) {
  try { return fs.statSync(p).isFile(); } catch (_) { return false; }
}

function executableNames(stem, platform = process.platform) {
  if (platform === 'win32') return [`${stem}.exe`, `${stem}.cmd`, `${stem}.bat`, stem];
  return [stem];
}

function resolveOnPath(command, env = process.env, platform = process.platform) {
  if (!command) return null;
  if (path.isAbsolute(command) || command.includes('/') || command.includes('\\')) {
    return isFile(command) ? path.resolve(command) : null;
  }
  const rawPath = env.PATH || env.Path || env.path || '';
  const delimiter = platform === 'win32' ? ';' : ':';
  const dirs = rawPath.split(delimiter).filter(Boolean);
  const names = platform === 'win32' && !path.extname(command)
    ? executableNames(command, platform)
    : [command];
  for (const dir of dirs) {
    for (const name of names) {
      const p = path.join(dir, name);
      if (isFile(p)) return p;
    }
  }
  return null;
}

function deriveServerJsFromCompiler(compilerPath) {
  if (!compilerPath || !path.isAbsolute(compilerPath)) return null;
  const binDir = path.dirname(compilerPath);
  const prefix = path.dirname(binDir);
  const candidate = path.join(prefix, 'share', 'slug', '1.0', 'tooling', 'slug-lsp.js');
  return isFile(candidate) ? candidate : null;
}

function deriveServerJsFromLauncher(launcherPath) {
  if (!launcherPath || !path.isAbsolute(launcherPath)) return null;
  const binDir = path.dirname(launcherPath);
  const prefix = path.dirname(binDir);
  const candidate = path.join(prefix, 'share', 'slug', '1.0', 'tooling', 'slug-lsp.js');
  return isFile(candidate) ? candidate : null;
}

function nodeServerSpec(serverJs, compiler, electronExecutable = process.execPath, env = process.env) {
  return {
    command: electronExecutable,
    args: [serverJs, '--slug', compiler || 'slug'],
    options: {
      env: { ...env, ELECTRON_RUN_AS_NODE: '1' },
      windowsHide: true,
      stdio: ['pipe', 'pipe', 'pipe'],
    },
    serverPath: serverJs,
    compilerPath: compiler || 'slug',
    mode: 'node-js',
  };
}

function directServerSpec(serverPath, compiler, env = process.env, platform = process.platform) {
  const isCmd = platform === 'win32' && /\.(?:cmd|bat)$/i.test(serverPath);
  return {
    command: serverPath,
    args: compiler ? ['--slug', compiler] : [],
    options: {
      env: { ...env },
      windowsHide: true,
      stdio: ['pipe', 'pipe', 'pipe'],
      ...(isCmd ? { shell: true } : {}),
    },
    serverPath,
    compilerPath: compiler || 'slug',
    mode: 'launcher',
  };
}

function discoverServer({
  lspPath = '',
  compilerPath = '',
  env = process.env,
  platform = process.platform,
  electronExecutable = process.execPath,
} = {}) {
  let compiler = null;
  if (compilerPath) compiler = resolveOnPath(compilerPath, env, platform);
  if (!compiler) compiler = resolveOnPath('slug', env, platform);
  if (!compiler && compilerPath) throw new Error(`SLUG compiler not found: ${compilerPath}`);

  if (lspPath) {
    const explicit = resolveOnPath(lspPath, env, platform);
    if (!explicit) throw new Error(`SLUG language server not found: ${lspPath}`);
    if (/\.js$/i.test(explicit)) return nodeServerSpec(explicit, compiler || compilerPath || 'slug', electronExecutable, env);
    const adjacentJs = deriveServerJsFromLauncher(explicit);
    if (adjacentJs) return nodeServerSpec(adjacentJs, compiler || compilerPath || 'slug', electronExecutable, env);
    return directServerSpec(explicit, compiler || compilerPath || null, env, platform);
  }

  const serverFromCompiler = deriveServerJsFromCompiler(compiler);
  if (serverFromCompiler) return nodeServerSpec(serverFromCompiler, compiler, electronExecutable, env);

  const launchers = executableNames('slug-lsp', platform);
  for (const name of launchers) {
    const launcher = resolveOnPath(name, env, platform);
    if (!launcher) continue;
    const adjacentJs = deriveServerJsFromLauncher(launcher);
    if (adjacentJs) return nodeServerSpec(adjacentJs, compiler || 'slug', electronExecutable, env);
    return directServerSpec(launcher, compiler, env, platform);
  }

  throw new Error('SLUG language server not found. Install SLUG 1.0 or configure slug.lspPath / slug.compilerPath.');
}

module.exports = {
  discoverServer,
  deriveServerJsFromCompiler,
  deriveServerJsFromLauncher,
  executableNames,
  resolveOnPath,
};

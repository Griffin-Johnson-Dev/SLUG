'use strict';

const { EventEmitter } = require('events');
const { spawn } = require('child_process');

class LspClient extends EventEmitter {
  constructor(spec, { trace = null, requestTimeoutMs = 15000 } = {}) {
    super();
    this.spec = spec;
    this.trace = trace;
    this.requestTimeoutMs = requestTimeoutMs;
    this.child = null;
    this.buffer = Buffer.alloc(0);
    this.nextId = 1;
    this.pending = new Map();
    this.closed = false;
  }

  start() {
    if (this.child) return;
    this.child = spawn(this.spec.command, this.spec.args || [], this.spec.options || {});
    this.child.stdout.on('data', (chunk) => this._onData(chunk));
    this.child.stderr.on('data', (chunk) => this.emit('stderr', chunk.toString('utf8')));
    this.child.on('error', (err) => this._failAll(err));
    this.child.on('exit', (code, signal) => {
      this.closed = true;
      const err = new Error(`slug-lsp exited (${code === null ? signal : code})`);
      this._failAll(err);
      this.emit('exit', code, signal);
    });
  }

  _log(direction, payload) {
    if (this.trace) this.trace(direction, payload);
  }

  _write(payload) {
    if (!this.child || this.closed) throw new Error('slug-lsp is not running');
    this._log('send', payload);
    const body = Buffer.from(JSON.stringify(payload), 'utf8');
    const header = Buffer.from(`Content-Length: ${body.length}\r\n\r\n`, 'ascii');
    this.child.stdin.write(Buffer.concat([header, body]));
  }

  notify(method, params) {
    this._write({ jsonrpc: '2.0', method, params });
  }

  request(method, params, timeoutMs = this.requestTimeoutMs) {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`LSP request timed out: ${method}`));
      }, timeoutMs);
      this.pending.set(id, { resolve, reject, timer, method });
      try { this._write({ jsonrpc: '2.0', id, method, params }); }
      catch (e) {
        clearTimeout(timer);
        this.pending.delete(id);
        reject(e);
      }
    });
  }

  _onData(chunk) {
    this.buffer = Buffer.concat([this.buffer, Buffer.from(chunk)]);
    while (true) {
      const sep = this.buffer.indexOf('\r\n\r\n');
      if (sep < 0) return;
      const header = this.buffer.subarray(0, sep).toString('ascii');
      const match = /(?:^|\r\n)Content-Length:\s*(\d+)/i.exec(header);
      if (!match) {
        this.buffer = this.buffer.subarray(sep + 4);
        continue;
      }
      const length = Number(match[1]);
      const start = sep + 4;
      if (this.buffer.length < start + length) return;
      const body = this.buffer.subarray(start, start + length).toString('utf8');
      this.buffer = this.buffer.subarray(start + length);
      let msg;
      try { msg = JSON.parse(body); }
      catch (e) { this.emit('protocolError', e); continue; }
      this._log('recv', msg);
      this._dispatch(msg);
    }
  }

  _dispatch(msg) {
    if (Object.prototype.hasOwnProperty.call(msg, 'id') && (Object.prototype.hasOwnProperty.call(msg, 'result') || msg.error)) {
      const p = this.pending.get(msg.id);
      if (!p) return;
      clearTimeout(p.timer);
      this.pending.delete(msg.id);
      if (msg.error) p.reject(new Error(msg.error.message || `LSP error ${msg.error.code}`));
      else p.resolve(msg.result);
      return;
    }
    if (msg.method) this.emit('notification', msg.method, msg.params);
  }

  _failAll(err) {
    for (const [, p] of this.pending) {
      clearTimeout(p.timer);
      p.reject(err);
    }
    this.pending.clear();
  }

  async stop() {
    if (!this.child || this.closed) return;
    try { await this.request('shutdown', null, 5000); } catch (_) {}
    try { this.notify('exit', null); } catch (_) {}
    await new Promise((resolve) => {
      const timer = setTimeout(() => {
        try { this.child.kill(); } catch (_) {}
        resolve();
      }, 2000);
      this.child.once('exit', () => { clearTimeout(timer); resolve(); });
    });
  }
}

module.exports = { LspClient };

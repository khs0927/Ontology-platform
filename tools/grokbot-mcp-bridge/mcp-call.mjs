#!/usr/bin/env node
// grokbot-mcp-bridge: spawn a locally configured stdio MCP server, handshake,
// list tools or call one tool, print JSON, exit. No npm dependencies.
import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath } from 'node:url';

const HOME = os.homedir();
const APPDATA = process.env.APPDATA || path.join(HOME, 'AppData', 'Roaming');
const LOCALAPPDATA = process.env.LOCALAPPDATA || path.join(HOME, 'AppData', 'Local');
const IS_WIN = process.platform === 'win32';

const CONFIGS = [
  { source: 'cursor', file: path.join(HOME, '.cursor', 'mcp.json'), kind: 'json' },
  { source: 'claude', file: path.join(APPDATA, 'Claude', 'claude_desktop_config.json'), kind: 'json' },
  { source: 'codex', file: path.join(HOME, '.codex', 'config.toml'), kind: 'toml' },
];
const SOURCE_ORDER = ['cursor', 'claude', 'codex', 'manual'];

// ---------------------------------------------------------------- utils
let OUT_OPTS = { ascii: false, file: null };
function out(obj) {
  let text = JSON.stringify(obj, null, 2);
  if (OUT_OPTS.ascii) text = text.replace(/[\u007f-\uffff]/g, c => '\\u' + c.charCodeAt(0).toString(16).padStart(4, '0'));
  if (OUT_OPTS.file) { fs.writeFileSync(OUT_OPTS.file, text + '\n', 'utf8'); process.stdout.write(JSON.stringify({ written: OUT_OPTS.file, bytes: Buffer.byteLength(text), ...(obj.error ? { error: obj.error, stage: obj.stage } : {}) }) + '\n'); }
  else process.stdout.write(text + '\n');
}
function fail(error, stage, extra = {}) {
  out({ error: String(error), stage, ...extra });
  process.exitCode = 1;
}
function readText(file) {
  const buf = fs.readFileSync(file);
  let b = buf;
  if (b[0] === 0xef && b[1] === 0xbb && b[2] === 0xbf) b = b.subarray(3);
  try { return new TextDecoder('utf-8', { fatal: true }).decode(b); }
  catch {
    // Some configs on Korean Windows are saved as CP949/EUC-KR.
    try { return new TextDecoder('euc-kr').decode(b); } catch { return b.toString('utf8'); }
  }
}
function parseArgv(argv) {
  const pos = []; const opt = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith('--')) {
      const eq = a.indexOf('=');
      if (eq > 0) { opt[a.slice(2, eq)] = a.slice(eq + 1); continue; }
      const k = a.slice(2);
      const next = argv[i + 1];
      if (['verbose', 'brief', 'show-secrets', 'all', 'ascii'].includes(k)) { opt[k] = true; continue; }
      if (next === undefined) { opt[k] = true; continue; }
      if (k === 'env') { (opt.env ||= []).push(next); i++; continue; }
      opt[k] = next; i++;
    } else pos.push(a);
  }
  return { pos, opt };
}

// ---------------------------------------------------------------- tiny TOML
// Supports: [table] / [a.b."c d"] headers, key = 'lit' | "basic" | number | bool |
// [arrays of those, possibly multi-line]. Enough for codex config.toml.
function splitKeyPath(s) {
  const parts = []; let i = 0; s = s.trim();
  while (i < s.length) {
    while (s[i] === ' ' || s[i] === '\t') i++;
    if (s[i] === '"' || s[i] === "'") {
      const q = s[i]; let j = i + 1; let v = '';
      while (j < s.length && s[j] !== q) { if (q === '"' && s[j] === '\\') { v += s[j + 1]; j += 2; continue; } v += s[j++]; }
      parts.push(v); i = j + 1;
    } else {
      let j = i; while (j < s.length && s[j] !== '.') j++;
      parts.push(s.slice(i, j).trim()); i = j;
    }
    while (s[i] === ' ' || s[i] === '\t') i++;
    if (s[i] === '.') i++;
  }
  return parts;
}
function parseTomlValue(s, pos) {
  // returns [value, newPos]
  const skipWs = () => { while (pos < s.length && /[\s]/.test(s[pos])) pos++; };
  const skipWsC = () => { for (;;) { skipWs(); if (s[pos] === '#') { while (pos < s.length && s[pos] !== '\n') pos++; } else break; } };
  skipWs();
  const c = s[pos];
  if (c === "'") {
    if (s.startsWith("'''", pos)) { const e = s.indexOf("'''", pos + 3); return [s.slice(pos + 3, e).replace(/^\r?\n/, ''), e + 3]; }
    const e = s.indexOf("'", pos + 1); return [s.slice(pos + 1, e), e + 1];
  }
  if (c === '"') {
    const triple = s.startsWith('"""', pos); let j = pos + (triple ? 3 : 1); let v = '';
    while (j < s.length) {
      if (triple ? s.startsWith('"""', j) : s[j] === '"') break;
      if (s[j] === '\\') {
        const n = s[j + 1]; const map = { n: '\n', t: '\t', r: '\r', '"': '"', '\\': '\\', b: '\b', f: '\f' };
        if (n === 'u' || n === 'U') { const len = n === 'u' ? 4 : 8; v += String.fromCodePoint(parseInt(s.substr(j + 2, len), 16)); j += 2 + len; continue; }
        v += map[n] ?? n; j += 2; continue;
      }
      v += s[j++];
    }
    return [triple ? v.replace(/^\r?\n/, '') : v, j + (triple ? 3 : 1)];
  }
  if (c === '[') {
    pos++; const arr = [];
    for (;;) {
      skipWsC();
      if (s[pos] === ']') { pos++; break; }
      const [v, p] = parseTomlValue(s, pos); arr.push(v); pos = p;
      skipWsC();
      if (s[pos] === ',') pos++;
      else if (s[pos] === ']') { pos++; break; }
      else if (pos >= s.length) break;
    }
    return [arr, pos];
  }
  if (c === '{') {
    pos++; const obj = {};
    for (;;) {
      skipWs(); if (s[pos] === '}') { pos++; break; }
      let e = pos; while (e < s.length && s[e] !== '=') e++;
      const keyPath = splitKeyPath(s.slice(pos, e)); pos = e + 1;
      const [v, p] = parseTomlValue(s, pos); pos = p;
      let o = obj; for (let k = 0; k < keyPath.length - 1; k++) o = (o[keyPath[k]] ??= {});
      o[keyPath[keyPath.length - 1]] = v;
      skipWs(); if (s[pos] === ',') pos++;
    }
    return [obj, pos];
  }
  let e = pos; while (e < s.length && !/[,\]\}\r\n#]/.test(s[e])) e++;
  const raw = s.slice(pos, e).trim();
  let v = raw;
  if (raw === 'true') v = true; else if (raw === 'false') v = false;
  else if (/^[+-]?\d[\d_]*(\.\d+)?([eE][+-]?\d+)?$/.test(raw)) v = Number(raw.replace(/_/g, ''));
  return [v, e];
}
function parseToml(text) {
  const root = {}; let cur = root; let pos = 0; const s = text.replace(/\r\n/g, '\n');
  while (pos < s.length) {
    // line start
    while (pos < s.length && /[ \t\n]/.test(s[pos])) pos++;
    if (pos >= s.length) break;
    if (s[pos] === '#') { while (pos < s.length && s[pos] !== '\n') pos++; continue; }
    if (s[pos] === '[') {
      const arrTable = s[pos + 1] === '[';
      const end = s.indexOf(arrTable ? ']]' : ']', pos);
      // header may contain quoted ']' - handle simply by scanning quotes
      let j = pos + (arrTable ? 2 : 1); let inQ = null;
      for (; j < s.length; j++) { const ch = s[j]; if (inQ) { if (ch === inQ) inQ = null; } else if (ch === '"' || ch === "'") inQ = ch; else if (ch === ']') break; }
      const header = s.slice(pos + (arrTable ? 2 : 1), j);
      const keys = splitKeyPath(header);
      let o = root;
      for (let k = 0; k < keys.length; k++) {
        if (arrTable && k === keys.length - 1) { o[keys[k]] ??= []; const n = {}; o[keys[k]].push(n); o = n; }
        else { if (typeof o[keys[k]] !== 'object' || o[keys[k]] === null) o[keys[k]] = {}; o = Array.isArray(o[keys[k]]) ? o[keys[k]][o[keys[k]].length - 1] : o[keys[k]]; }
      }
      cur = o; pos = (arrTable ? j + 2 : j + 1); void end;
      while (pos < s.length && s[pos] !== '\n') pos++;
      continue;
    }
    // key = value
    let e = pos; let inQ = null;
    for (; e < s.length; e++) { const ch = s[e]; if (inQ) { if (ch === inQ) inQ = null; } else if (ch === '"' || ch === "'") inQ = ch; else if (ch === '=' || ch === '\n') break; }
    if (s[e] !== '=') { pos = e + 1; continue; }
    const keyPath = splitKeyPath(s.slice(pos, e));
    let v, p;
    try { [v, p] = parseTomlValue(s, e + 1); } catch { v = null; p = s.indexOf('\n', e); }
    let o = cur; for (let k = 0; k < keyPath.length - 1; k++) o = (o[keyPath[k]] ??= {});
    o[keyPath[keyPath.length - 1]] = v;
    pos = p; while (pos < s.length && s[pos] !== '\n') pos++;
  }
  return root;
}

// ---------------------------------------------------------------- config loading
function findHorizun() {
  const base = path.join(LOCALAPPDATA, 'Programs', 'Horizun');
  if (!fs.existsSync(base)) return null;
  const hits = [];
  const walk = (d, depth) => {
    if (depth > 4) return;
    let ents = []; try { ents = fs.readdirSync(d, { withFileTypes: true }); } catch { return; }
    for (const e of ents) {
      const p = path.join(d, e.name);
      if (e.isDirectory()) walk(p, depth + 1);
      else if (/^horizun.*mcp.*\.exe$|mcp.*server.*\.exe$/i.test(e.name)) hits.push(p);
    }
  };
  walk(base, 0);
  hits.sort((a, b) => (/horizun-mcp\.exe$/i.test(b) ? 1 : 0) - (/horizun-mcp\.exe$/i.test(a) ? 1 : 0));
  return hits[0] || null;
}

function loadServers() {
  const list = []; const warnings = [];
  for (const cfg of CONFIGS) {
    if (!fs.existsSync(cfg.file)) { warnings.push({ source: cfg.source, file: cfg.file, warning: 'config not found' }); continue; }
    let servers = {};
    try {
      const text = readText(cfg.file);
      if (cfg.kind === 'json') servers = JSON.parse(text).mcpServers || {};
      else servers = parseToml(text).mcp_servers || {};
    } catch (e) { warnings.push({ source: cfg.source, file: cfg.file, warning: 'parse error: ' + e.message }); continue; }
    for (const [name, def] of Object.entries(servers)) {
      if (!def || typeof def !== 'object') continue;
      const url = def.url || def.serverUrl || (def.type && /http|sse/i.test(def.type) ? def.url : undefined);
      list.push({
        name, source: cfg.source, configFile: cfg.file, configDir: path.dirname(cfg.file),
        command: def.command, args: Array.isArray(def.args) ? def.args.map(String) : [],
        env: def.env && typeof def.env === 'object' ? def.env : {},
        cwd: def.cwd || undefined,
        url, remote: !!url && !def.command,
        disabled: def.disabled === true || def.enabled === false,
      });
    }
  }
  const hz = findHorizun();
  if (hz) list.push({ name: 'horizun-revit', source: 'manual', configFile: null, configDir: path.dirname(hz), command: hz, args: [], env: {}, cwd: path.dirname(hz), remote: false, disabled: false });
  // assign ids: bare name for first match in source order, source:name always available
  const sorted = [...list].sort((a, b) => SOURCE_ORDER.indexOf(a.source) - SOURCE_ORDER.indexOf(b.source));
  const seen = new Map();
  for (const s of sorted) {
    s.qualifiedId = `${s.source}:${s.name}`;
    const key = s.name.toLowerCase();
    if (!seen.has(key)) { seen.set(key, s); s.id = s.name; } else { s.id = s.qualifiedId; s.shadowedBy = seen.get(key).qualifiedId; }
  }
  return { servers: sorted, warnings };
}

// Bridge-local overrides (never touches the user's MCP configs):
// overrides.json next to this script: { "<qualifiedId or name>": { "cwd": "...", "env": {...}, "timeout": 120000 } }
function loadOverrides() {
  const f = path.join(path.dirname(fileURLToPath(import.meta.url)), 'overrides.json');
  try { return JSON.parse(readText(f)); } catch { return {}; }
}
function applyOverrides(s) {
  const ov = loadOverrides();
  const o = ov[s.qualifiedId] || ov[s.id] || ov[s.name];
  if (!o) return s;
  if (o.cwd) s.cwd = o.cwd;
  if (o.env) s.env = { ...s.env, ...o.env };
  if (Array.isArray(o.args)) s.args = o.args.map(String);
  if (o.command) s.command = o.command;
  if (o.timeout) s.defaultTimeout = Number(o.timeout);
  return s;
}

function resolveServer(servers, ref) {
  const lc = ref.toLowerCase();
  return servers.find(s => s.qualifiedId.toLowerCase() === lc)
    || servers.find(s => s.id.toLowerCase() === lc)
    || servers.find(s => s.name.toLowerCase() === lc);
}

// ---------------------------------------------------------------- redaction
const SECRET_NAME = /(key|token|secret|passw|pwd|auth|credential|cookie|session|_OC$)/i;
const SECRET_FLAG = /^--?(key|api[-_]?key|token|access[-_]?token|secret|password|auth)$/i;
function redactJsonish(v) {
  if (Array.isArray(v)) return v.map(redactJsonish);
  if (v && typeof v === 'object') { const o = {}; for (const [k, x] of Object.entries(v)) o[k] = SECRET_NAME.test(k) && typeof x !== 'object' ? '<redacted>' : redactJsonish(x); return o; }
  return v;
}
function redactStr(s) {
  return String(s)
    .replace(/([?&](?:api[_-]?key|key|token|access_token|secret|sig)=)[^&\s"]+/gi, '$1<redacted>')
    .replace(/\b(sk-|ghp_|gho_|github_pat_|hf_|xox[abp]-|dp\.pt\.|AIza)[A-Za-z0-9_\-\.]{8,}/g, '<redacted>');
}
function redactArgs(args) {
  const outA = [];
  for (let i = 0; i < args.length; i++) {
    const a = args[i];
    const m = /^(--?[A-Za-z][\w-]*)=(.*)$/.exec(a);
    if (m && SECRET_FLAG.test(m[1])) { outA.push(`${m[1]}=<redacted>`); continue; }
    if (SECRET_FLAG.test(a) && i + 1 < args.length) { outA.push(a, '<redacted>'); i++; continue; }
    const t = a.trim();
    if ((t.startsWith('{') && t.endsWith('}')) || (t.startsWith('[') && t.endsWith(']'))) {
      try { outA.push(JSON.stringify(redactJsonish(JSON.parse(t)))); continue; } catch { /* fallthrough */ }
    }
    outA.push(redactStr(a));
  }
  return outA;
}
function redactEnv(env) {
  const o = {};
  for (const [k, v] of Object.entries(env || {})) o[k] = SECRET_NAME.test(k) ? '<redacted>' : redactStr(v);
  return o;
}

// ---------------------------------------------------------------- spawning
function which(cmd) {
  if (!cmd) return null;
  const hasDir = /[\\/]/.test(cmd);
  const exts = IS_WIN ? (process.env.PATHEXT || '.COM;.EXE;.BAT;.CMD').split(';').filter(Boolean) : [''];
  const tryFile = (p) => {
    if (IS_WIN) {
      if (path.extname(p) && fs.existsSync(p) && fs.statSync(p).isFile()) return p;
      for (const e of exts) { const q = p + e; if (fs.existsSync(q)) return q; }
      return null;
    }
    return fs.existsSync(p) ? p : null;
  };
  if (hasDir || path.isAbsolute(cmd)) return tryFile(cmd);
  for (const dir of (process.env.PATH || '').split(path.delimiter)) {
    if (!dir) continue; const r = tryFile(path.join(dir.replace(/"/g, ''), cmd)); if (r) return r;
  }
  return null;
}
function winQuote(a) {
  if (a === '') return '""';
  if (!/[\s"&|<>^()%!,;]/.test(a)) return a;
  return '"' + a.replace(/(\\*)"/g, '$1$1\\"').replace(/(\\+)$/, '$1$1') + '"';
}

function buildSpawn(s) {
  const baseDir = s.cwd || s.configDir || HOME;
  let command = s.command; let args = [...s.args];
  // "dart mcp-server --flag" style command strings
  if (command && !which(command) && /\s/.test(command) && !fs.existsSync(command)) {
    const parts = command.split(/\s+/); command = parts[0]; args = [...parts.slice(1), ...args];
  }
  // resolve relative path-like args against cwd/config dir
  args = args.map(a => {
    if (a.startsWith('-') || path.isAbsolute(a) || !/[\\/]/.test(a) || /^[a-z]+:\/\//i.test(a)) return a;
    const p = path.resolve(baseDir, a); return fs.existsSync(p) ? p : a;
  });
  const cwd = fs.existsSync(baseDir) ? baseDir : HOME;
  const env = { ...process.env };
  for (const [k, v] of Object.entries(s.env || {})) env[k] = String(v);
  env.PYTHONUNBUFFERED ??= '1';
  env.PYTHONIOENCODING ??= 'utf-8';
  const resolved = which(command) || (fs.existsSync(path.resolve(cwd, command)) ? path.resolve(cwd, command) : null);
  if (!resolved) return { error: `command not found: ${command}` };
  const opts = { cwd, env, stdio: ['pipe', 'pipe', 'pipe'], windowsHide: true, shell: false };
  if (IS_WIN && /\.(cmd|bat)$/i.test(resolved)) {
    // Node refuses to spawn .cmd/.bat without a shell; go through cmd.exe explicitly.
    const line = [winQuote(resolved), ...args.map(winQuote)].join(' ');
    return { file: process.env.ComSpec || 'cmd.exe', args: ['/d', '/s', '/c', `"${line}"`], opts: { ...opts, windowsVerbatimArguments: true }, display: [resolved, ...args] };
  }
  return { file: resolved, args, opts, display: [resolved, ...args] };
}

function killTree(child) {
  if (!child || !child.pid) return;
  if (!IS_WIN && child.exitCode !== null) return;
  try {
    if (IS_WIN) spawnSync('taskkill', ['/PID', String(child.pid), '/T', '/F'], { stdio: 'ignore', windowsHide: true });
    else child.kill('SIGKILL');
  } catch { /* ignore */ }
}

class McpClient {
  constructor(spec, { verbose }) {
    this.spec = spec; this.verbose = verbose; this.nextId = 1; this.pending = new Map();
    this.stderrTail = ''; this.buf = Buffer.alloc(0); this.exited = null; this.nonJson = [];
  }
  start() {
    return new Promise((resolve, reject) => {
      let child;
      try { child = spawn(this.spec.file, this.spec.args, this.spec.opts); }
      catch (e) { reject(e); return; }
      this.child = child;
      child.on('error', (e) => { this.exited = { error: e.message }; this._rejectAll(new Error('spawn error: ' + e.message)); reject(e); });
      child.on('spawn', () => resolve());
      child.on('exit', (code, sig) => { this.exited = { code, signal: sig }; this._rejectAll(new Error(`server exited (code ${code}${sig ? ', signal ' + sig : ''})`)); });
      child.stdout.on('data', (d) => this._onData(d));
      child.stderr.on('data', (d) => {
        const t = d.toString('utf8'); this.stderrTail = (this.stderrTail + t).slice(-4000);
        if (this.verbose) process.stderr.write(t);
      });
      child.stdin.on('error', () => {});
    });
  }
  _rejectAll(err) { for (const [, p] of this.pending) p.reject(err); this.pending.clear(); }
  _onData(d) {
    this.buf = Buffer.concat([this.buf, d]);
    for (;;) {
      // tolerate LSP-style Content-Length framing too
      const head = this.buf.subarray(0, 32).toString('latin1');
      if (/^Content-Length:/i.test(head)) {
        const sep = this.buf.indexOf('\r\n\r\n'); if (sep < 0) return;
        const len = parseInt(/Content-Length:\s*(\d+)/i.exec(this.buf.subarray(0, sep).toString('latin1'))[1], 10);
        if (this.buf.length < sep + 4 + len) return;
        const body = this.buf.subarray(sep + 4, sep + 4 + len).toString('utf8');
        this.buf = this.buf.subarray(sep + 4 + len); this._onLine(body); continue;
      }
      const nl = this.buf.indexOf(0x0a); if (nl < 0) return;
      const line = this.buf.subarray(0, nl).toString('utf8').replace(/\r$/, '');
      this.buf = this.buf.subarray(nl + 1); this._onLine(line);
    }
  }
  _onLine(line) {
    const t = line.trim(); if (!t) return;
    let msg;
    try { msg = JSON.parse(t); } catch { this.nonJson.push(t.slice(0, 300)); if (this.nonJson.length > 20) this.nonJson.shift(); if (this.verbose) process.stderr.write('[non-json stdout] ' + t + '\n'); return; }
    if (!msg || typeof msg !== 'object') return;
    if (msg.id !== undefined && msg.method === undefined && this.pending.has(msg.id)) {
      const p = this.pending.get(msg.id); this.pending.delete(msg.id);
      if (msg.error) p.reject(Object.assign(new Error(msg.error.message || 'JSON-RPC error'), { rpc: msg.error })); else p.resolve(msg.result);
      return;
    }
    if (msg.method && msg.id !== undefined) {
      // server -> client request
      let result; let error;
      if (msg.method === 'ping') result = {};
      else if (msg.method === 'roots/list') result = { roots: [] };
      else error = { code: -32601, message: `client does not support ${msg.method}` };
      this._write(error ? { jsonrpc: '2.0', id: msg.id, error } : { jsonrpc: '2.0', id: msg.id, result });
      return;
    }
    if (msg.method && this.verbose) process.stderr.write(`[notification] ${msg.method}\n`);
  }
  _write(obj) { if (this.child && this.child.stdin.writable) this.child.stdin.write(JSON.stringify(obj) + '\n'); }
  request(method, params) {
    if (this.exited) return Promise.reject(new Error('server not running: ' + JSON.stringify(this.exited)));
    const id = this.nextId++;
    return new Promise((resolve, reject) => { this.pending.set(id, { resolve, reject }); this._write({ jsonrpc: '2.0', id, method, params }); });
  }
  notify(method, params) { this._write({ jsonrpc: '2.0', method, ...(params ? { params } : {}) }); }
  async close() {
    // Kill the whole tree while the root is still alive (so wrapper processes such as
    // cmd.exe / uvx / npx do not leave orphaned grandchildren behind).
    if (this.treeKilled) return; this.treeKilled = true;
    try { this.child.stdin.end(); } catch { /* */ }
    killTree(this.child);
  }
}

// ---------------------------------------------------------------- commands
async function withServer(ref, opt, timeoutMs, fn) {
  const { servers } = loadServers();
  let s = resolveServer(servers, ref);
  if (!s) { fail(`unknown server: ${ref}`, 'resolve', { known: servers.map(x => x.id) }); return; }
  s = applyOverrides(s);
  if (!opt.timeout && s.defaultTimeout) timeoutMs = Math.max(timeoutMs, s.defaultTimeout);
  if (s.remote) { fail(`server ${s.qualifiedId} is a remote URL entry (${redactStr(s.url)}); this bridge only spawns stdio servers`, 'resolve'); return; }
  if (opt.cwd && opt.cwd !== true) s.cwd = opt.cwd;
  for (const kv of [].concat(opt.env || [])) { if (typeof kv !== 'string') continue; const i = kv.indexOf('='); if (i > 0) s.env = { ...s.env, [kv.slice(0, i)]: kv.slice(i + 1) }; }
  const spec = buildSpawn(s);
  if (spec.error) { fail(spec.error, 'spawn', { server: s.qualifiedId }); return; }
  const client = new McpClient(spec, { verbose: !!opt.verbose });
  let stage = 'spawn'; let timer; let done = false;
  const cleanup = async () => { if (done) return; done = true; clearTimeout(timer); await client.close(); };
  process.on('SIGINT', () => { killTree(client.child); process.exit(130); });
  process.on('exit', () => { if (!client.treeKilled) killTree(client.child); });
  const timeout = new Promise((_, rej) => { timer = setTimeout(() => rej(Object.assign(new Error(`timeout after ${timeoutMs} ms`), { timeout: true })), timeoutMs); });
  try {
    await Promise.race([(async () => {
      await client.start();
      stage = 'initialize';
      const init = await client.request('initialize', { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'grokbot-bridge', version: '1.0' } });
      client.notify('notifications/initialized');
      stage = 'run';
      await fn(client, init, s, (st) => { stage = st; });
    })(), timeout]);
    await cleanup();
  } catch (e) {
    await cleanup();
    fail(e.message, stage, {
      server: s.qualifiedId,
      ...(e.rpc ? { rpcError: e.rpc } : {}),
      exit: client.exited || undefined,
      stderrTail: redactStr(client.stderrTail.slice(-2000)) || undefined,
      nonJsonStdout: client.nonJson.length ? client.nonJson.slice(-5) : undefined,
    });
  }
}

async function cmdServers(opt) {
  const { servers, warnings } = loadServers();
  const show = !!opt['show-secrets'];
  out({
    servers: servers.map(s => ({
      id: s.id, qualifiedId: s.qualifiedId, name: s.name, source: s.source, configFile: s.configFile,
      ...(s.remote ? { remote: true, url: redactStr(s.url) } : { command: s.command, args: show ? s.args : redactArgs(s.args) }),
      ...(Object.keys(s.env).length ? { env: show ? s.env : redactEnv(s.env) } : {}),
      ...(s.cwd ? { cwd: s.cwd } : {}),
      ...(s.disabled ? { disabled: true } : {}),
      ...(s.shadowedBy ? { shadowedBy: s.shadowedBy } : {}),
    })),
    warnings,
  });
}

async function cmdTools(ref, opt) {
  const timeoutMs = Number(opt.timeout || 30000);
  await withServer(ref, opt, timeoutMs, async (client, init, s, setStage) => {
    setStage('tools/list');
    const tools = []; let cursor; let pages = 0;
    do {
      const r = await client.request('tools/list', cursor ? { cursor } : {});
      tools.push(...(r?.tools || [])); cursor = r?.nextCursor; pages++;
    } while (cursor && pages < 50);
    if (opt.brief) out({ server: s.qualifiedId, serverInfo: init?.serverInfo, count: tools.length, tools: tools.map(t => t.name) });
    else out({ server: s.qualifiedId, serverInfo: init?.serverInfo, protocolVersion: init?.protocolVersion, count: tools.length, tools: tools.map(t => ({ name: t.name, description: t.description, inputSchema: t.inputSchema })) });
  });
}

async function cmdCall(ref, toolName, opt) {
  const timeoutMs = Number(opt.timeout || 120000);
  let args = {};
  try {
    if (opt['args-file']) args = JSON.parse(readText(opt['args-file']));
    else if (opt.args !== undefined && opt.args !== true) args = JSON.parse(opt.args);
  } catch (e) { fail('invalid --args JSON: ' + e.message, 'args'); return; }
  await withServer(ref, opt, timeoutMs, async (client, init, s, setStage) => {
    setStage('tools/call');
    const result = await client.request('tools/call', { name: toolName, arguments: args });
    out({ server: s.qualifiedId, tool: toolName, result });
    if (result?.isError) process.exitCode = 3;
  });
}

const USAGE = `usage:
  node mcp-call.mjs servers [--show-secrets]
  node mcp-call.mjs tools <server> [--timeout 30000] [--brief] [--verbose]
  node mcp-call.mjs call <server> <toolName> [--args '<json>' | --args-file <path>] [--timeout 120000] [--verbose]
common: [--cwd <dir>] [--env KEY=VALUE]... (override spawn cwd/env)  [--ascii] (escape non-ASCII as \\uXXXX)  [--out <file>] (write UTF-8 JSON to file)
<server> is a bare name (first match in order cursor, claude, codex, manual) or source:name (e.g. claude:sketchup).`;

const { pos, opt } = parseArgv(process.argv.slice(2));
OUT_OPTS = { ascii: !!opt.ascii, file: opt.out && opt.out !== true ? opt.out : null };
const cmd = pos[0];
try {
  if (cmd === 'servers') await cmdServers(opt);
  else if (cmd === 'tools' && pos[1]) await cmdTools(pos[1], opt);
  else if (cmd === 'call' && pos[1] && pos[2]) await cmdCall(pos[1], pos[2], opt);
  else { process.stderr.write(USAGE + '\n'); process.exitCode = 64; }
} catch (e) { fail(e.message, 'internal'); }
// make sure we don't hang on lingering handles
setTimeout(() => process.exit(process.exitCode ?? 0), 50).unref?.();
process.on('beforeExit', () => process.exit(process.exitCode ?? 0));

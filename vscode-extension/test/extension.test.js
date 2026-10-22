'use strict';
// Drives the real extension.js with a mock `vscode` module and a fake Ollama HTTP server.
const test = require('node:test');
const assert = require('node:assert');
const http = require('http');
const Module = require('module');
const fs = require('fs');
const os = require('os');
const path = require('path');

const REPLY = 'Sure:\n```python\ndef add(a, b):\n    return a + b\n```\n';

function startOllama(reply = REPLY) {
  return new Promise((resolve) => {
    const server = http.createServer((req, res) => {
      let body = '';
      req.on('data', (d) => (body += d));
      req.on('end', () => {
        server.lastBody = body ? JSON.parse(body) : null;
        res.writeHead(200, { 'Content-Type': 'application/x-ndjson' });
        const words = reply.split(' ');
        words.forEach((w, i) => res.write(JSON.stringify({ message: { role: 'assistant', content: w + (i < words.length - 1 ? ' ' : '') }, done: false }) + '\n'));
        res.end(JSON.stringify({ done: true, message: { content: '' } }) + '\n');
      });
    });
    server.listen(0, '127.0.0.1', () => resolve(server));
  });
}

function makeVscode(root, host, choices) {
  const handlers = {};
  const commands = {};
  const executed = [];
  const tabs = [];
  const messages = [];
  const config = { enabled: true, host, model: 'm', temperature: 0.2, numCtx: 4096, approval: 'diff', keepComment: false, watcherCommand: 'plevel-watch' };
  class Position { constructor(l, c) { this.line = l; this.character = c; } }
  class Range { constructor(a, b, c, d) { this.start = new Position(a, b); this.end = new Position(c, d); this.isEmpty = a === c && b === d; } }
  class WorkspaceEdit { constructor() { this.edits = []; } replace(uri, range, text) { this.edits.push({ uri, range, text }); } }
  const docs = [];
  const closedTabs = [];
  class TabInputTextDiff { constructor(o, m) { this.original = o; this.modified = m; } }
  class Doc {
    constructor(name, text) { this.uri = { scheme: 'file', fsPath: path.join(root, name), toString: () => 'file://' + path.join(root, name) }; this.lines = text.split('\n'); }
    get lineCount() { return this.lines.length; }
    getText() { return this.lines.join('\n'); }
    lineAt(i) { return { text: this.lines[i] }; }
  }
  const vscode = {
    Uri: { parse: (s) => ({ scheme: s.split(':')[0], fsPath: s, toString: () => s }) },
    Range, Position, WorkspaceEdit, TabInputTextDiff,
    StatusBarAlignment: { Right: 2 }, ConfigurationTarget: { Global: 1 },
    workspace: {
      workspaceFolders: [{ uri: { fsPath: root } }],
      textDocuments: docs,
      getWorkspaceFolder: () => ({ uri: { fsPath: root } }),
      asRelativePath: (u) => path.relative(root, u.fsPath || String(u)),
      findFiles: async () => [{ fsPath: path.join(root, 'app.py') }, { fsPath: path.join(root, 'util.py') }],
      getConfiguration: () => ({ get: (k, d) => (k in config ? config[k] : d), update: async (k, v) => { config[k] = v; } }),
      onDidChangeTextDocument: (h) => { handlers.change = h; return { dispose() {} }; },
      onDidChangeConfiguration: (h) => { handlers.config = h; return { dispose() {} }; },
      registerTextDocumentContentProvider: (s, p) => { handlers.provider = p; return { dispose() {} }; },
      applyEdit: async (edit) => {
        for (const e of edit.edits) {
          const d = docs.find((x) => x.uri === e.uri);
          const r = e.range;
          const line = d.lines[r.start.line];
          assert.strictEqual(r.start.line, r.end.line);
          d.lines.splice(r.start.line, 1, ...(line.slice(0, r.start.character) + e.text + line.slice(r.end.character)).split('\n'));
        }
        return true;
      },
    },
    window: {
      createStatusBarItem: () => ({ show() {}, dispose() {} }),
      showInformationMessage: async (msg, ...btns) => { messages.push(msg); return btns.length ? choices.next : undefined; },
      showWarningMessage: async (m) => { messages.push(m); },
      showErrorMessage: async (m) => { messages.push('ERROR ' + m); },
      setStatusBarMessage: () => {},
      createTerminal: (o) => { const t = { sent: [], opts: o, show() {}, sendText(x) { t.sent.push(x); } }; vscode.window.terminals.push(t); return t; },
      terminals: [],
      tabGroups: { get all() { return [{ tabs }]; }, close: async (tab) => { closedTabs.push(tab); tabs.splice(tabs.indexOf(tab), 1); } },
      showQuickPick: async () => undefined,
      activeTextEditor: null,
    },
    commands: {
      registerCommand: (id, fn) => { commands[id] = fn; return { dispose() {} }; },
      executeCommand: async (...a) => {
        executed.push(a);
        if (a[0] === 'vscode.diff') tabs.push({ input: new TabInputTextDiff(a[1], a[2]) });
      },
    },
  };
  return { vscode, handlers, commands, executed, messages, config, docs, Doc, closedTabs, tabs };
}

async function setup(choice, reply) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'plv-'));
  const server = await startOllama(reply);
  const host = `http://127.0.0.1:${server.address().port}`;
  const choices = { next: choice };
  const env = makeVscode(root, host, choices);
  const origLoad = Module._load;
  Module._load = function (request, ...rest) { return request === 'vscode' ? env.vscode : origLoad.call(this, request, ...rest); };
  delete require.cache[require.resolve('../extension')];
  const ext = require('../extension');
  Module._load = origLoad;
  const ctx = { subscriptions: [] };
  ext.activate(ctx);
  return { ...env, ext, server, root, choices };
}

async function pressEnterOn(env, doc, line) {
  // VS Code reports Enter as an insertion of "\n" + auto-indent
  const indent = /^[ \t]*/.exec(doc.lines[line])[0];
  doc.lines.splice(line + 1, 0, indent);
  env.handlers.change({
    document: doc, reason: undefined,
    contentChanges: [{ rangeLength: 0, text: '\n' + indent, range: new env.vscode.Range(line, doc.lines[line].length, line, doc.lines[line].length) }],
  });
  for (let i = 0; i < 200 && (env.executed.length === 0 && env.docs[0].getText().includes('plevel:') && !env.messages.some((m) => m.startsWith('ERROR'))); i++) {
    await new Promise((r) => setTimeout(r, 20));
  }
  await new Promise((r) => setTimeout(r, 100));
}

test('Enter on a plevel comment -> diff -> Apply writes the code', async () => {
  const env = await setup('Apply');
  const doc = new env.Doc('app.py', 'import os\n# plevel: write add\nprint(1)');
  env.docs.push(doc);
  await pressEnterOn(env, doc, 1);
  assert.strictEqual(env.executed[0][0], 'vscode.diff');
  const proposed = env.handlers.provider.provideTextDocumentContent({ toString: () => env.executed[0][2].toString() });
  void proposed;
  assert.match(env.messages[0], /Apply this change/);
  assert.strictEqual(env.closedTabs.length, 1, 'diff tab is closed after the decision');
  const text = doc.getText();
  assert.match(text, /def add\(a, b\):\n    return a \+ b/);
  assert.ok(!text.includes('plevel:'), text);
  assert.ok(text.startsWith('import os\n') && text.endsWith('print(1)'));
  assert.ok(!fs.existsSync(path.join(env.root, '.plevel', 'busy')), 'lock released');
  assert.strictEqual(env.server.lastBody.options.temperature, 0.2);
  assert.match(env.server.lastBody.messages[1].content, /write add/);
  env.server.close();
});

test('Discard leaves the file untouched', async () => {
  const env = await setup('Discard');
  const doc = new env.Doc('app.py', '# plevel: write add');
  env.docs.push(doc);
  await pressEnterOn(env, doc, 0);
  assert.strictEqual(doc.lines[0], '# plevel: write add');
  env.server.close();
});

test('direct mode writes without asking, keeps indentation', async () => {
  const env = await setup(undefined, '```python\nx = 1\nif x:\n    print(x)\n```');
  env.config.approval = 'direct';
  const doc = new env.Doc('app.py', 'def f():\n    # plevel: body\n');
  env.docs.push(doc);
  await pressEnterOn(env, doc, 1);
  assert.strictEqual(doc.getText().split('\n').slice(0, 4).join('\n'), 'def f():\n    x = 1\n    if x:\n        print(x)');
  assert.strictEqual(env.executed.length, 0);
  env.server.close();
});

test('ordinary Enter, paste, undo, and disabled mode do nothing', async () => {
  const env = await setup('Apply');
  const doc = new env.Doc('app.py', 'x = 1\n# plevel: write add');
  env.docs.push(doc);
  const mk = (over) => ({ document: doc, reason: undefined, contentChanges: [{ rangeLength: 0, text: '\n', range: new env.vscode.Range(0, 5, 0, 5) }], ...over });
  env.handlers.change(mk({}));                                                              // Enter on "x = 1"
  env.handlers.change({ ...mk({}), contentChanges: [{ rangeLength: 0, text: '\n\n', range: new env.vscode.Range(1, 99, 1, 99) }] }); // paste of 2 newlines
  env.handlers.change({ ...mk({}), reason: 1, contentChanges: [{ rangeLength: 0, text: '\n', range: new env.vscode.Range(1, 99, 1, 99) }] }); // undo
  env.config.enabled = false;
  env.handlers.change({ ...mk({}), contentChanges: [{ rangeLength: 0, text: '\n', range: new env.vscode.Range(1, 99, 1, 99) }] });
  await new Promise((r) => setTimeout(r, 150));
  assert.strictEqual(env.server.lastBody, undefined, 'model must not have been called');
  env.server.close();
});

test('Ollama down shows a helpful error and releases the lock', async () => {
  const env = await setup('Apply');
  env.config.host = 'http://127.0.0.1:1';
  const doc = new env.Doc('app.py', '# plevel: write add');
  env.docs.push(doc);
  await pressEnterOn(env, doc, 0);
  assert.ok(env.messages.some((m) => /ERROR Plevel/.test(m) && /Ollama running/.test(m)), env.messages.join('|'));
  assert.ok(!fs.existsSync(path.join(env.root, '.plevel', 'busy')));
  assert.strictEqual(doc.lines[0], '# plevel: write add');
  env.server.close();
});

test('startWatcher opens a terminal with the model', async () => {
  const env = await setup('Apply');
  env.commands['plevel.startWatcher']();
  assert.strictEqual(env.vscode.window.terminals[0].sent[0], 'plevel-watch --model m');
  env.server.close();
});

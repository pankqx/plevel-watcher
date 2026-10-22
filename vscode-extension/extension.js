'use strict';
const vscode = require('vscode');
const fs = require('fs');
const path = require('path');
const core = require('./core');

const SCHEME = 'plevel-proposal';
const LOCK = path.join('.plevel', 'busy');

let statusItem;
let running = null; // {abort: AbortController}
const proposals = new Map(); // uri string -> proposed file text

function cfg() {
  const c = vscode.workspace.getConfiguration('plevel');
  return {
    enabled: c.get('enabled', true),
    host: c.get('host', 'http://127.0.0.1:11434'),
    model: c.get('model', 'qwen2.5-coder:1.5b'),
    temperature: c.get('temperature', 0.2),
    numCtx: c.get('numCtx', 4096),
    approval: c.get('approval', 'diff'),
    keepComment: c.get('keepComment', false),
    watcherCommand: c.get('watcherCommand', 'plevel-watch'),
  };
}

function updateStatus(state) {
  const c = cfg();
  if (state === 'working') {
    statusItem.text = '$(sync~spin) Plevel thinking… (click to cancel)';
    statusItem.command = 'plevel.cancel';
  } else {
    statusItem.text = c.enabled ? '$(sparkle) Plevel' : '$(circle-slash) Plevel off';
    statusItem.command = 'plevel.toggle';
  }
  statusItem.tooltip = `Plevel · ${c.model} · type "# plevel: <task>" and press Enter`;
  statusItem.show();
}

function workspaceRoot(doc) {
  const folder = vscode.workspace.getWorkspaceFolder(doc.uri) || (vscode.workspace.workspaceFolders || [])[0];
  return folder ? folder.uri.fsPath : null;
}

function setLock(root, on) {
  if (!root) return;
  try {
    const f = path.join(root, LOCK);
    if (on) { fs.mkdirSync(path.dirname(f), { recursive: true }); fs.writeFileSync(f, String(Date.now())); }
    else if (fs.existsSync(f)) fs.unlinkSync(f);
  } catch (e) { /* the lock is a courtesy; never fail the request because of it */ }
}

async function gatherContext(doc) {
  const out = { tree: [], others: [] };
  try {
    const files = await vscode.workspace.findFiles('**/*', '**/{node_modules,.git,.venv,venv,dist,build,__pycache__,.plevel}/**', 120);
    out.tree = files.map((u) => vscode.workspace.asRelativePath(u)).sort();
  } catch (e) { /* no workspace */ }
  for (const d of vscode.workspace.textDocuments) {
    if (out.others.length >= 3) break;
    if (d === doc || d.uri.scheme !== 'file' || d.getText().length > 60000) continue;
    out.others.push({ path: vscode.workspace.asRelativePath(d.uri), head: d.getText().split('\n').slice(0, 60).join('\n') });
  }
  return out;
}

const APPROVAL_TIMEOUT_MS = 5 * 60 * 1000; // same as the watcher's lock TTL

async function closeProposalTab(uri) {
  try {
    for (const group of vscode.window.tabGroups.all) {
      for (const tab of group.tabs) {
        const input = tab.input;
        if (input instanceof vscode.TabInputTextDiff && input.modified.toString() === uri.toString()) {
          await vscode.window.tabGroups.close(tab);
        }
      }
    }
  } catch (e) { /* closing the diff is a nicety only */ }
}

async function showProposal(doc, newText, lineCount) {
  const uri = vscode.Uri.parse(`${SCHEME}:/${path.basename(doc.uri.fsPath)}?${Date.now()}`);
  proposals.set(uri.toString(), newText);
  await vscode.commands.executeCommand('vscode.diff', doc.uri, uri, `Plevel: proposed change to ${path.basename(doc.uri.fsPath)}`);
  let timer;
  const timeout = new Promise((resolve) => { timer = setTimeout(() => resolve(undefined), APPROVAL_TIMEOUT_MS); });
  const choice = await Promise.race([
    vscode.window.showInformationMessage(
      `Plevel wrote ${lineCount} line${lineCount === 1 ? '' : 's'}. Apply this change?`, 'Apply', 'Discard'),
    timeout,
  ]);
  clearTimeout(timer);
  proposals.delete(uri.toString());
  await closeProposalTab(uri);
  return choice === 'Apply';
}

async function writeIntoDocument(doc, line, raw, code, keepComment) {
  // the line may have moved while the model was thinking: look for it near where it was
  let at = -1;
  for (let d = 0; d < doc.lineCount && at < 0; d++) {
    for (const cand of [line + d, line - d]) {
      if (cand >= 0 && cand < doc.lineCount && doc.lineAt(cand).text.replace(/\r$/, '') === raw) { at = cand; break; }
    }
  }
  if (at < 0) throw new Error('the comment line was edited or removed; nothing was written');
  // replace only the affected line so the user's undo stack and cursor stay sane
  const replacement = core.applyCode(raw, 0, raw, code, keepComment);
  const e2 = new vscode.WorkspaceEdit();
  e2.replace(doc.uri, new vscode.Range(at, 0, at, doc.lineAt(at).text.length), replacement);
  const ok = await vscode.workspace.applyEdit(e2);
  if (!ok) throw new Error('VS Code refused the edit');
}

async function run(doc, line) {
  if (running) { vscode.window.showWarningMessage('Plevel is already working on a request.'); return; }
  const parsed = core.parseCommentLine(doc.lineAt(line).text);
  if (!parsed) { vscode.window.showInformationMessage('Plevel: this line is not a "# plevel: <task>" comment.'); return; }
  const c = cfg();
  const root = workspaceRoot(doc);
  const abort = new AbortController();
  running = { abort };
  setLock(root, true);
  updateStatus('working');
  try {
    const ctx = await gatherContext(doc);
    const messages = core.buildMessages({
      path: vscode.workspace.asRelativePath(doc.uri), text: doc.getText(), line, task: parsed.task,
      tree: ctx.tree, others: ctx.others,
    });
    const reply = await core.streamChat({
      host: c.host, model: c.model, messages, temperature: c.temperature, numCtx: c.numCtx, signal: abort.signal,
    });
    const code = core.extractCode(reply);
    if (!code.trim()) throw new Error('the model returned nothing');
    const lineCount = code.split('\n').length;
    if (c.approval === 'direct') {
      await writeIntoDocument(doc, line, parsed.raw, code, c.keepComment);
    } else {
      const newText = core.applyCode(doc.getText(), line, parsed.raw, code, c.keepComment);
      const ok = await showProposal(doc, newText, lineCount);
      if (ok) await writeIntoDocument(doc, line, parsed.raw, code, c.keepComment);
    }
  } catch (err) {
    if (err && err.name === 'AbortError') vscode.window.setStatusBarMessage('Plevel: cancelled', 3000);
    else {
      const msg = String(err && err.message || err);
      const hint = /fetch failed|ECONNREFUSED/i.test(msg) ? ' Is Ollama running? (sudo systemctl start ollama)' : '';
      vscode.window.showErrorMessage(`Plevel: ${msg}${hint}`);
    }
  } finally {
    running = null;
    setLock(root, false);
    updateStatus('idle');
  }
}

/** True when this edit looks like the user pressing Enter (and nothing else). */
function isEnterKey(change) {
  return change.rangeLength === 0 && /^\r?\n[ \t]*$/.test(change.text);
}

function activate(context) {
  statusItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  context.subscriptions.push(statusItem);
  updateStatus('idle');

  context.subscriptions.push(vscode.workspace.registerTextDocumentContentProvider(SCHEME, {
    provideTextDocumentContent: (uri) => proposals.get(uri.toString()) || '',
  }));

  context.subscriptions.push(vscode.workspace.onDidChangeTextDocument((e) => {
    if (!cfg().enabled || e.reason || running) return;          // reason is set for undo/redo
    if (e.document.uri.scheme !== 'file') return;
    for (const ch of e.contentChanges) {
      if (!isEnterKey(ch)) continue;
      const line = ch.range.start.line;
      if (line >= e.document.lineCount) continue;
      if (core.parseCommentLine(e.document.lineAt(line).text)) {
        run(e.document, line);
        return;
      }
    }
  }));

  const reg = (id, fn) => context.subscriptions.push(vscode.commands.registerCommand(id, fn));

  reg('plevel.run', () => {
    const ed = vscode.window.activeTextEditor;
    if (ed) run(ed.document, ed.selection.active.line);
  });
  reg('plevel.cancel', () => { if (running) running.abort.abort(); });
  reg('plevel.toggle', async () => {
    const on = !cfg().enabled;
    await vscode.workspace.getConfiguration('plevel').update('enabled', on, vscode.ConfigurationTarget.Global);
    updateStatus('idle');
    vscode.window.setStatusBarMessage(`Plevel ${on ? 'on' : 'off'}`, 3000);
  });
  reg('plevel.pickModel', async () => {
    const c = cfg();
    try {
      const res = await fetch(c.host.replace(/\/$/, '') + '/api/tags');
      const data = await res.json();
      const pick = await vscode.window.showQuickPick((data.models || []).map((m) => m.name), { placeHolder: 'Choose the Ollama model for Plevel' });
      if (pick) {
        await vscode.workspace.getConfiguration('plevel').update('model', pick, vscode.ConfigurationTarget.Global);
        updateStatus('idle');
      }
    } catch (err) {
      vscode.window.showErrorMessage('Plevel: cannot reach Ollama at ' + c.host);
    }
  });
  reg('plevel.startWatcher', () => {
    const c = cfg();
    const term = vscode.window.createTerminal({ name: 'Plevel watcher', cwd: (vscode.workspace.workspaceFolders || [])[0]?.uri.fsPath });
    term.show();
    term.sendText(`${c.watcherCommand} --model ${c.model}`);
  });

  context.subscriptions.push(vscode.workspace.onDidChangeConfiguration((e) => {
    if (e.affectsConfiguration('plevel')) updateStatus(running ? 'working' : 'idle');
  }));
}

function deactivate() { if (running) running.abort.abort(); }

module.exports = { activate, deactivate, isEnterKey };

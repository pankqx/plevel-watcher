'use strict';
// Pure logic for the Plevel VS Code extension. No vscode imports, so it can be tested with plain node.
// The Python twin is plevel/agent.py; both are checked against tests/vectors/comments.json.

const COMMENT_RE = /^([ \t]*)(#|\/\/|--|;|%|\/\*|<!--)[ \t]*plevel[ \t]*:[ \t]*(.*?)[ \t]*(?:\*\/|-->)?[ \t]*$/i;

const SYSTEM_PROMPT =
  "You are Plevel, a code-writing assistant inside the user's editor. The user wrote an " +
  'instruction as a comment in a file. Reply with ONLY the code that should replace that ' +
  'comment, inside exactly one fenced code block. Match the file\'s language, naming style and ' +
  'indentation, and reuse names and imports that already exist in the file. Prefer the ' +
  'standard library and never invent libraries or functions. If the instruction is a question ' +
  "that code cannot answer, reply with a short comment block in the file's comment syntax " +
  'instead. Do not write any text outside the code block.';

/** Returns {indent, task, raw} if the line is a `plevel:` command comment, else null. */
function parseCommentLine(line) {
  const raw = line.replace(/\r$/, '');
  const m = COMMENT_RE.exec(raw);
  if (!m || !m[3].trim()) return null;
  return { indent: m[1], task: m[3].trim(), raw };
}

function extractCode(reply) {
  const lines = reply.replace(/\r\n/g, '\n').split('\n');
  const body = [];
  let inside = false;
  let found = false;
  for (const ln of lines) {
    if (!inside && /^\s{0,3}`{3,}[\w+#.\-]*\s*$/.test(ln)) { inside = true; found = true; continue; }
    if (inside && /^\s{0,3}`{3,}\s*$/.test(ln)) break;
    if (inside) body.push(ln);
  }
  const code = found ? body.join('\n') : reply;
  return code.replace(/^\n+/, '').replace(/\s+$/, '');
}

function dedent(code) {
  const lines = code.split('\n');
  let min = Infinity;
  for (const ln of lines) {
    if (!ln.trim()) continue;
    const lead = /^[ \t]*/.exec(ln)[0].length;
    if (lead < min) min = lead;
  }
  if (!isFinite(min) || min === 0) return code;
  return lines.map((ln) => (ln.trim() ? ln.slice(min) : '')).join('\n');
}

function reindent(code, indent) {
  return dedent(code).split('\n').map((ln) => (ln.trim() ? indent + ln : '')).join('\n');
}

/** Replace comment line `line` of `text` with the code. Throws if the line no longer matches. */
function applyCode(text, line, raw, code, keepComment) {
  const lines = text.split('\n');
  if (line >= lines.length || lines[line].replace(/\r$/, '') !== raw) {
    throw new Error('the comment line changed; not applying');
  }
  const cmd = parseCommentLine(raw);
  let add = reindent(code, cmd.indent).split('\n');
  if (keepComment) add = [raw, ...add];
  const eol = lines[line].endsWith('\r') ? '\r' : '';
  add = add.map((l) => l + eol);
  return [...lines.slice(0, line), ...add, ...lines.slice(line + 1)].join('\n');
}

/** The part of the file the model sees; the comment line is marked. */
function fileWindow(text, line, maxLines = 200, before = 80, after = 40) {
  const lines = text.split('\n');
  const marked = lines.slice();
  marked[line] = marked[line].replace(/\r$/, '') + '   <-- INSTRUCTION IS HERE';
  if (lines.length <= maxLines) return marked.join('\n');
  const head = marked.slice(0, 20);
  const lo = Math.max(20, line - before);
  const hi = Math.min(lines.length, line + after + 1);
  return [...head, ...(lo > 20 ? ['...'] : []), ...marked.slice(lo, hi), ...(hi < lines.length ? ['...'] : [])].join('\n');
}

const LANGS = {
  py: 'Python', js: 'JavaScript', mjs: 'JavaScript', ts: 'TypeScript', tsx: 'TypeScript React',
  jsx: 'JavaScript React', java: 'Java', kt: 'Kotlin', c: 'C', h: 'C', cpp: 'C++', cs: 'C#',
  go: 'Go', rs: 'Rust', rb: 'Ruby', php: 'PHP', swift: 'Swift', sh: 'Bash', sql: 'SQL',
  html: 'HTML', css: 'CSS', yml: 'YAML', yaml: 'YAML', toml: 'TOML', md: 'Markdown', lua: 'Lua',
};

/** info: {path, text, line, task, tree?: string[], others?: [{path, head}]} */
function buildMessages(info) {
  const ext = (info.path.split('.').pop() || '').toLowerCase();
  const lang = LANGS[ext] || 'code';
  let system = SYSTEM_PROMPT;
  if (info.tree && info.tree.length) {
    system += '\n\nProject files:\n' + info.tree.join('\n');
  }
  if (info.others && info.others.length) {
    system += '\n\nOther open files (use them if relevant):\n' +
      info.others.map((o) => `### ${o.path}\n\`\`\`\n${o.head}\n\`\`\``).join('\n\n');
  }
  const user =
    `File: ${info.path} (${lang})\n\n\`\`\`\n${fileWindow(info.text, info.line)}\n\`\`\`\n\n` +
    `Instruction: ${info.task}\n` +
    'Reply with the code that replaces the instruction comment, in one fenced code block.';
  return [{ role: 'system', content: system }, { role: 'user', content: user }];
}

/** Streams a chat reply from Ollama. Returns the full text. `fetchImpl` and `signal` are injectable. */
async function streamChat({ host, model, messages, temperature, numCtx, maxTokens, signal, onToken, fetchImpl }) {
  const f = fetchImpl || fetch;
  const res = await f(host.replace(/\/$/, '') + '/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model, messages, stream: true, options: { temperature, num_ctx: numCtx, num_predict: maxTokens || 1024 } }),
    signal,
  });
  if (!res.ok) {
    let detail = '';
    try { detail = (await res.text()).slice(0, 200); } catch (e) { /* ignore */ }
    throw new Error(`Ollama answered ${res.status}. ${detail}`);
  }
  const decoder = new TextDecoder();
  let buf = '';
  let full = '';
  const handle = (line) => {
    if (!line.trim()) return;
    const obj = JSON.parse(line);
    if (obj.error) throw new Error(obj.error);
    const piece = obj.message && obj.message.content;
    if (piece) { full += piece; if (onToken) onToken(piece); }
  };
  for await (const chunk of res.body) {
    buf += decoder.decode(chunk, { stream: true });
    let i;
    while ((i = buf.indexOf('\n')) >= 0) { handle(buf.slice(0, i)); buf = buf.slice(i + 1); }
  }
  handle(buf);
  return full;
}

module.exports = { COMMENT_RE, SYSTEM_PROMPT, parseCommentLine, extractCode, reindent, applyCode, fileWindow, buildMessages, streamChat };

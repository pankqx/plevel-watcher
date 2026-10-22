'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const path = require('path');
const core = require('../core');

const V = JSON.parse(fs.readFileSync(path.join(__dirname, '..', '..', 'tests', 'vectors', 'comments.json'), 'utf8'));

test('comment lines match like the Python twin', () => {
  for (const m of V.matches) {
    const p = core.parseCommentLine(m.line);
    assert.ok(p, m.line);
    assert.strictEqual(p.indent, m.indent);
    assert.strictEqual(p.task, m.task);
  }
  for (const l of V.non_matches) assert.strictEqual(core.parseCommentLine(l), null, l);
});

test('extractCode matches vectors', () => {
  for (const e of V.extract) assert.strictEqual(core.extractCode(e.reply), e.code);
});

test('applyCode matches vectors', () => {
  for (const a of V.apply) {
    assert.strictEqual(core.applyCode(a.text, a.line, core.parseCommentLine(a.text.split('\n')[a.line]).raw, a.code, a.keep), a.out);
  }
});

test('stale line is refused', () => {
  assert.throws(() => core.applyCode('x\n# plevel: other\n', 1, '# plevel: add y', 'y = 2', false));
});

test('buildMessages includes file window, tree and open files', () => {
  const text = Array.from({ length: 500 }, (_, i) => `line${i}`).join('\n') + '\n# plevel: do it\n';
  const msgs = core.buildMessages({ path: 'a/app.py', text, line: 500, task: 'do it', tree: ['a/app.py', 'b/util.py'], others: [{ path: 'b/util.py', head: 'def helper(): pass' }] });
  assert.match(msgs[0].content, /b\/util.py/);
  assert.match(msgs[0].content, /def helper/);
  assert.match(msgs[1].content, /Python/);
  assert.match(msgs[1].content, /INSTRUCTION IS HERE/);
  assert.ok(msgs[1].content.length < 12000);
});

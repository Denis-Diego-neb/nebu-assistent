const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

const source = fs.readFileSync(path.join(__dirname, '../nebula_front/nebula-app.js'), 'utf8');
const start = source.indexOf('  function pintarLinhas(');
assert.ok(start >= 0);
const end = source.indexOf('\n  }', start) + 4;
const context = vm.createContext({document: {createElement: () => ({height: 20})}});
vm.runInContext(source.slice(start, end), context);

// Simula o reset de rolagem causado pela remoção dos elementos no navegador.
function panel(top, height, viewport) {
  return {
    scrollTop: top, scrollHeight: height, clientHeight: viewport, children: [],
    replaceChildren() { this.children = []; this.scrollTop = 0; this.scrollHeight = 0; },
    append(item) { this.children.push(item); this.scrollHeight += item.height; },
  };
}

test('preserva a leitura acima em atualizações repetidas, no PC e celular', () => {
  for (const viewport of [300, 700]) {
    const target = panel(180, 2000, viewport);
    for (const height of [2200, 2400, 2600]) {
      context.pintarLinhas(target, [{height}], 'Vazio');
      assert.equal(target.scrollTop, 180);
    }
  }
});

test('acompanha novas mensagens quando já estava no final', () => {
  const target = panel(1700, 2000, 300);
  context.pintarLinhas(target, [{height: 2300}], 'Vazio');
  assert.equal(target.scrollTop, 2300);
});

test('acompanha a primeira mensagem e exibe estado vazio', () => {
  const target = panel(0, 0, 300);
  context.pintarLinhas(target, [], 'Sem mensagens');
  assert.equal(target.children[0].textContent, 'Sem mensagens');
  context.pintarLinhas(target, [{height: 1200}], 'Vazio');
  assert.equal(target.scrollTop, 1200);
});

// Execute the real page script with controllable responses, then the real local API.
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const {script, pageUrl, ids} = JSON.parse(fs.readFileSync(0, 'utf8'));

function page(fetchImpl, address = pageUrl) {
  const elements = new Map();
  function element() {
    return {hidden: false, disabled: false, value: '', textContent: '', handlers: {},
      addEventListener(event, handler) { this.handlers[event] = handler; }};
  }
  const cards = ids.map(id => Object.assign(element(), {
    dataset: {recordId: id, email: 'alice@example.com', keywords: 'review'},
  }));
  const buttons = cards.map(card => Object.assign(element(), {closest: () => card}));
  const values = new Map();
  const context = vm.createContext({
    document: {
      querySelectorAll: selector => selector === '.review-item' ? cards : buttons,
      getElementById(id) {
        if (!elements.has(id)) elements.set(id, element());
        return elements.get(id);
      },
    },
    location: new URL(address), history: {replaceState() {}},
    localStorage: {getItem: key => values.get(key) || null, setItem: (key, value) => values.set(key, value)},
    URL, URLSearchParams, AbortController, setTimeout, clearTimeout,
    fetch: fetchImpl,
  });
  vm.runInContext(script, context);
  return {cards, buttons, elements, values, context};
}
const turn = () => new Promise(resolve => setImmediate(resolve));
async function waitFor(predicate) {
  const until = Date.now() + 5000;
  while (!predicate()) {
    if (Date.now() > until) throw new Error('Review did not finish saving');
    await new Promise(resolve => setTimeout(resolve, 10));
  }
}
const reply = excluded => ({ok: true, json: async () => ({excluded_record_ids: excluded, report_error: false})});

async function main() {
  const requests = [];
  const p = page((_url, options) => new Promise((resolve, reject) => {
    requests.push({resolve, reject, method: options.method, body: options.body ? JSON.parse(options.body) : null});
  }));
  assert.equal(requests[0].method, 'GET');
  p.buttons[0].handlers.click();
  p.buttons[1].handlers.click();
  assert.equal(p.cards[0].hidden, true, 'click must hide immediately');
  assert.equal(p.cards[1].hidden, true);
  assert.ok([...p.values.values()].some(value => value.includes(ids[0])), 'pending decision must be stored');
  assert.equal(requests.length, 1, 'deleting must not write to the project yet');
  assert.equal(p.elements.get('save-review').disabled, false);
  requests[0].resolve(reply([]));
  await turn();
  assert.equal(p.cards[0].hidden, true, 'initial read must preserve unsaved deletion');
  p.elements.get('save-review').handlers.click();
  assert.equal(requests.length, 2);
  assert.equal(requests[1].body.action, 'save');
  assert.deepEqual(requests[1].body.exclude_ids, ids);
  p.elements.get('undo-delete').handlers.click();
  assert.equal(p.cards[1].hidden, false, 'undo must respond immediately');
  requests[1].resolve(reply(ids));
  await turn();
  assert.equal(p.cards[1].hidden, false, 'earlier save response must preserve later undo');
  p.elements.get('save-review').handlers.click();
  assert.deepEqual(requests[2].body.restore_ids, [ids[1]]);
  requests[2].reject(new Error('offline'));
  await turn();
  assert.match(p.elements.get('review-sync-status').textContent, /保存失败/);
  assert.equal(p.elements.get('save-review').disabled, false);
  p.elements.get('save-review').handlers.click();
  requests[3].resolve(reply([ids[0]]));
  await turn();
  assert.match(p.elements.get('review-sync-status').textContent, /已保存/);
  assert.equal(p.elements.get('save-review').disabled, true);

  const offline = page(() => {throw new Error('file view must not fetch');}, 'file:///example/mail_review.html');
  offline.buttons[0].handlers.click();
  assert.equal(offline.cards[0].hidden, true);
  offline.elements.get('save-review').handlers.click();
  assert.match(offline.elements.get('review-sync-status').textContent, /从 GUI/);

  // Integration: one deliberate save sends all decisions to the Python service.
  const live = page((url, options) => fetch(new URL(url, pageUrl), {
    ...options, headers: {...options.headers, Origin: new URL(pageUrl).origin},
  }));
  await waitFor(() => /已从本地项目读取/.test(live.elements.get('review-sync-status').textContent));
  live.buttons[0].handlers.click();
  assert.equal(live.cards[0].hidden, true);
  assert.match(live.elements.get('review-sync-status').textContent, /待保存/);
  live.elements.get('save-review').handlers.click();
  await waitFor(() => /已保存 1 项/.test(live.elements.get('review-sync-status').textContent));
  assert.equal(live.cards[0].hidden, true);
  process.stdout.write('manual review save, pending requests, retry, undo and API persistence OK\n');
}
main().catch(error => { console.error(error); process.exitCode = 1; });

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const scriptPath = path.resolve(__dirname, '../frontend/public/theme.js');
assert.ok(fs.existsSync(scriptPath), 'theme controller must exist');
const source = fs.readFileSync(scriptPath, 'utf8');

function browser({saved = null, dark = false, blocked = false} = {}) {
  const root = {dataset: {}, style: {}};
  const events = {}, selectEvents = {}, mediaEvents = {};
  const select = {value: '', addEventListener(type, listener) {selectEvents[type] = listener;}};
  const media = {matches: dark, addEventListener(type, listener) {mediaEvents[type] = listener;}};
  const values = new Map(saved === null ? [] : [['kicaddiffview.theme', saved]]);
  const document = {
    documentElement: root,
    getElementById(id) {return id === 'theme-select' ? select : null;},
    addEventListener(type, listener) {events[type] = listener;},
  };
  const localStorage = {
    getItem(key) {if (blocked) throw new Error('Storage blocked'); return values.get(key) ?? null;},
    setItem(key, value) {if (blocked) throw new Error('Storage blocked'); values.set(key, value);},
  };
  const window = {matchMedia(query) {assert.equal(query, '(prefers-color-scheme: dark)'); return media;}};
  vm.runInNewContext(source, {document, window, localStorage});
  // Applying the palette must not wait for DOMContentLoaded or the API.
  assert.ok(['light', 'dark'].includes(root.dataset.theme));
  events.DOMContentLoaded();
  return {
    root, select, values,
    choose(value) {select.value = value; selectEvents.change();},
    system(value) {media.matches = value; mediaEvents.change();},
  };
}

const automatic = browser();
assert.equal(automatic.select.value, 'system');
assert.equal(automatic.root.dataset.theme, 'light');
assert.equal(automatic.root.style.colorScheme, 'light');
automatic.system(true);
assert.equal(automatic.root.dataset.theme, 'dark', 'System follows OS changes live');
automatic.choose('light');
assert.equal(automatic.root.dataset.theme, 'light');
automatic.system(true);
assert.equal(automatic.root.dataset.theme, 'light', 'Explicit Light overrides the system');
assert.equal(automatic.values.get('kicaddiffview.theme'), 'light');

const restored = browser({saved: automatic.values.get('kicaddiffview.theme'), dark: true});
assert.equal(restored.root.dataset.theme, 'light', 'Preference survives page reload');
assert.equal(restored.select.value, 'light');
restored.choose('dark');
restored.system(false);
assert.equal(restored.root.dataset.theme, 'dark');
assert.equal(restored.root.style.colorScheme, 'dark');
restored.choose('system');
assert.equal(restored.root.dataset.theme, 'light');
assert.equal(restored.values.get('kicaddiffview.theme'), 'system');
restored.system(true);
assert.equal(restored.root.dataset.theme, 'dark');

const invalid = browser({saved: 'invalid', dark: true});
assert.equal(invalid.select.value, 'system');
assert.equal(invalid.root.dataset.theme, 'dark');
const blocked = browser({blocked: true});
blocked.choose('dark');
assert.equal(blocked.root.dataset.theme, 'dark', 'Storage failures must not block switching');
blocked.choose('system');
blocked.system(true);
assert.equal(blocked.root.dataset.theme, 'dark');
console.log('PASS: theme startup, persistence, explicit overrides, live System mode and blocked storage.');

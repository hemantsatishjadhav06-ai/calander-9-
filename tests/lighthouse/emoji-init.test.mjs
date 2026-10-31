import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

const template = await readFile(new URL('../../templates/base.html', import.meta.url), 'utf8');
const start = template.indexOf('_filteredEmojis() {');
const end = template.indexOf('_insertEmoji(emoji)', start);
assert.ok(start >= 0 && end > start);
const filteredEmojis = vm.runInNewContext(`({${template.slice(start, end)}})`)._filteredEmojis;
const emojis = [{ e: '✨', n: 'sparkles' }, { e: '⭐', n: 'star' }];

test('a closed picker creates no hidden reactive emoji buttons', () => {
  assert.equal(filteredEmojis.call({ emojiPickerOpen: false, _emojiSearch: '', _emojiList: emojis }).length, 0);
});

test('opening, searching and reopening preserve the emoji choices', () => {
  const state = { emojiPickerOpen: true, _emojiSearch: '', _emojiList: emojis };
  assert.deepEqual(filteredEmojis.call(state), emojis);
  state._emojiSearch = '  SPARK  ';
  assert.deepEqual(filteredEmojis.call(state), [emojis[0]]);
  state.emojiPickerOpen = false;
  assert.equal(filteredEmojis.call(state).length, 0);
  state.emojiPickerOpen = true;
  assert.deepEqual(filteredEmojis.call(state), [emojis[0]]);
});

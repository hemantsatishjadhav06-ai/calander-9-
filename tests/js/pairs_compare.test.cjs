// The pixel comparison behind `npm run pairs:diff` (tests/e2e/pairs/compare.cjs). No browser, no server.
// npm ci --ignore-scripts && npm run test:ui
const { test } = require('node:test');
const assert = require('node:assert/strict');

const { decodePng, encodePng, diffImages, DIFF_LIMIT } = require('../e2e/pairs/compare.cjs');

function solid(width, height, [r, g, b, a = 255]) {
  const data = Buffer.alloc(width * height * 4);
  for (let i = 0; i < data.length; i += 4) {
    data[i] = r; data[i + 1] = g; data[i + 2] = b; data[i + 3] = a;
  }
  return { width, height, data };
}

function setPixel(image, x, y, [r, g, b, a = 255]) {
  const i = (y * image.width + x) * 4;
  image.data[i] = r; image.data[i + 1] = g; image.data[i + 2] = b; image.data[i + 3] = a;
}

test('a PNG it writes reads back pixel for pixel', () => {
  const image = solid(7, 5, [250, 250, 249]);
  setPixel(image, 3, 2, [17, 86, 65]);
  setPixel(image, 6, 4, [0, 0, 0, 0]);
  const back = decodePng(encodePng(image));
  assert.equal(back.width, 7);
  assert.equal(back.height, 5);
  assert.deepEqual(back.data, image.data);
});

test('every PNG filter type decodes (the browser writes them all)', () => {
  // A 4 x 3 RGBA image whose rows use filters 1 (Sub), 2 (Up), 3 (Average) and 4 (Paeth).
  const zlib = require('node:zlib');
  const pixels = solid(4, 3, [10, 20, 30]);
  for (let x = 0; x < 4; x++) for (let y = 0; y < 3; y++) setPixel(pixels, x, y, [x * 40 + y, y * 70, 200 - x * 30, 255]);
  const stride = 16;
  const raw = [];
  const at = (y, i) => (y < 0 || i < 0 ? 0 : pixels.data[y * stride + i]);
  const paeth = (a, b, c) => {
    const p = a + b - c;
    const pa = Math.abs(p - a), pb = Math.abs(p - b), pc = Math.abs(p - c);
    return pa <= pb && pa <= pc ? a : pb <= pc ? b : c;
  };
  const filters = [1, 2, 4];
  for (let y = 0; y < 3; y++) {
    const type = filters[y];
    raw.push(type);
    for (let i = 0; i < stride; i++) {
      const left = at(y, i - 4), up = at(y - 1, i), upLeft = at(y - 1, i - 4);
      const predictor = type === 1 ? left : type === 2 ? up : type === 3 ? (left + up) >> 1 : paeth(left, up, upLeft);
      raw.push((at(y, i) - predictor) & 0xff);
    }
  }
  const png = encodePng(pixels, { idat: zlib.deflateSync(Buffer.from(raw)) });
  assert.deepEqual(decodePng(png).data, pixels.data);
  // And Average (3) on its own, over a row that has one above it.
  const raw3 = [0, ...pixels.data.subarray(0, stride)];
  raw3.push(3);
  for (let i = 0; i < stride; i++) raw3.push((at(1, i) - ((at(1, i - 4) + at(0, i)) >> 1)) & 0xff);
  const two = { width: 4, height: 2, data: pixels.data.subarray(0, 2 * stride) };
  assert.deepEqual(decodePng(encodePng(two, { idat: zlib.deflateSync(Buffer.from(raw3)) })).data, two.data);
});

test('an RGB PNG (no alpha) reads as opaque RGBA', () => {
  const zlib = require('node:zlib');
  const raw = Buffer.from([0, 1, 2, 3, 4, 5, 6]); // one row, filter 0, two RGB pixels
  const png = encodePng({ width: 2, height: 1, data: Buffer.alloc(8) }, { colorType: 2, idat: zlib.deflateSync(raw) });
  assert.deepEqual([...decodePng(png).data], [1, 2, 3, 255, 4, 5, 6, 255]);
});

test('anything that is not an 8-bit, non-interlaced PNG is refused, not guessed at', () => {
  assert.throws(() => decodePng(Buffer.from('not a png')), /not a PNG/);
  const image = solid(2, 2, [1, 2, 3]);
  assert.throws(() => decodePng(encodePng(image, { bitDepth: 16 })), /8-bit/);
  assert.throws(() => decodePng(encodePng(image, { interlace: 1 })), /interlaced/);
});

test('two identical images differ by nothing', () => {
  const a = solid(40, 30, [250, 250, 249]);
  const b = solid(40, 30, [250, 250, 249]);
  assert.deepEqual(diffImages(a, b).ratio, 0);
  assert.equal(diffImages(a, b).pixels, 0);
});

test('one changed channel in one pixel counts as one different pixel', () => {
  const a = solid(100, 50, [250, 250, 249]);
  const b = solid(100, 50, [250, 250, 249]);
  setPixel(b, 99, 49, [250, 250, 248]);
  const result = diffImages(a, b);
  assert.equal(result.pixels, 1);
  assert.equal(result.ratio, 1 / 5000);
});

test('a size change counts every pixel outside the shared area as different', () => {
  const a = solid(10, 10, [0, 0, 0]);
  const b = solid(10, 12, [0, 0, 0]);
  const result = diffImages(a, b);
  assert.equal(result.width, 10);
  assert.equal(result.height, 12);
  assert.equal(result.pixels, 20);
  assert.equal(result.ratio, 20 / 120);
});

test('the diff image marks the changed pixels and keeps the rest faint', () => {
  const a = solid(3, 1, [255, 255, 255]);
  const b = solid(3, 1, [255, 255, 255]);
  setPixel(b, 1, 0, [0, 0, 0]);
  const { image } = diffImages(a, b, { image: true });
  assert.deepEqual([...image.data.subarray(4, 8)], [255, 0, 0, 255]);
  assert.notDeepEqual([...image.data.subarray(0, 4)], [255, 0, 0, 255]);
});

test('the limit is 0.1 % of the pixels, the threshold the visual baselines use', () => {
  assert.equal(DIFF_LIMIT, 0.001);
});

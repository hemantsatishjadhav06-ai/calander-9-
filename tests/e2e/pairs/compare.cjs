// The light diff's pixel comparison (plan T12), with no dependency beyond Node: reads the 8-bit,
// non-interlaced PNGs a browser writes, counts the pixels that differ, and writes a PNG that marks
// them. Its own tests: tests/js/pairs_compare.test.cjs (npm run test:ui).
const zlib = require('node:zlib');

/** A pair differs when more than this share of its pixels differ: the visual baselines' 0.1 %. */
const DIFF_LIMIT = 0.001;

const SIGNATURE = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
const CHANNELS = { 0: 1, 2: 3, 4: 2, 6: 4 }; // grey, RGB, grey + alpha, RGBA

function paeth(a, b, c) {
  const p = a + b - c;
  const pa = Math.abs(p - a);
  const pb = Math.abs(p - b);
  const pc = Math.abs(p - c);
  return pa <= pb && pa <= pc ? a : pb <= pc ? b : c;
}

/** `{ width, height, data }` with `data` as RGBA bytes, from a PNG buffer. */
function decodePng(buffer) {
  if (buffer.length < 8 || !buffer.subarray(0, 8).equals(SIGNATURE)) throw new Error('This is not a PNG file.');
  let offset = 8;
  let header = null;
  const idat = [];
  while (offset < buffer.length) {
    const length = buffer.readUInt32BE(offset);
    const type = buffer.toString('latin1', offset + 4, offset + 8);
    const body = buffer.subarray(offset + 8, offset + 8 + length);
    offset += 12 + length;
    if (type === 'IHDR') {
      header = {
        width: body.readUInt32BE(0),
        height: body.readUInt32BE(4),
        bitDepth: body[8],
        colorType: body[9],
        interlace: body[12],
      };
    } else if (type === 'IDAT') {
      idat.push(body);
    } else if (type === 'IEND') {
      break;
    }
  }
  if (!header) throw new Error('This PNG has no header.');
  const { width, height, bitDepth, colorType, interlace } = header;
  if (bitDepth !== 8) throw new Error(`Only 8-bit PNGs are read; this one is ${bitDepth}-bit.`);
  if (interlace !== 0) throw new Error('Only non-interlaced PNGs are read; this one is interlaced.');
  const channels = CHANNELS[colorType];
  if (!channels) throw new Error(`Only grey, RGB and RGBA PNGs are read; this one has colour type ${colorType}.`);

  const raw = zlib.inflateSync(Buffer.concat(idat));
  const stride = width * channels;
  if (raw.length < height * (stride + 1)) throw new Error('This PNG is shorter than its header says.');
  const rows = Buffer.alloc(height * stride);
  for (let y = 0; y < height; y++) {
    const filter = raw[y * (stride + 1)];
    const line = raw.subarray(y * (stride + 1) + 1, (y + 1) * (stride + 1));
    const out = y * stride;
    for (let i = 0; i < stride; i++) {
      const left = i >= channels ? rows[out + i - channels] : 0;
      const up = y > 0 ? rows[out - stride + i] : 0;
      const upLeft = y > 0 && i >= channels ? rows[out - stride + i - channels] : 0;
      let predictor;
      if (filter === 0) predictor = 0;
      else if (filter === 1) predictor = left;
      else if (filter === 2) predictor = up;
      else if (filter === 3) predictor = (left + up) >> 1;
      else if (filter === 4) predictor = paeth(left, up, upLeft);
      else throw new Error(`Unknown PNG filter ${filter} on row ${y}.`);
      rows[out + i] = (line[i] + predictor) & 0xff;
    }
  }

  const data = Buffer.alloc(width * height * 4);
  for (let p = 0, s = 0; p < width * height; p++, s += channels) {
    const d = p * 4;
    if (channels >= 3) {
      data[d] = rows[s];
      data[d + 1] = rows[s + 1];
      data[d + 2] = rows[s + 2];
    } else {
      data[d] = data[d + 1] = data[d + 2] = rows[s];
    }
    data[d + 3] = channels === 4 ? rows[s + 3] : channels === 2 ? rows[s + 1] : 255;
  }
  return { width, height, data };
}

function chunk(type, body) {
  const length = Buffer.alloc(4);
  length.writeUInt32BE(body.length);
  const typed = Buffer.concat([Buffer.from(type, 'latin1'), body]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(zlib.crc32(typed) >>> 0);
  return Buffer.concat([length, typed, crc]);
}

/**
 * An RGBA PNG of `{ width, height, data }`. The options exist for the tests, which need headers and
 * compressed rows a browser might write: `colorType`, `bitDepth`, `interlace` and a ready `idat`.
 */
function encodePng(image, { colorType = 6, bitDepth = 8, interlace = 0, idat = null } = {}) {
  const { width, height, data } = image;
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0);
  header.writeUInt32BE(height, 4);
  header[8] = bitDepth;
  header[9] = colorType;
  header[10] = 0;
  header[11] = 0;
  header[12] = interlace;
  let compressed = idat;
  if (!compressed) {
    const stride = width * 4;
    const raw = Buffer.alloc(height * (stride + 1));
    for (let y = 0; y < height; y++) data.copy(raw, y * (stride + 1) + 1, y * stride, (y + 1) * stride);
    compressed = zlib.deflateSync(raw);
  }
  return Buffer.concat([SIGNATURE, chunk('IHDR', header), chunk('IDAT', compressed), chunk('IEND', Buffer.alloc(0))]);
}

/**
 * How two images differ: the pixels that are not identical in every channel, over the larger of the
 * two sizes (a pixel only one image has counts as different), and that count's share of the whole.
 * With `{ image: true }`, also an RGBA image of the after side, faded, with every differing pixel red.
 */
function diffImages(before, after, { image = false } = {}) {
  const width = Math.max(before.width, after.width);
  const height = Math.max(before.height, after.height);
  const marked = image ? Buffer.alloc(width * height * 4) : null;
  let pixels = 0;
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const inBefore = x < before.width && y < before.height;
      const inAfter = x < after.width && y < after.height;
      const b = (y * before.width + x) * 4;
      const a = (y * after.width + x) * 4;
      let differs = !(inBefore && inAfter);
      if (!differs) {
        differs =
          before.data[b] !== after.data[a] ||
          before.data[b + 1] !== after.data[a + 1] ||
          before.data[b + 2] !== after.data[a + 2] ||
          before.data[b + 3] !== after.data[a + 3];
      }
      if (differs) pixels++;
      if (marked) {
        const m = (y * width + x) * 4;
        if (differs) {
          marked[m] = 255;
          marked[m + 1] = 0;
          marked[m + 2] = 0;
        } else {
          // The after side at a quarter strength over white, so the red marks stand out.
          for (let c = 0; c < 3; c++) marked[m + c] = 255 - ((255 - after.data[a + c]) >> 2);
        }
        marked[m + 3] = 255;
      }
    }
  }
  const total = width * height;
  return { width, height, pixels, ratio: total ? pixels / total : 0, image: marked ? { width, height, data: marked } : null };
}

module.exports = { DIFF_LIMIT, decodePng, encodePng, diffImages };

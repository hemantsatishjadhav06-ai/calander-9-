// The axe helper itself: it fails a page with a serious or critical WCAG 2.2 AA violation, naming the
// rule, the impact, the element and the help page, and it passes a clean page.
import { expect, test } from '../support/test';

function fixturePage(body: string): string {
  return [
    '<!doctype html><html lang="en"><head><meta charset="utf-8">',
    '<meta name="viewport" content="width=device-width, initial-scale=1">',
    '<title>Axe self-check</title></head>',
    `<body><main><h1>Axe self-check</h1>${body}</main></body></html>`,
  ].join('');
}

test('the axe helper fails a page with a form control that has no label', async ({ page, axe }) => {
  await page.setContent(fixturePage('<form><input type="text" name="unlabelled"></form>'));

  const failure = await axe(page, 'unlabelled input').then(
    () => null,
    (error: Error) => error,
  );

  expect(failure, 'the helper must throw on a critical violation').not.toBeNull();
  const message = failure?.message ?? '';
  expect(message).toContain('unlabelled input');
  expect(message).toMatch(/\blabel\b/);
  expect(message).toMatch(/\b(critical|serious)\b/);
  expect(message).toMatch(/target: \S*input/);
  expect(message).toContain('https://dequeuniversity.com/rules/axe/');
});

test('the axe helper passes a page whose controls are labelled', async ({ page, axe }) => {
  await page.setContent(fixturePage('<form><label for="name">Name</label><input id="name" type="text"></form>'));

  const results = await axe(page, 'labelled input');

  const blocking = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical');
  expect(blocking).toEqual([]);
  expect(results.passes.map((rule) => rule.id)).toContain('label');
});

test('the axe helper reads colours once a fade-in has finished', async ({ page, axe }) => {
  // Text that fades in, as the account menu does when it opens: read straight away, it would be
  // half transparent and fail the contrast rule although it ends fully opaque.
  await page.setContent(
    fixturePage(
      '<p id="fade" style="color:#1a1a1a;background:#ffffff;opacity:0.1;transition:opacity 1200ms linear">Fades in</p>' +
        '<script>requestAnimationFrame(() => requestAnimationFrame(() => {' +
        ' document.getElementById("fade").style.opacity = "1"; }));</script>',
    ),
  );

  const results = await axe(page, 'fade-in');

  expect(results.violations.filter((violation) => violation.id === 'color-contrast')).toEqual([]);
  expect(results.passes.map((rule) => rule.id)).toContain('color-contrast');
});

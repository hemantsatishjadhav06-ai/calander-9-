export async function withCpuSlowdown(cdp, measure) {
  try {
    await cdp.send('Emulation.setCPUThrottlingRate', { rate: 4 });
    return await measure();
  } finally {
    try { await cdp.send('Emulation.setCPUThrottlingRate', { rate: 1 }); }
    finally { await cdp.detach(); }
  }
}

export async function withCleanAuditTabs(context, audit) {
  const existing = new Set(context.pages());
  try { return await audit(); }
  finally {
    // Lighthouse normally closes its page. Also clean up an exceptional path so
    // a polling page cannot add work to any later sample in this browser.
    for (const page of context.pages()) if (!existing.has(page)) await page.close();
  }
}

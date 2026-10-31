// Fail-closed budget evaluation, shared by the real runner and its regression tests.
const AUDITS = {
  performance: ['categories:performance', 'minScore'],
  lcp: ['largest-contentful-paint', 'maxNumericValue'],
  cls: ['cumulative-layout-shift', 'maxNumericValue'],
  scriptBytes: ['resource-summary:script:size', 'maxNumericValue'],
};

function finite(value, label) {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) {
    throw new Error(`${label} must be a finite nonnegative number, got ${value}`);
  }
  return value;
}

export function validateBaseURL(value) {
  const url = new URL(value);
  if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1' || !url.port || url.username || url.password || url.pathname !== '/' || url.search || url.hash) {
    throw new Error('Lighthouse needs an explicit http://127.0.0.1:PORT loopback origin, never production.');
  }
  return url.origin;
}

export function validateConfig(config) {
  if (config.ci?.collect?.numberOfRuns !== 3 || config.ci.collect.settings?.formFactor !== 'mobile' || config.ci.collect.url?.length !== 3) {
    throw new Error('Lighthouse requires three mobile runs on each of the three target URLs.');
  }
  for (const [name, field] of Object.values(AUDITS)) {
    const assertion = config.ci.assert?.assertions?.[name];
    if (!assertion || assertion[0] !== 'error') throw new Error(`${name} must be an error budget.`);
    finite(assertion[1]?.[field], name);
  }
  finite(config.smbean?.interactionToNextPaintMaxMs, 'lab INP budget');
  finite(config.smbean?.javascriptGzipMaxBytes, 'gzipped JavaScript budget');
  for (const path of config.ci.collect.url) {
    if (!path.startsWith('/workspace/') || path.startsWith('//') || new URL(path, 'http://127.0.0.1').origin !== 'http://127.0.0.1') {
      throw new Error('Lighthouse target paths must stay in the seeded workspace.');
    }
  }
}

export function median(values) {
  if (values.length !== 3) throw new Error('A median requires all three runs.');
  return values.map((v) => finite(v, 'metric')).sort((a, b) => a - b)[1];
}

export function measurements(lhr, interaction, gzipBytes) {
  if (lhr.runtimeError) throw new Error(`Lighthouse runtime failure: ${lhr.runtimeError.code}`);
  if (lhr.requestedUrl !== lhr.finalDisplayedUrl) throw new Error('Lighthouse target redirected; refusing to measure a login/error page.');
  if (!interaction || !Number.isInteger(interaction.interactionCount) || interaction.interactionCount < 1) {
    throw new Error('No real interaction was measured; lab INP is unknown.');
  }
  const script = lhr.audits?.['resource-summary']?.details?.items?.find((item) => item.resourceType === 'script');
  return {
    performance: finite(lhr.categories?.performance?.score, 'performance'),
    lcp: finite(lhr.audits?.['largest-contentful-paint']?.numericValue, 'largest-contentful-paint'),
    cls: finite(lhr.audits?.['cumulative-layout-shift']?.numericValue, 'cumulative-layout-shift'),
    tbt: finite(lhr.audits?.['total-blocking-time']?.numericValue, 'total-blocking-time'),
    scriptBytes: finite(script?.transferSize, 'script transfer bytes'),
    gzipBytes: finite(gzipBytes, 'gzipped JavaScript bytes'),
    inp: finite(interaction.inpUpperBoundMs, 'lab INP upper bound'),
  };
}

export function interactionSummary(entries, interactionCount) {
  if (!Number.isInteger(interactionCount) || interactionCount < 1) throw new Error('No real interaction was measured.');
  // Event Timing quantizes durations in 8 ms steps. One full step of headroom also
  // covers interactions omitted by the API's minimum durationThreshold of 16 ms.
  const upperBound = Math.max(16, ...entries.map((entry) => finite(entry.duration, 'event duration'))) + 8;
  return { inpUpperBoundMs: upperBound, interactionCount, durationThresholdMs: 16, quantizationHeadroomMs: 8, cpuSlowdown: 4, entries };
}

export function evaluate(samples, config) {
  validateConfig(config);
  if (samples.length !== 3) throw new Error('All three runs must complete; a failed run cannot be discarded.');
  const limits = Object.fromEntries(Object.entries(AUDITS).map(([key, [name, field]]) => [key, config.ci.assert.assertions[name][1][field]]));
  limits.inp = config.smbean.interactionToNextPaintMaxMs;
  limits.gzipBytes = config.smbean.javascriptGzipMaxBytes;
  const medians = Object.fromEntries([...Object.keys(limits), 'tbt'].map((key) => [key, median(samples.map((sample) => sample[key]))]));
  const failures = Object.entries(limits).filter(([key, limit]) => key === 'performance' ? medians[key] < limit : medians[key] > limit)
    .map(([metric, limit]) => ({ metric, actual: medians[metric], limit }));
  return { passed: failures.length === 0, medians, limits, failures };
}

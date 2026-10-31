// The whole run's network check (spec R2). The server's socket guard and provider mock refuse every
// connection off the machine and record it. This global setup notes when the run starts and returns
// the teardown, which Playwright runs once after the last test and before it stops the server: it
// asks the server what it refused since then, and fails the run if anything was, naming each host
// and where in the server it was tried. Only this run counts, so a server kept running between runs
// (reuseExistingServer) never blames this run for an earlier one.
import { type FullConfig, request } from '@playwright/test';

type Refusal = {
  host: string;
  at: number;
  kind?: string;
  port?: number | null;
  method?: string;
  url?: string;
  where?: string;
};

type Refused = { hosts: string[]; refused: Refusal[]; unanswered: Refusal[] };

function describe(item: Refusal): string {
  const what = item.url ? `${item.method ?? ''} ${item.url}`.trim() : `${item.kind ?? 'connect'} ${item.host}:${item.port ?? ''}`;
  const where = item.where ? `\n${item.where.trimEnd().split('\n').slice(-4).join('\n')}` : '';
  return `- ${new Date(item.at * 1000).toISOString()} ${what}${where}`;
}

export default async function globalSetup(config: FullConfig): Promise<() => Promise<void>> {
  const baseURL = String(config.projects[0]?.use.baseURL);
  const since = Date.now() / 1000;

  return async () => {
    const context = await request.newContext({ baseURL });
    try {
      const response = await context.get('/__e2e__/probe/refused_network', { params: { since: String(since) } });
      if (!response.ok()) {
        throw new Error(`The e2e server's refused-network probe answered ${response.status()} at the end of the run.`);
      }
      const body = (await response.json()) as Refused;
      if (body.hosts.length > 0) {
        const items = [...body.refused, ...body.unanswered].sort((a, b) => a.at - b.at).map(describe);
        throw new Error(
          `During this run the e2e server tried to reach ${body.hosts.join(', ')}; nothing may leave the machine ` +
            '(spec R2). Mock the call (tests/e2e/server/mocks.py) or keep the path from making it.\n' +
            items.join('\n'),
        );
      }
    } finally {
      await context.dispose();
    }
  };
}

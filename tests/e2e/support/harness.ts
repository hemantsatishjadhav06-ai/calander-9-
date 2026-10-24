// The e2e server's named fixtures and probes, from a spec. See tests/e2e/README.md for the contract.
import type { APIRequestContext } from '@playwright/test';

export type Role = 'owner' | 'manager' | 'editor' | 'client' | 'owner_b';

export type UserRef = { id: string; email: string };

export type AccountRef = { id: string; platform_id: string; name: string };

/** What GET /__e2e__/ping returns under `ids`: the seeded world (tests/e2e/server/seed.py). */
export type HarnessIds = {
  workspace_a: string;
  workspace_b: string;
  organisation_a: string;
  organisation_b: string;
  workspace_names: { a: string; b: string };
  users: Record<Role, UserRef>;
  accounts: Record<'linkedin_company' | 'instagram' | 'facebook', AccountRef>;
  library_asset: { id: string; title: string };
  /** Every seeded person's password; only golden path 1 posts the login form with it. */
  password: string;
  timezone: string;
};

export type SessionResult = {
  cookie: { name: string; value: string };
  user: UserRef;
};

export type ProbeParams = Record<string, string | number | boolean>;

export class HarnessError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = 'HarnessError';
  }
}

async function errorText(response: Awaited<ReturnType<APIRequestContext['get']>>): Promise<string> {
  try {
    const body = (await response.json()) as { error?: string };
    return body.error ?? JSON.stringify(body);
  } catch {
    return (await response.text()).slice(0, 300);
  }
}

export class Harness {
  constructor(
    private readonly request: APIRequestContext,
    readonly ids: HarnessIds,
  ) {}

  /** Reach the server's ping and read the seeded ids; fails loudly when the server is not the e2e one. */
  static async connect(request: APIRequestContext): Promise<Harness> {
    const response = await request.get('/__e2e__/ping');
    if (!response.ok()) {
      throw new HarnessError(
        `The e2e harness did not answer /__e2e__/ping (${response.status()}): ${await errorText(response)}. ` +
          'Is the server the e2e one (python -m tests.e2e.server --reset)?',
        response.status(),
      );
    }
    const body = (await response.json()) as { ok: boolean; ids: HarnessIds };
    return new Harness(request, body.ids);
  }

  /** POST /__e2e__/fixture/<name>: create fresh rows for this test and return what the fixture says. */
  async fixture<T = Record<string, unknown>>(name: string, payload: Record<string, unknown> = {}): Promise<T> {
    const response = await this.request.post(`/__e2e__/fixture/${encodeURIComponent(name)}`, { data: payload });
    if (!response.ok()) {
      throw new HarnessError(`e2e fixture '${name}' answered ${response.status()}: ${await errorText(response)}`, response.status());
    }
    return (await response.json()) as T;
  }

  /** GET /__e2e__/probe/<name>?k=v: read the rows this test asserts on. */
  async probe<T = Record<string, unknown>>(name: string, params: ProbeParams = {}): Promise<T> {
    const query = Object.fromEntries(Object.entries(params).map(([key, value]) => [key, String(value)]));
    const response = await this.request.get(`/__e2e__/probe/${encodeURIComponent(name)}`, { params: query });
    if (!response.ok()) {
      throw new HarnessError(`e2e probe '${name}' answered ${response.status()}: ${await errorText(response)}`, response.status());
    }
    return (await response.json()) as T;
  }
}

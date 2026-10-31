// Complement the route sweep without changing its invariant assertions: an authorised URL in A
// must still scope object ids supplied in a form body or query string. All requests carry the
// signed-in browser's session and a valid CSRF cookie, so a CSRF refusal cannot hide a bad lookup.
import { expect, test } from '../support/test';

type ForeignObjects = {
  workspace_id: string;
  workspace_name: string;
  objects: Record<string, string>;
};

for (const role of ['owner', 'editor'] as const) {
  test(`the ${role} cannot act on B's rows through A's form bodies or read B's thread through a query`, async ({
    page,
    harness,
    as,
    axe,
    network,
  }) => {
    const foreign = await harness.fixture<ForeignObjects>('isolation_b_objects');
    const base = `/workspace/${harness.ids.workspace_a}`;
    const before = await harness.probe('isolation_b_state', foreign.objects);
    await as(role);
    expect((await page.goto(`${base}/studio/`))?.status()).toBe(200);
    await expect(page.getByTestId('home-today')).toBeVisible();
    await axe(page, `Home before foreign inputs (${role})`);
    const csrf = (await page.context().cookies()).find((cookie) => cookie.name === 'csrftoken')?.value;
    expect(csrf, 'Home sets the CSRF cookie for the signed-in browser').toBeTruthy();
    const headers = { 'X-CSRFToken': String(csrf) };

    // A control reaches the real rescheduling view and its input validation, rather than CSRF or
    // membership middleware. The foreign-id request below supplies every required input.
    const control = await page.request.post(`${base}/calendar/reschedule/`, {
      headers,
      form: {},
      maxRedirects: 0,
    });
    expect(control.status()).toBe(400);
    expect(await control.json()).toEqual({ error: 'platform_post_id and new_datetime required' });

    const moved = await page.request.post(`${base}/calendar/reschedule/`, {
      headers,
      form: {
        platform_post_id: foreign.objects.platform_post_id,
        new_datetime: new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString(),
      },
      maxRedirects: 0,
    });
    expect(moved.status(), 'a foreign platform-post id in the form body is not found in A').toBe(404);
    expect(await moved.text()).not.toContain(foreign.workspace_name);

    // Bulk delete deliberately answers an empty selection as a successful no-op. Assert the
    // exact count as well as the foreign workspace snapshot, rather than accepting any 200.
    const deleted = await page.request.post(`${base}/calendar/bulk-action/`, {
      headers,
      form: { action: 'delete', platform_post_ids: foreign.objects.platform_post_id },
      maxRedirects: 0,
    });
    expect(deleted.status()).toBe(200);
    expect(await deleted.json()).toEqual({ action: 'delete', count: 0 });

    const thread = await page.goto(`${base}/studio/thread/?c=${foreign.objects.conversation_id}`);
    expect(thread?.status(), 'a foreign conversation id in the query is not found in A').toBe(404);
    expect(await thread!.text()).not.toContain(foreign.workspace_name);
    await axe(page, `Foreign thread query refused (${role})`);
    expect(await harness.probe('isolation_b_state', foreign.objects), "every row in B remains unchanged").toEqual(before);
    expect(network.blocked).toEqual([]);
  });
}

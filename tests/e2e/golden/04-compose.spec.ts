// Golden path 4 (docs/specs/01-harness.md): write a post myself, with its own wording for one
// account and a picture from the media library, and submit it for approval.
//
// Compose on workspace A: the LinkedIn company page and Instagram, one caption, Own wording for
// LinkedIn with a different caption, the seeded library image from the Media library picker, then
// Submit for approval. In the database: one platform post per account, both waiting for review; the
// override caption on the LinkedIn one only; the library image attached first (position 0); and a
// "submitted" approval action by the author. The owner and an editor both can; a client is refused
// the composer.
//
// The channel pills are toggle buttons: LinkedIn is pressed with a click, Instagram with the keyboard,
// and each says it is selected (aria-pressed). Axe runs once each screen, the picker and the saved
// toast have finished appearing.
import { settled } from '../support/settled';
import { expect, test } from '../support/test';

type PublishingPost = {
  post: { id: string; caption: string; author: string | null; proposed_publish_at: string | null } | null;
  platform_posts: {
    id: string;
    account_id: string;
    platform: string;
    status: string;
    platform_specific_caption: string | null;
  }[];
  media: { asset_id: string; position: number }[];
  actions: { action: string; channel: string; user: string | null; platform_post_id: string | null }[];
};

const POST_URL = /\/compose\/([0-9a-f-]{36})\//;

for (const role of ['owner', 'editor'] as const) {
  test(`${role} writes a post with its own wording for LinkedIn and a library image, and submits it for approval`, async ({
    page,
    as,
    axe,
    harness,
    network,
  }) => {
    const since = Date.now() / 1000;
    const { workspace_a: workspace, accounts, library_asset: asset, users } = harness.ids;
    const linkedin = accounts.linkedin_company;
    const instagram = accounts.instagram;
    const marker = `E2E path 4 ${role} ${Date.now()}`;
    const caption = `${marker}. Site visits run every Saturday at the Kokapet site office, 10:00 to 17:00.`;
    const ownWording = `${marker}. For LinkedIn: our Kokapet site office opens for visits every Saturday.`;

    await as(role);
    const response = await page.goto(`/workspace/${workspace}/compose/`);
    expect(response?.status()).toBe(200);
    await expect(page.getByTestId('compose-caption')).toBeVisible();
    await settled(page.getByTestId('compose-caption'), 'the composer');
    await axe(page, `Compose (${role})`);

    // Two accounts (one by click, one from the keyboard) and one caption.
    const linkedinPill = page.getByTestId(`compose-account-${linkedin.id}`);
    const instagramPill = page.getByTestId(`compose-account-${instagram.id}`);
    await expect(linkedinPill).toHaveAttribute('aria-pressed', 'false');
    await expect(instagramPill).toHaveAttribute('aria-pressed', 'false');
    await linkedinPill.click();
    await instagramPill.press('Enter');
    await expect(linkedinPill).toHaveAttribute('aria-pressed', 'true');
    await expect(instagramPill).toHaveAttribute('aria-pressed', 'true');
    await page.getByTestId('compose-caption').fill(caption);

    // Own wording for LinkedIn only.
    await page.getByTestId(`compose-override-toggle-${linkedin.id}`).click();
    const override = page.getByTestId(`compose-override-caption-${linkedin.id}`);
    await expect(override).toBeVisible();
    await override.fill(ownWording);
    await expect(page.getByTestId(`compose-override-caption-${instagram.id}`)).toBeHidden();

    // The seeded image from the Media library picker.
    await page.getByTestId('compose-media-library').click();
    const picker = page.getByTestId('compose-media-picker');
    await expect(picker).toBeVisible();
    await expect(page.getByRole('dialog', { name: 'Media library' })).toBeVisible();
    const tile = picker.getByTestId(`compose-media-picker-asset-${asset.id}`);
    await expect(tile).toBeVisible();
    await settled(picker, 'the Media library picker');
    await axe(page, `Media library picker (${role})`, { include: '[data-testid="compose-media-picker"]' });
    await tile.click();
    await expect(picker).toBeHidden();
    await expect(page.getByTestId(`compose-media-item-${asset.id}`)).toBeVisible();

    // Submit for approval: the composer stays and moves to the post's own address.
    await page.getByTestId('compose-submit-for-approval').click();
    await expect(page).toHaveURL(POST_URL);
    const postId = POST_URL.exec(page.url())![1];
    await expect(page.getByTestId('compose-saved-toast')).toBeVisible();
    await settled(page.getByTestId('compose-saved-toast'), 'the saved toast');
    await axe(page, `Compose after Submit for approval (${role})`);

    const saved = await harness.probe<PublishingPost>('publishing_post', { post_id: postId });
    expect(saved.post?.caption).toBe(caption);
    expect(saved.post?.author).toBe(users[role].email);

    // One platform post per account, both waiting for review; the own wording only on LinkedIn.
    const byAccount = Object.fromEntries(saved.platform_posts.map((pp) => [pp.account_id, pp]));
    expect(saved.platform_posts).toHaveLength(2);
    expect(Object.keys(byAccount).sort()).toEqual([linkedin.id, instagram.id].sort());
    expect(byAccount[linkedin.id].status).toBe('pending_review');
    expect(byAccount[instagram.id].status).toBe('pending_review');
    expect(byAccount[linkedin.id].platform_specific_caption).toBe(ownWording);
    expect(byAccount[instagram.id].platform_specific_caption).toBeNull();

    // The library image, first.
    expect(saved.media).toEqual([{ asset_id: asset.id, position: 0 }]);

    // Submitted, by the author, from the dashboard.
    const submitted = saved.actions.filter((action) => action.action === 'submitted');
    expect(submitted).toHaveLength(1);
    expect(submitted[0].user).toBe(users[role].email);
    expect(submitted[0].channel).toBe('dashboard');
    expect(saved.actions.some((action) => action.action === 'approved')).toBe(false);

    expect(network.blocked).toEqual([]);
    expect((await harness.probe<{ hosts: string[] }>('refused_network', { since })).hosts).toEqual([]);
  });
}

test('a client is refused the composer', async ({ page, as, axe, harness }) => {
  const { workspace_a: workspace } = harness.ids;

  await as('client');
  const response = await page.goto(`/workspace/${workspace}/compose/`);

  expect(response?.status()).toBe(403);
  await expect(page.getByTestId('compose-caption')).toHaveCount(0);
  await expect(page.getByTestId('compose-submit-for-approval')).toHaveCount(0);
  await axe(page, 'Composer refused (client)');
});

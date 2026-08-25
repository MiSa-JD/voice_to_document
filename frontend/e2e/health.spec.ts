import { expect, test } from '@playwright/test';

test('브라우저에서 준비 상태와 404를 구분한다', async ({ page, request }) => {
  await page.goto('/service-status');

  await expect(
    page.getByRole('heading', { name: '서비스 준비 상태' }),
  ).toBeVisible();
  await expect(page.getByText('준비 완료')).toBeVisible();

  const apiMissing = await request.get('/api/does-not-exist');
  expect(apiMissing.status()).toBe(404);
  expect(apiMissing.headers()['content-type']).toContain('application/json');

  await page.goto('/');
  await expect(
    page.getByRole('heading', { name: '녹음 대시보드' }),
  ).toBeVisible();

  await page.goto('/does-not-exist');
  await expect(
    page.getByRole('heading', { name: '페이지를 찾을 수 없습니다' }),
  ).toBeVisible();
});

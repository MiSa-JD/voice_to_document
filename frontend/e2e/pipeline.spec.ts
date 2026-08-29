import { copyFile } from 'node:fs/promises';
import path from 'node:path';

import { expect, test } from '@playwright/test';

test('pipeline flow: fixture가 대시보드와 상세 결과에 표시된다', async ({
  page,
  request,
}) => {
  const dataRoot = process.env.E2E_DATA_ROOT;
  expect(dataRoot, 'E2E_DATA_ROOT가 필요합니다.').toBeTruthy();
  await copyFile(
    path.resolve('..', 'backend/tests/fixtures/complete.m4a'),
    path.join(dataRoot!, 'inbox', 'e2e-complete.m4a'),
  );

  await expect
    .poll(
      async () => {
        const response = await request.get('/api/recordings');
        const body = (await response.json()) as {
          items: Array<{ status: string }>;
        };
        return body.items[0]?.status;
      },
      { timeout: 30_000 },
    )
    .toBe('COMPLETED');

  await page.goto('/');
  const recording = page.getByRole('link', { name: /e2e-complete.m4a/ });
  await expect(recording).toBeVisible();
  await expect(recording).toContainText('완료');
  await recording.click();

  await expect(
    page.getByRole('heading', { name: 'e2e-complete.m4a' }),
  ).toBeVisible();
  await expect(
    page.getByText('오늘 회의의 목표를 확인하겠습니다.'),
  ).toBeVisible();
  await expect(
    page.getByText('다음 주까지 초안을 준비하겠습니다.'),
  ).toBeVisible();
  await expect(page.getByText('범주: 회의')).toBeVisible();
});

test('restart preservation: worker 재시작 뒤 결과가 유지된다', async ({
  page,
  request,
}) => {
  const response = await request.get('/api/recordings');
  const body = (await response.json()) as {
    items: Array<{ id: string; status: string }>;
    total: number;
  };
  expect(body.total).toBe(1);
  expect(body.items[0]?.status).toBe('COMPLETED');

  await page.goto(`/recordings/${body.items[0]!.id}`);
  await expect(
    page.getByRole('heading', { name: 'e2e-complete.m4a' }),
  ).toBeVisible();
  await expect(page.getByText('범주: 회의')).toBeVisible();

  const detail = await request.get(`/api/recordings/${body.items[0]!.id}`);
  const payload = (await detail.json()) as {
    artifacts: Array<{ kind: string }>;
    jobs: Array<{ status: string }>;
  };
  expect(payload.artifacts.map((artifact) => artifact.kind).sort()).toEqual([
    'recording_audio',
    'transcript_json',
    'transcript_markdown',
  ]);
  expect(payload.jobs).toHaveLength(2);
  expect(payload.jobs.every((job) => job.status === 'succeeded')).toBe(true);
});

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

  const detailResponse = await request.get('/api/recordings');
  const detailBody = (await detailResponse.json()) as {
    items: Array<{ id: string }>;
  };
  const recordingId = detailBody.items[0]!.id;
  await page.goto(`/recordings/${recordingId}/speakers`);
  const clip = page.getByLabel('SPEAKER_00 대표 클립');
  const reviewAudio = (await clip.count())
    ? clip
    : page.getByLabel('녹음 전체 오디오');
  await expect(reviewAudio).toBeVisible();
  await reviewAudio.focus();
  await page.keyboard.press('Space');

  await page
    .getByRole('combobox', { name: '선택 발화 변경 인물' })
    .selectOption('__new__');
  await expect(
    page.getByRole('textbox', { name: '새 인물 이름' }),
  ).toBeFocused();
  await page.getByRole('textbox', { name: '새 인물 이름' }).fill('E2E 검토자');
  await page.getByRole('button', { name: '인물 만들기' }).click();
  await page.getByRole('checkbox', { name: '00:00 발화 선택' }).check();
  await page.getByRole('button', { name: '변경 확인' }).click();
  await page.getByRole('button', { name: '일괄 저장' }).click();

  await expect
    .poll(async () => {
      const result = await request.get(`/api/recordings/${recordingId}`);
      const payload = (await result.json()) as {
        jobs: Array<{ kind: string; status: string }>;
      };
      return payload.jobs.find((job) => job.kind === 'render')?.status;
    })
    .toBe('succeeded');
  await expect(
    page.locator('.transcript').getByText('E2E 검토자'),
  ).toBeVisible();

  await page.goto(`/recordings/${recordingId}`);
  await page.getByRole('button', { name: '재전사 설정 열기' }).click();
  await page.getByLabel('녹음 언어').selectOption('en');
  await page.getByLabel('대략적인 내용 설명 (선택)').fill('E2E 내용 설명');
  await page.getByLabel('고유명사·전문용어 (선택)').fill('E2E-term, WhisperX');
  await page.getByRole('button', { name: '영향 확인' }).click();
  const beforeSubmit = await request.get(
    `/api/recordings/${recordingId}/retranscriptions/latest`,
  );
  expect(beforeSubmit.status()).toBe(404);
  await page
    .getByRole('button', { name: '영향을 확인했고 STT 다시 수행' })
    .click();

  await expect
    .poll(async () => {
      const result = await request.get(
        `/api/recordings/${recordingId}/retranscriptions/latest`,
      );
      if (!result.ok()) return 'waiting';
      const payload = (await result.json()) as { status: string };
      return payload.status;
    })
    .toBe('succeeded');
  await expect(page.getByText('재전사 완료')).toBeVisible();
  await expect(page.getByText('ko → en')).toBeVisible();
  await expect(
    page.getByRole('link', { name: '화자 다시 검토' }),
  ).toBeVisible();
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
  expect(new Set(payload.artifacts.map((artifact) => artifact.kind))).toEqual(
    new Set(['recording_audio', 'transcript_json', 'transcript_markdown']),
  );
  expect(payload.artifacts).toHaveLength(7);
  expect(payload.jobs).toHaveLength(5);
  expect(payload.jobs.every((job) => job.status === 'succeeded')).toBe(true);
});

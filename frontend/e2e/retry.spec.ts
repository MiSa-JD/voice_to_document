import { execFileSync } from 'node:child_process';
import { expect, test } from '@playwright/test';

test('실패한 문서 작업을 UI에서 재시도하고 기존 전사를 보존한다', async ({
  page,
  request,
}) => {
  test.skip(
    process.env.E2E_RETRY_SCENARIO !== '1' ||
      process.env.E2E_RETRY_SCENARIO !== '1' ||
      !process.env.E2E_DATA_ROOT ||
      process.env.DOCUMENT_MODE === 'real',
    '격리 fake Compose 전용',
  );
  const list = await (await request.get('/api/recordings')).json();
  const recording = list.items[0];
  expect(recording).toBeTruthy();
  const before = await (
    await request.get(`/api/recordings/${recording.id}`)
  ).json();
  execFileSync('docker', ['compose', 'stop', 'worker'], {
    cwd: '..',
    stdio: 'pipe',
  });
  try {
    const changed = await request.patch(
      `/api/recordings/${recording.id}/category`,
      {
        data: {
          expected_revision: recording.revision,
          category: recording.category === '회의' ? '일상 대화' : '회의',
        },
      },
    );
    expect(changed.status()).toBe(200);
    execFileSync(
      'docker',
      [
        'compose',
        'exec',
        '-T',
        'api',
        'python',
        '-c',
        [
          'from app.config import Settings',
          'from app.jobs import claim_next_job, fail_job',
          's = Settings()',
          'job = claim_next_job(s.database_path)',
          'assert job is not None and job.kind == "render"',
          'fail_job(s.database_path, job.id, "ARTIFACT_IO_ERROR", "storage unavailable")',
        ].join('\n'),
      ],
      { cwd: '..', stdio: 'pipe' },
    );
    await page.goto(`/recordings/${recording.id}`);
    await expect(page.getByText('ARTIFACT_IO_ERROR')).toBeVisible();
    const retry = page.getByRole('button', {
      name: '문서 반영 작업 다시 시도',
    });
    await retry.focus();
    await page.keyboard.press('Enter');
    await expect(page.getByText('재시도 작업을 등록했습니다.')).toBeVisible();
  } finally {
    execFileSync('docker', ['compose', 'start', 'worker'], {
      cwd: '..',
      stdio: 'pipe',
    });
  }
  await expect
    .poll(
      async () => {
        const detail = await (
          await request.get(`/api/recordings/${recording.id}`)
        ).json();
        return detail.jobs.filter(
          (job: { kind: string; status: string }) =>
            job.kind === 'render' && job.status === 'succeeded',
        ).length;
      },
      { timeout: 30_000 },
    )
    .toBeGreaterThan(0);
  const after = await (
    await request.get(`/api/recordings/${recording.id}`)
  ).json();
  expect(
    after.segments.map((segment: { id: string; text: string }) => [
      segment.id,
      segment.text,
    ]),
  ).toEqual(
    before.segments.map((segment: { id: string; text: string }) => [
      segment.id,
      segment.text,
    ]),
  );
  expect(
    after.jobs.some((job: { status: string }) => job.status === 'failed'),
  ).toBeTruthy();
  await expect(
    page.getByRole('button', { name: '문서 반영 작업 다시 시도' }),
  ).toHaveCount(0);
});

import { execFileSync } from 'node:child_process';
import { expect, test } from '@playwright/test';

test('실제 모드 API에서 실패 이력을 조회하고 실행 없이 재시도를 등록한다', async ({
  page,
  request,
}) => {
  test.skip(
    process.env.E2E_REAL_RECOVERY_SCENARIO !== '1' ||
      !process.env.E2E_DATA_ROOT ||
      process.env.SPEECH_MODE !== 'real' ||
      process.env.DOCUMENT_MODE !== 'real',
    'worker를 중지한 격리 real/real Compose 전용',
  );
  const runningWorkers = execFileSync(
    'docker',
    ['compose', 'ps', '--status', 'running', '-q', 'worker'],
    { cwd: '..', encoding: 'utf8' },
  );
  expect(runningWorkers.trim()).toBe('');
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
        's = Settings()',
        'assert s.effective_speech_mode == s.effective_document_mode == "real"',
        'assert not s.model_cache_root.exists()',
        'assert not s.llm_api_key and not s.hf_token',
      ].join('\n'),
    ],
    { cwd: '..', stdio: 'pipe' },
  );
  const list = await (await request.get('/api/recordings')).json();
  const recording = list.items[0];
  const response = await request.get(`/api/recordings/${recording.id}`);
  expect(response.status()).toBe(200);
  const before = await response.json();
  expect(before.recording.status).toBe('COMPLETED');
  expect(before.segments.length).toBeGreaterThan(0);
  expect(
    before.jobs.some((job: { status: string }) => job.status === 'failed'),
  ).toBeTruthy();
  await page.goto(`/recordings/${recording.id}`);
  await expect(page.getByText('ARTIFACT_IO_ERROR').first()).toBeVisible();

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
        'fail_job(s.database_path, job.id, "ARTIFACT_IO_ERROR", "synthetic storage failure")',
      ].join('\n'),
    ],
    { cwd: '..', stdio: 'pipe' },
  );
  const failed = await (
    await request.get(`/api/recordings/${recording.id}`)
  ).json();
  const original = failed.jobs.find(
    (job: { recovery_action: string }) => job.recovery_action === 'retry',
  );
  expect(original).toBeTruthy();
  await page.reload();
  await page.getByRole('button', { name: '문서 반영 작업 다시 시도' }).click();
  await expect(page.getByText('재시도 작업을 등록했습니다.')).toBeVisible();
  const repeated = await request.post(`/api/recordings/${recording.id}/retry`, {
    data: { job_id: original.id, expected_revision: failed.recording.revision },
  });
  expect(repeated.status()).toBe(202);
  const retry = await repeated.json();
  expect(retry.created).toBe(false);
  const after = await (
    await request.get(`/api/recordings/${recording.id}`)
  ).json();
  expect(
    after.jobs.find((job: { id: string }) => job.id === original.id).status,
  ).toBe('failed');
  expect(
    after.jobs.find((job: { id: string }) => job.id === retry.job_id).status,
  ).toBe('queued');
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
});

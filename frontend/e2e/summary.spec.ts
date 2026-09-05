import { copyFile, readFile, readdir } from 'node:fs/promises';
import path from 'node:path';

import { expect, test, type APIRequestContext } from '@playwright/test';

type Detail = {
  recording: { id: string; revision: number; category: string };
  segments: Array<{ local_speaker_id: string }>;
  summary_status: string;
  summary_policy: string;
  summary_can_request: boolean;
  summary: unknown;
  jobs: Array<{ kind: string; status: string; input_revision: number }>;
};

const scenario = process.env.E2E_SUMMARY_SCENARIO;
test.skip(
  process.env.DOCUMENT_MODE !== 'real' || !scenario,
  '실제 summary mode 전용 E2E입니다.',
);

async function ingestAndWait(request: APIRequestContext) {
  const dataRoot = process.env.E2E_DATA_ROOT!;
  await copyFile(
    path.resolve('..', 'backend/tests/fixtures/complete.m4a'),
    path.join(dataRoot, 'inbox', `openai-summary-${scenario}.m4a`),
  );
  await expect
    .poll(
      async () => {
        const response = await request.get('/api/recordings');
        const body = (await response.json()) as {
          items: Array<{ id: string; status: string }>;
        };
        return body.items[0]?.status;
      },
      { timeout: 90_000 },
    )
    .toBe('COMPLETED');
  const list = await request.get('/api/recordings');
  const body = (await list.json()) as { items: Array<{ id: string }> };
  return body.items[0]!.id;
}

async function detail(request: APIRequestContext, id: string) {
  return (await (await request.get(`/api/recordings/${id}`)).json()) as Detail;
}

async function verifyArtifacts(dataRoot: string, current: Detail) {
  const categorySlug = current.recording.category.replaceAll(' ', '-');
  const categoryDirectory = path.join(
    dataRoot,
    'document output',
    categorySlug,
  );
  const jsonFiles = (
    await readdir(categoryDirectory, { recursive: true })
  ).filter((name) => name.endsWith('.json'));
  const markdownFiles = (
    await readdir(categoryDirectory, { recursive: true })
  ).filter((name) => name.endsWith('.md'));
  const jsonFile = jsonFiles.find((name) =>
    name.endsWith(`/revisions/${current.recording.revision}.json`),
  );
  const markdownFile = markdownFiles.find((name) =>
    name.endsWith(`/revisions/${current.recording.revision}.md`),
  );
  expect(jsonFile).toBeTruthy();
  expect(markdownFile).toBeTruthy();
  const metadata = JSON.parse(
    await readFile(path.join(categoryDirectory, jsonFile!), 'utf8'),
  ) as { revision: number; category: string; summary: unknown };
  const markdown = await readFile(
    path.join(categoryDirectory, markdownFile!),
    'utf8',
  );
  expect(metadata).toMatchObject({
    revision: current.recording.revision,
    category: current.recording.category,
    summary: current.summary,
  });
  expect(markdown).toContain(`범주: ${current.recording.category}`);
}

test('actual summary automatic: 자동 요약, stale 재생성, 재시작 멱등성', async ({
  page,
  request,
}) => {
  test.skip(scenario !== 'automatic');
  const recordingId = await ingestAndWait(request);
  let current = await detail(request, recordingId);
  expect(current.recording.category).toBe('회의');
  expect(current.summary_policy).toBe('automatic');
  expect(current.summary_status).toBe('succeeded');
  expect(current.summary).not.toBeNull();
  expect(current.jobs.filter((job) => job.kind === 'summarize')).toHaveLength(
    1,
  );

  await page.goto(`/recordings/${recordingId}`);
  await expect(page.getByText('최신 transcript의 요약입니다.')).toBeVisible();
  await verifyArtifacts(process.env.E2E_DATA_ROOT!, current);

  const person = await request.post('/api/persons', {
    data: { display_name: '합성 검토자' },
  });
  const personId = ((await person.json()) as { id: string }).id;
  const changed = await request.put(
    `/api/recordings/${recordingId}/speakers/${current.segments[0]!.local_speaker_id}`,
    { data: { person_id: personId, expected_revision: 1 } },
  );
  expect(changed.ok()).toBeTruthy();
  const stale = await detail(request, recordingId);
  expect(stale.summary_status).toBe('stale');
  expect(stale.summary).toBeNull();

  await expect
    .poll(async () => (await detail(request, recordingId)).summary_status, {
      timeout: 90_000,
    })
    .toBe('succeeded');
  current = await detail(request, recordingId);
  expect(current.recording.revision).toBe(2);
  expect(
    current.jobs.filter(
      (job) => job.kind === 'summarize' && job.input_revision === 2,
    ),
  ).toHaveLength(1);

  await verifyArtifacts(process.env.E2E_DATA_ROOT!, current);
});

test('actual summary restart: worker 재시작 뒤 job과 artifact가 중복되지 않는다', async ({
  page,
  request,
}) => {
  test.skip(scenario !== 'automatic');
  const response = await request.get('/api/recordings');
  const body = (await response.json()) as { items: Array<{ id: string }> };
  expect(body.items).toHaveLength(1);
  const current = await detail(request, body.items[0]!.id);
  expect(current.summary_status).toBe('succeeded');
  expect(current.jobs.filter((job) => job.kind === 'summarize')).toHaveLength(
    2,
  );
  await page.goto(`/recordings/${body.items[0]!.id}`);
  await expect(page.getByText('최신 transcript의 요약입니다.')).toBeVisible();
  await verifyArtifacts(process.env.E2E_DATA_ROOT!, current);
});

test('actual summary manual: 수동 요청 전 무요약, 실패 안내, 재시도 완료', async ({
  page,
  request,
}) => {
  test.skip(scenario !== 'manual');
  const recordingId = await ingestAndWait(request);
  let initial = await detail(request, recordingId);
  expect(initial.recording.category).toBe('회의');
  expect(initial.summary_policy).toBe('manual');
  expect(initial.summary_status).toBe('not_requested');
  expect(initial.summary).toBeNull();
  expect(initial.jobs.filter((job) => job.kind === 'summarize')).toHaveLength(
    0,
  );

  const categoryChange = await request.patch(
    `/api/recordings/${recordingId}/category`,
    { data: { category: '일상 대화', expected_revision: 1 } },
  );
  expect(categoryChange.ok()).toBeTruthy();
  await expect
    .poll(async () => {
      const current = await detail(request, recordingId);
      return {
        revision: current.recording.revision,
        category: current.recording.category,
        status: current.summary_status,
        canRequest: current.summary_can_request,
      };
    })
    .toEqual({
      revision: 2,
      category: '일상 대화',
      status: 'not_requested',
      canRequest: true,
    });
  initial = await detail(request, recordingId);
  expect(initial.jobs.filter((job) => job.kind === 'summarize')).toHaveLength(
    0,
  );

  await page.goto(`/recordings/${recordingId}`);
  await page.route(
    `**/api/recordings/${recordingId}/summary`,
    async (route) => {
      await route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({
          error: {
            code: 'TEMPORARY',
            message: '일시적으로 요청할 수 없습니다.',
          },
        }),
      });
    },
  );
  await page.getByRole('button', { name: '요약 요청' }).click();
  await expect(page.getByText('일시적으로 요청할 수 없습니다.')).toBeVisible();
  await page.unroute(`**/api/recordings/${recordingId}/summary`);
  await page.getByRole('button', { name: '요약 요청' }).click();
  await expect(page.getByText('요약을 요청했습니다.')).toBeVisible();

  await expect
    .poll(async () => (await detail(request, recordingId)).summary_status, {
      timeout: 90_000,
    })
    .toBe('succeeded');
  const current = await detail(request, recordingId);
  expect(current.summary).not.toBeNull();
  expect(current.jobs.filter((job) => job.kind === 'summarize')).toHaveLength(
    1,
  );
  await page.reload();
  await expect(page.getByText('최신 transcript의 요약입니다.')).toBeVisible();
  await verifyArtifacts(process.env.E2E_DATA_ROOT!, current);
});

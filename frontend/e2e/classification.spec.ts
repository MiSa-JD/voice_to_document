import { copyFile, readFile, readdir } from 'node:fs/promises';
import path from 'node:path';

import { expect, test } from '@playwright/test';

test.skip(
  process.env.DOCUMENT_MODE !== 'real',
  '실제 document mode 전용 E2E입니다.',
);

test('real OpenAI classification: 실제 분류와 수동 범주가 artifact·UI에 일치한다', async ({
  page,
  request,
}) => {
  const dataRoot = process.env.E2E_DATA_ROOT;
  expect(dataRoot, 'E2E_DATA_ROOT가 필요합니다.').toBeTruthy();
  await copyFile(
    path.resolve('..', 'backend/tests/fixtures/complete.m4a'),
    path.join(dataRoot!, 'inbox', 'openai-classification.m4a'),
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
      { timeout: 60_000 },
    )
    .toBe('COMPLETED');

  const list = await request.get('/api/recordings');
  const listBody = (await list.json()) as {
    items: Array<{ id: string; category: string }>;
  };
  const recordingId = listBody.items[0]!.id;
  expect(listBody.items[0]!.category).toBe('회의');

  await page.goto(`/recordings/${recordingId}`);
  await expect(page.getByText('현재 적용').locator('..')).toContainText(
    '회의 · 자동',
  );
  await expect(page.getByText('자동 분류 제안').locator('..')).toContainText(
    '회의',
  );
  await page
    .getByRole('combobox', { name: '적용할 범주' })
    .selectOption('강의');
  await page.getByRole('button', { name: '범주 저장' }).click();

  await expect
    .poll(async () => {
      const response = await request.get(`/api/recordings/${recordingId}`);
      const body = (await response.json()) as {
        recording: {
          revision: number;
          category: string;
          automatic_category: string;
          category_source: string;
        };
        jobs: Array<{ kind: string; status: string }>;
      };
      const render = body.jobs.find((job) => job.kind === 'render');
      return {
        revision: body.recording.revision,
        category: body.recording.category,
        automatic: body.recording.automatic_category,
        source: body.recording.category_source,
        render: render?.status,
      };
    })
    .toEqual({
      revision: 2,
      category: '강의',
      automatic: '회의',
      source: 'manual',
      render: 'succeeded',
    });

  await page.reload();
  await expect(page.getByText('현재 적용').locator('..')).toContainText(
    '강의 · 수동',
  );
  await expect(page.getByText('자동 분류 제안').locator('..')).toContainText(
    '회의',
  );

  const transcriptDirectories = await readdir(
    path.join(dataRoot!, 'transcripts'),
  );
  expect(transcriptDirectories).toHaveLength(1);
  const transcript = JSON.parse(
    await readFile(
      path.join(
        dataRoot!,
        'transcripts',
        transcriptDirectories[0]!,
        'revisions',
        '2',
        'transcript.json',
      ),
      'utf8',
    ),
  ) as {
    revision: number;
    classification_source: string;
    classification: { category: string };
    classification_fingerprint: { direct: { provider: string } };
  };
  const markdownFiles = await readdir(path.join(dataRoot!, 'document output'));
  expect(markdownFiles).toHaveLength(1);
  const markdown = await readFile(
    path.join(dataRoot!, 'document output', markdownFiles[0]!),
    'utf8',
  );

  expect(transcript).toMatchObject({
    revision: 2,
    classification_source: 'manual',
    classification: { category: '강의' },
    classification_fingerprint: {
      direct: { provider: 'openai_compatible' },
    },
  });
  expect(markdown).toContain('Revision: 2');
  expect(markdown).toContain('Category: 강의');
  expect(markdown).toContain('Category Source: manual');
});

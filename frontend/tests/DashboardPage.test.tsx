import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { vi } from 'vitest';

import { DashboardPage } from '../src/pages/DashboardPage';

const operations = {
  queued_jobs: 0,
  running_jobs: 0,
  review_recordings: 0,
  failed_recordings: 0,
  last_job_finished_at: null,
};

const counts = {
  DISCOVERED: 0,
  TRANSCRIBING: 0,
  SPEAKER_REVIEW: 0,
  CLASSIFYING: 0,
  READY_FOR_SUMMARY: 0,
  SUMMARIZING: 0,
  COMPLETED: 0,
  FAILED: 0,
};

function response(status: number, body: object) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

test('빈 녹음 목록을 오류와 구분해 표시한다', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(
      response(200, {
        items: [],
        total: 0,
        page_size: 50,
        operations,
        status_counts: counts,
      }),
    ),
  );

  render(
    <MemoryRouter>
      <DashboardPage />
    </MemoryRouter>,
  );

  expect(
    screen.getByText('녹음 목록을 불러오고 있습니다…'),
  ).toBeInTheDocument();
  expect(
    await screen.findByText('아직 감지된 녹음이 없습니다'),
  ).toBeInTheDocument();
});

test('완료 녹음과 상태를 표시한다', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(
      response(200, {
        items: [
          {
            id: 'recording-id',
            original_name: 'complete.m4a',
            duration_ms: 2000,
            status: 'COMPLETED',
            category: '회의',
            category_confidence: 0.99,
            category_reason: '회의',
            needs_speaker_review: false,
            revision: 1,
            created_at: 'now',
            updated_at: 'now',
          },
        ],
        total: 1,
        page_size: 50,
        operations,
        status_counts: { ...counts, COMPLETED: 1 },
      }),
    ),
  );

  render(
    <MemoryRouter>
      <DashboardPage />
    </MemoryRouter>,
  );

  expect(await screen.findByText('complete.m4a')).toBeInTheDocument();
  expect(screen.getByText('회의')).toBeInTheDocument();
  expect(screen.getAllByText('완료').length).toBeGreaterThan(0);
  expect(screen.getByRole('link', { name: /complete.m4a/ })).toHaveAttribute(
    'href',
    '/recordings/recording-id',
  );
});

test('API 실패 후 다시 불러온다', async () => {
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce(
      response(500, {
        error: { code: 'ERROR', message: '목록 서버 오류', details: {} },
      }),
    )
    .mockResolvedValueOnce(
      response(200, {
        items: [],
        total: 0,
        page_size: 50,
        operations,
        status_counts: counts,
      }),
    );
  vi.stubGlobal('fetch', fetchMock);
  const user = userEvent.setup();

  render(
    <MemoryRouter>
      <DashboardPage />
    </MemoryRouter>,
  );

  expect(await screen.findByRole('alert')).toHaveTextContent('목록 서버 오류');
  await user.click(screen.getByRole('button', { name: '다시 불러오기' }));
  expect(
    await screen.findByText('아직 감지된 녹음이 없습니다'),
  ).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(2);
});

test('목록 밖 활성 작업의 전체 집계를 표시하고 polling을 계속한다', async () => {
  vi.useFakeTimers();
  const finishedAt = '2026-09-09T06:00:00+00:00';
  const payload = {
    items: [],
    total: 51,
    page_size: 50,
    status_counts: counts,
    operations: {
      ...operations,
      queued_jobs: 2,
      running_jobs: 1,
      review_recordings: 3,
      failed_recordings: 4,
      last_job_finished_at: finishedAt,
    },
  };
  const fetchMock = vi
    .fn()
    .mockImplementation(() => Promise.resolve(response(200, payload)));
  vi.stubGlobal('fetch', fetchMock);
  try {
    await act(async () => {
      render(
        <MemoryRouter>
          <DashboardPage />
        </MemoryRouter>,
      );
    });
    expect(screen.getByText('2개 작업')).toBeInTheDocument();
    expect(screen.getByText('1개 작업')).toBeInTheDocument();
    expect(screen.getByText('3개 녹음')).toBeInTheDocument();
    expect(screen.getByText('4개 녹음')).toBeInTheDocument();
    expect(
      screen.getByText(new Date(finishedAt).toLocaleString()),
    ).toHaveAttribute('dateTime', finishedAt);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    payload.operations.queued_jobs = 0;
    payload.operations.running_jobs = 0;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(fetchMock).toHaveBeenCalledTimes(3);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6000);
    });
    expect(fetchMock).toHaveBeenCalledTimes(3);
  } finally {
    vi.useRealTimers();
  }
});

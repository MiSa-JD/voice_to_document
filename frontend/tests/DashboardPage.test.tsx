import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { vi } from 'vitest';

import { DashboardPage } from '../src/pages/DashboardPage';

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

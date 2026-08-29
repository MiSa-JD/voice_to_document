import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { vi } from 'vitest';

import { SpeakerReviewPage } from '../src/pages/SpeakerReviewPage';

function response(status: number, body: object) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const detail = {
  recording: {
    id: 'recording-id',
    original_name: 'review.m4a',
    duration_ms: 10_000,
    status: 'SPEAKER_REVIEW',
    category: null,
    category_confidence: null,
    category_reason: null,
    needs_speaker_review: true,
    revision: 3,
    created_at: 'now',
    updated_at: 'now',
  },
  speakers: [
    {
      local_speaker_id: 'SPEAKER_00',
      person_id: null,
      speaker_name: null,
      speaker_source: 'auto',
      speaker_score: 0.91,
      segment_count: 1,
      duration_ms: 2_000,
      clip_status: 'ready',
      clip_error_code: null,
      representative_clip_artifact_id: 'clip-id',
      representative_clip_start_ms: 0,
      representative_clip_end_ms: 2_000,
    },
    {
      local_speaker_id: 'SPEAKER_01',
      person_id: null,
      speaker_name: null,
      speaker_source: 'unresolved',
      speaker_score: null,
      segment_count: 1,
      duration_ms: 2_000,
      clip_status: 'insufficient',
      clip_error_code: null,
      representative_clip_artifact_id: null,
      representative_clip_start_ms: null,
      representative_clip_end_ms: null,
    },
  ],
  segments: [
    {
      id: 'one',
      start_ms: 1000,
      end_ms: 3000,
      local_speaker_id: 'SPEAKER_00',
      assignment_status: 'assigned',
      overlapping_speaker_ids: [],
      person_id: null,
      speaker_name: null,
      speaker_source: 'unresolved',
      speaker_score: null,
      text: '첫 발화',
      revision: 3,
    },
    {
      id: 'two',
      start_ms: 4000,
      end_ms: 6000,
      local_speaker_id: 'SPEAKER_01',
      assignment_status: 'assigned',
      overlapping_speaker_ids: [],
      person_id: null,
      speaker_name: null,
      speaker_source: 'unresolved',
      speaker_score: null,
      text: '둘째 발화',
      revision: 3,
    },
  ],
  artifacts: [
    {
      id: 'audio-id',
      kind: 'recording_audio',
      content_sha256: 'hash',
      schema_version: 1,
      revision: 1,
      created_at: 'now',
    },
  ],
  jobs: [],
  summary: null,
};

function renderPage() {
  render(
    <MemoryRouter initialEntries={['/recordings/recording-id/speakers']}>
      <Routes>
        <Route
          path="/recordings/:id/speakers"
          element={<SpeakerReviewPage />}
        />
      </Routes>
    </MemoryRouter>,
  );
}

test('화자 카드, 클립 상태, 선택 발화와 timestamp seek를 표시한다', async () => {
  const play = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(HTMLMediaElement.prototype, 'play', {
    configurable: true,
    value: play,
  });
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockImplementation((path: string) =>
        Promise.resolve(
          path === '/api/persons'
            ? response(200, { items: [], total: 0 })
            : response(200, detail),
        ),
      ),
  );
  renderPage();

  expect(
    await screen.findByText('review.m4a의 음성을 듣고 인물을 연결합니다.'),
  ).toBeInTheDocument();
  expect(screen.getAllByText('자동 후보 없음')).toHaveLength(2);
  expect(
    screen.getByText('대표 클립으로 적합한 발화가 부족합니다.'),
  ).toBeInTheDocument();
  await userEvent.click(
    screen.getByRole('button', { name: /SPEAKER_01 1개 발화/ }),
  );
  expect(screen.getByText('둘째 발화').closest('li')).toHaveClass(
    'transcript__row--selected',
  );

  const original = document.querySelector(
    'audio[src="/api/media/audio-id"]',
  ) as HTMLAudioElement;
  await userEvent.click(screen.getByRole('button', { name: '00:04' }));
  expect(original.currentTime).toBe(4);
  expect(play).toHaveBeenCalled();
});

test('기존 인물 연결을 revision과 함께 즉시 저장하고 다시 읽는다', async () => {
  const fetchMock = vi
    .fn()
    .mockImplementation((path: string, init?: RequestInit) => {
      if (path === '/api/persons')
        return Promise.resolve(
          response(200, {
            items: [
              {
                id: 'person-id',
                display_name: '김민지',
                revision: 1,
                created_at: 'now',
                updated_at: 'now',
              },
            ],
            total: 1,
          }),
        );
      if (init?.method === 'PUT')
        return Promise.resolve(
          response(200, {
            recording_id: 'recording-id',
            recording_revision: 4,
            person_id: 'person-id',
            speaker_name: '김민지',
            updated_segment_count: 1,
          }),
        );
      return Promise.resolve(response(200, detail));
    });
  vi.stubGlobal('fetch', fetchMock);
  renderPage();

  const select = await screen.findByRole('combobox', {
    name: 'SPEAKER_00 인물 연결',
  });
  fireEvent.change(select, { target: { value: 'person-id' } });
  await waitFor(() =>
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/recordings/recording-id/speakers/SPEAKER_00',
      expect.objectContaining({
        method: 'PUT',
        body: JSON.stringify({ person_id: 'person-id', expected_revision: 3 }),
      }),
    ),
  );
  await waitFor(() =>
    expect(
      fetchMock.mock.calls.filter(
        ([path]) => path === '/api/recordings/recording-id',
      ),
    ).toHaveLength(2),
  );
});

test('로딩 실패와 빈 화자 상태를 구분한다', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(response(500, { error: { message: '실패' } })),
  );
  renderPage();
  expect(await screen.findByRole('alert')).toHaveTextContent('실패');

  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockImplementation((path: string) =>
        Promise.resolve(
          path === '/api/persons'
            ? response(200, { items: [], total: 0 })
            : response(200, { ...detail, speakers: [] }),
        ),
      ),
  );
  renderPage();
  expect(
    await screen.findByText('검토할 화자가 없습니다.'),
  ).toBeInTheDocument();
});

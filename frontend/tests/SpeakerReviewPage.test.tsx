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
      person_id: 'candidate-1',
      speaker_name: '김민지',
      speaker_source: 'auto',
      speaker_score: 0.91,
      segment_count: 1,
      duration_ms: 2_000,
      clip_status: 'ready',
      clip_error_code: null,
      representative_clip_artifact_id: 'clip-id',
      representative_clip_start_ms: 0,
      representative_clip_end_ms: 2_000,
      match: {
        decision: 'auto_matched',
        best_score: 0.91,
        second_best_score: 0.72,
        margin: 0.19,
        input_revision: 2,
        candidates: [
          {
            person_id: 'candidate-1',
            display_name: '김민지',
            rank: 1,
            score: 0.91,
            rejected: false,
          },
          {
            person_id: 'candidate-2',
            display_name: '이서준',
            rank: 2,
            score: 0.72,
            rejected: true,
          },
        ],
      },
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
      match: {
        decision: 'insufficient_clips',
        best_score: 0,
        second_best_score: 0,
        margin: 0,
        input_revision: 2,
        candidates: [],
      },
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
  expect(
    screen.getByText(
      '화자 후보는 유사도 기반 편의 기능이며 신원 인증이 아닙니다.',
    ),
  ).toBeInTheDocument();
  expect(screen.getByText(/연결 상태: 자동 확정/)).toHaveTextContent(
    '유사도 91%',
  );
  expect(screen.getByText('연결 상태: 미확정')).toBeInTheDocument();
  expect(screen.getByText('김민지 · 유사도 91%')).toBeInTheDocument();
  expect(screen.getByText('72%')).toBeInTheDocument();
  expect(screen.getByText('19%')).toBeInTheDocument();
  expect(screen.getByText(/2위 이서준/)).toHaveTextContent(
    '과거 자동 연결 거부',
  );
  expect(
    screen.getByText('대표 클립이 2개보다 적어 비교하지 않았습니다.'),
  ).toBeInTheDocument();
  expect(
    screen.getByText('대표 클립으로 적합한 발화가 부족합니다.'),
  ).toBeInTheDocument();
  await userEvent.click(
    screen.getByRole('button', { name: /SPEAKER_01, 1개 발화/ }),
  );
  expect(screen.getByText('둘째 발화').closest('li')).toHaveClass(
    'transcript__row--selected',
  );

  const original = document.querySelector(
    'audio[src="/api/media/audio-id"]',
  ) as HTMLAudioElement;
  await userEvent.click(
    screen.getByRole('button', { name: '00:04부터 오디오 재생' }),
  );
  expect(original.currentTime).toBe(4);
  expect(play).toHaveBeenCalled();
});

test('후보 버튼으로 기존 인물을 수동 확정하고 자동 연결을 알 수 없음으로 취소한다', async () => {
  const fetchMock = vi
    .fn()
    .mockImplementation((path: string, init?: RequestInit) => {
      if (path === '/api/persons')
        return Promise.resolve(
          response(200, {
            items: [
              {
                id: 'candidate-1',
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
            person_id: null,
            speaker_name: null,
            updated_segment_count: 1,
          }),
        );
      return Promise.resolve(response(200, detail));
    });
  vi.stubGlobal('fetch', fetchMock);
  renderPage();

  await userEvent.click(
    await screen.findByRole('button', { name: '김민지 수동 확정' }),
  );
  await waitFor(() =>
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/recordings/recording-id/speakers/SPEAKER_00',
      expect.objectContaining({
        body: JSON.stringify({
          person_id: 'candidate-1',
          expected_revision: 3,
        }),
      }),
    ),
  );

  fireEvent.change(
    screen.getByRole('combobox', { name: 'SPEAKER_00 인물 연결' }),
    { target: { value: '__unknown__' } },
  );
  await waitFor(() =>
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/recordings/recording-id/speakers/SPEAKER_00',
      expect.objectContaining({
        body: JSON.stringify({ person_id: null, expected_revision: 3 }),
      }),
    ),
  );
});

test('모든 자동 판정 이유를 색상 없이 한국어 텍스트로 설명한다', async () => {
  const decisions = [
    ['no_profiles', '같은 모델로 비교할 수 있는 인물 profile이 없습니다.'],
    ['insufficient_profiles', '인물 profile의 수동 확인 표본이 부족합니다.'],
    ['auto_disabled', '후보는 계산했지만 자동 확정 기능이 꺼져 있습니다.'],
    [
      'below_threshold',
      '1순위 후보의 절대 유사도가 자동 확정 기준보다 낮습니다.',
    ],
    ['insufficient_margin', '1·2위 유사도 차이가 작아 수동 검토가 필요합니다.'],
    [
      'duplicate_person',
      '같은 녹음의 다른 화자와 인물이 중복되어 확정하지 않았습니다.',
    ],
    [
      'rejected_candidate',
      '이 화자와 후보의 과거 자동 연결을 사용자가 거부했습니다.',
    ],
  ] as const;
  const speakers = decisions.map(([decision], index) => ({
    ...detail.speakers[1],
    local_speaker_id: `SPEAKER_${index + 10}`,
    match: { ...detail.speakers[1].match, decision },
  }));
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockImplementation((path: string) =>
        Promise.resolve(
          path === '/api/persons'
            ? response(200, { items: [], total: 0 })
            : response(200, { ...detail, speakers }),
        ),
      ),
  );
  renderPage();

  await screen.findByText(decisions[0][1]);
  for (const [, explanation] of decisions) {
    expect(screen.getByText(explanation)).toBeInTheDocument();
  }
});

test('후보 결과가 없는 pending 상태를 계산 완료 판정과 구분한다', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((path: string) =>
      Promise.resolve(
        path === '/api/persons'
          ? response(200, { items: [], total: 0 })
          : response(200, {
              ...detail,
              speakers: [
                {
                  ...detail.speakers[1],
                  clip_status: 'pending',
                  match: undefined,
                },
                {
                  ...detail.speakers[1],
                  local_speaker_id: 'SPEAKER_99',
                  person_id: 'manual-person',
                  speaker_name: '수동 검토자',
                  speaker_source: 'manual',
                },
              ],
            }),
      ),
    ),
  );
  renderPage();

  expect(
    await screen.findByText('대표 클립 생성과 후보 계산을 기다리고 있습니다.'),
  ).toHaveAttribute('role', 'status');
  expect(screen.getByText('연결 상태: 수동 확정')).toBeInTheDocument();
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

test('새 인물 인라인 폼은 오류를 설명하고 취소 시 선택으로 초점을 돌린다', async () => {
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

  const select = await screen.findByRole('combobox', {
    name: 'SPEAKER_00 인물 연결',
  });
  await userEvent.selectOptions(select, '__new__');
  const input = screen.getByRole('textbox', { name: '새 인물 이름' });
  expect(input).toHaveFocus();
  expect(input).toHaveAccessibleDescription(
    'transcript에 표시할 이름을 입력하세요.',
  );
  await userEvent.click(screen.getByRole('button', { name: '인물 만들기' }));
  expect(await screen.findByRole('alert')).toHaveTextContent(
    '인물 이름을 입력하세요.',
  );
  expect(input).toHaveAttribute('aria-invalid', 'true');
  await userEvent.click(screen.getByRole('button', { name: '취소' }));
  await waitFor(() => expect(select).toHaveFocus());
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

test('선택 발화를 확인한 뒤 한 번의 batch 요청으로 저장한다', async () => {
  const fetchMock = vi
    .fn()
    .mockImplementation((path: string, init?: RequestInit) => {
      if (path === '/api/persons') {
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
      }
      if (path === '/api/segments/speakers' && init?.method === 'PATCH') {
        return Promise.resolve(
          response(200, {
            recording_id: 'recording-id',
            recording_revision: 4,
            person_id: 'person-id',
            speaker_name: '김민지',
            updated_segment_count: 2,
          }),
        );
      }
      return Promise.resolve(response(200, detail));
    });
  vi.stubGlobal('fetch', fetchMock);
  renderPage();

  await userEvent.click(
    await screen.findByRole('checkbox', { name: '00:01 발화 선택' }),
  );
  await userEvent.click(
    screen.getByRole('checkbox', { name: '00:04 발화 선택' }),
  );
  await userEvent.selectOptions(
    screen.getByRole('combobox', { name: '선택 발화 변경 인물' }),
    'person-id',
  );
  expect(
    fetchMock.mock.calls.some(([path]) => path === '/api/segments/speakers'),
  ).toBe(false);
  await userEvent.click(screen.getByRole('button', { name: '변경 확인' }));

  const confirmation = screen.getByRole('region', { name: '발화 변경 확인' });
  expect(confirmation).toHaveTextContent('2개 발화');
  expect(confirmation).toHaveTextContent('SPEAKER_00 → 김민지');
  await userEvent.click(screen.getByRole('button', { name: '일괄 저장' }));

  await waitFor(() =>
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/segments/speakers',
      expect.objectContaining({
        method: 'PATCH',
        body: JSON.stringify({
          recording_id: 'recording-id',
          segment_ids: ['one', 'two'],
          person_id: 'person-id',
          expected_revision: 3,
        }),
      }),
    ),
  );
  expect(
    fetchMock.mock.calls.filter(([path]) => path === '/api/segments/speakers'),
  ).toHaveLength(1);
});

test('draft 이탈을 경고하고 명시적 폐기 전에는 서버를 변경하지 않는다', async () => {
  const fetchMock = vi
    .fn()
    .mockImplementation((path: string) =>
      Promise.resolve(
        path === '/api/persons'
          ? response(200, { items: [], total: 0 })
          : response(200, detail),
      ),
    );
  const confirm = vi.fn().mockReturnValue(false);
  vi.stubGlobal('fetch', fetchMock);
  vi.stubGlobal('confirm', confirm);
  renderPage();

  await userEvent.click(
    await screen.findByRole('checkbox', { name: '00:01 발화 선택' }),
  );
  const unload = new Event('beforeunload', { cancelable: true });
  window.dispatchEvent(unload);
  expect(unload.defaultPrevented).toBe(true);
  await userEvent.click(screen.getByRole('link', { name: '← 녹음 상세' }));
  expect(confirm).toHaveBeenCalled();
  expect(
    fetchMock.mock.calls.some(
      ([, init]) => (init as RequestInit | undefined)?.method === 'PATCH',
    ),
  ).toBe(false);

  await userEvent.click(screen.getByRole('button', { name: '변경 폐기' }));
  expect(screen.getByText('0개 발화 선택')).toBeInTheDocument();
});

test('전체 화자 연결의 revision 충돌을 일반 오류와 구분한다', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((path: string, init?: RequestInit) => {
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
          response(409, {
            error: {
              code: 'REVISION_CONFLICT',
              message: '다른 변경이 먼저 저장되었습니다.',
              details: { current_revision: 7 },
            },
          }),
        );
      return Promise.resolve(response(200, detail));
    }),
  );
  renderPage();

  fireEvent.change(
    await screen.findByRole('combobox', { name: 'SPEAKER_00 인물 연결' }),
    { target: { value: 'person-id' } },
  );
  const alert = await screen.findByRole('alert');
  expect(alert).toHaveTextContent('저장을 중단했습니다');
  expect(alert).toHaveTextContent('최신 revision은 7');
});

test('batch 충돌에서 draft를 유지하고 확인한 경우에만 최신 내용을 읽는다', async () => {
  const fetchMock = vi
    .fn()
    .mockImplementation((path: string, init?: RequestInit) => {
      if (path === '/api/persons')
        return Promise.resolve(response(200, { items: [], total: 0 }));
      if (path === '/api/segments/speakers' && init?.method === 'PATCH')
        return Promise.resolve(
          response(409, {
            error: {
              code: 'REVISION_CONFLICT',
              message: '다른 변경이 먼저 저장되었습니다.',
              details: { current_revision: 5 },
            },
          }),
        );
      return Promise.resolve(response(200, detail));
    });
  const confirm = vi.fn().mockReturnValueOnce(false).mockReturnValueOnce(true);
  vi.stubGlobal('fetch', fetchMock);
  vi.stubGlobal('confirm', confirm);
  renderPage();

  await userEvent.click(
    await screen.findByRole('checkbox', { name: '00:01 발화 선택' }),
  );
  await userEvent.selectOptions(
    screen.getByRole('combobox', { name: '선택 발화 변경 인물' }),
    '__unknown__',
  );
  await userEvent.click(screen.getByRole('button', { name: '변경 확인' }));
  await userEvent.click(screen.getByRole('button', { name: '일괄 저장' }));

  expect(await screen.findByRole('alert')).toHaveTextContent(
    '로컬 변경은 유지됩니다',
  );
  expect(
    screen.getByRole('checkbox', { name: '00:01 발화 선택' }),
  ).toBeChecked();
  const reload = screen.getByRole('button', {
    name: '로컬 변경 폐기 후 최신 내용 불러오기',
  });
  await userEvent.click(reload);
  expect(screen.getByText('1개 발화 선택')).toBeInTheDocument();
  expect(
    fetchMock.mock.calls.filter(
      ([path]) => path === '/api/recordings/recording-id',
    ),
  ).toHaveLength(1);

  await userEvent.click(reload);
  await waitFor(() =>
    expect(
      fetchMock.mock.calls.filter(
        ([path]) => path === '/api/recordings/recording-id',
      ),
    ).toHaveLength(2),
  );
});

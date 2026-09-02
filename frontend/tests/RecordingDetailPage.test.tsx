import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { vi } from 'vitest';

import { RecordingDetailPage } from '../src/pages/RecordingDetailPage';

function response(status: number, body: object) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function renderDetail() {
  render(
    <MemoryRouter initialEntries={['/recordings/recording-id']}>
      <Routes>
        <Route path="/recordings/:id" element={<RecordingDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

test('transcript, category, summary, job 이력을 표시한다', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((path: string) =>
      Promise.resolve(
        path.endsWith('/retranscriptions/latest')
          ? response(404, {
              error: { code: 'RETRANSCRIPTION_NOT_FOUND', message: '없음' },
            })
          : response(200, {
              recording: {
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
              segments: [
                {
                  id: 'segment-id',
                  start_ms: 0,
                  end_ms: 900,
                  local_speaker_id: 'SPEAKER_00',
                  assignment_status: 'assigned',
                  overlapping_speaker_ids: [],
                  person_id: null,
                  speaker_name: null,
                  text: '오늘 회의의 목표를 확인하겠습니다.',
                  revision: 1,
                },
                {
                  id: 'overlap-segment-id',
                  start_ms: 1000,
                  end_ms: 1500,
                  local_speaker_id: 'SPEAKER_00',
                  assignment_status: 'overlap',
                  overlapping_speaker_ids: ['SPEAKER_00', 'SPEAKER_01'],
                  person_id: null,
                  speaker_name: null,
                  text: '겹쳐 말한 구간입니다.',
                  revision: 1,
                },
                {
                  id: 'unassigned-segment-id',
                  start_ms: 1600,
                  end_ms: 1900,
                  local_speaker_id: null,
                  assignment_status: 'unassigned',
                  overlapping_speaker_ids: [],
                  person_id: null,
                  speaker_name: null,
                  text: '화자 미배정 구간입니다.',
                  revision: 1,
                },
              ],
              artifacts: [],
              jobs: [
                {
                  id: 'job-id',
                  kind: 'transcribe',
                  status: 'succeeded',
                  attempts: 1,
                  input_revision: 1,
                  settings_fingerprint: 'fake',
                  error_code: null,
                  error_message: null,
                  created_at: 'now',
                  updated_at: 'now',
                },
              ],
              summary: {
                purpose: '초안 준비 계획 확인',
                discussion: ['회의 목표를 확인함'],
                decisions: ['초안을 준비함'],
                action_items: [
                  { assignee: null, due_date: null, task: '초안 준비' },
                ],
                open_questions: [],
              },
            }),
      ),
    ),
  );

  renderDetail();

  expect(
    await screen.findByRole('heading', { name: 'complete.m4a' }),
  ).toBeInTheDocument();
  expect(
    screen.getByText('오늘 회의의 목표를 확인하겠습니다.'),
  ).toBeInTheDocument();
  expect(screen.getByText('미확정(SPEAKER_00)')).toBeInTheDocument();
  expect(
    screen.getByText('미확정(SPEAKER_00) · 겹침(SPEAKER_00, SPEAKER_01)'),
  ).toBeInTheDocument();
  expect(screen.getByText('화자 미배정')).toBeInTheDocument();
  expect(screen.getByText('초안 준비 계획 확인')).toBeInTheDocument();
  expect(screen.getByText('transcribe')).toBeInTheDocument();
});

test('404를 일반 빈 상세로 오해하지 않는다', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(
      response(404, {
        error: {
          code: 'RECORDING_NOT_FOUND',
          message: '녹음을 찾을 수 없습니다.',
          details: {},
        },
      }),
    ),
  );

  renderDetail();

  expect(await screen.findByRole('alert')).toHaveTextContent(
    '녹음을 찾을 수 없습니다.',
  );
  expect(screen.queryByText('생성된 요약이 없습니다.')).not.toBeInTheDocument();
});

test('실패 코드와 사용자 조치, 자동 재시도 상태를 표시한다', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((path: string) =>
      Promise.resolve(
        path.endsWith('/retranscriptions/latest')
          ? response(404, {
              error: { code: 'RETRANSCRIPTION_NOT_FOUND', message: '없음' },
            })
          : response(200, {
              recording: {
                id: 'recording-id',
                original_name: 'failed.m4a',
                duration_ms: 2000,
                status: 'FAILED',
                category: null,
                category_confidence: null,
                category_reason: null,
                needs_speaker_review: false,
                revision: 1,
                created_at: 'now',
                updated_at: 'now',
              },
              segments: [],
              artifacts: [],
              jobs: [
                {
                  id: 'job-id',
                  kind: 'transcribe',
                  status: 'queued',
                  attempts: 1,
                  input_revision: 1,
                  settings_fingerprint: 'real',
                  error_code: 'MODEL_DOWNLOAD_FAILED',
                  error_message:
                    '모델을 내려받지 못했습니다. 네트워크와 모델 캐시 권한을 확인하세요.',
                  created_at: 'now',
                  updated_at: 'now',
                },
              ],
              summary: null,
            }),
      ),
    ),
  );

  renderDetail();

  expect(
    await screen.findByRole('heading', { name: 'failed.m4a' }),
  ).toBeInTheDocument();
  expect(screen.getByText('자동 재시도 대기')).toBeInTheDocument();
  expect(screen.getByText('MODEL_DOWNLOAD_FAILED')).toBeInTheDocument();
  expect(screen.getByRole('status')).toHaveTextContent('네트워크');
});

test('확인 전에는 변경하지 않고 제출 후 재전사 비교와 재검토 링크를 표시한다', async () => {
  let latestCalls = 0;
  const detail = {
    recording: {
      id: 'recording-id',
      original_name: 'complete.m4a',
      duration_ms: 2000,
      status: 'COMPLETED',
      category: '회의',
      category_confidence: 0.9,
      category_reason: '회의',
      needs_speaker_review: false,
      revision: 1,
      created_at: 'now',
      updated_at: 'now',
    },
    speakers: [],
    segments: [],
    artifacts: [],
    jobs: [],
    summary: null,
  };
  const latest = {
    request_id: 'request-id',
    recording_id: 'recording-id',
    status: 'succeeded',
    base_revision: 1,
    target_revision: 2,
    previous_language: 'ko',
    requested_language: 'en',
    new_language: 'en',
    previous_segment_count: 2,
    new_segment_count: 3,
    unresolved_speaker_count: 2,
    hint_applied: true,
    history_available: true,
    history_location: 'app_data/history',
    error_code: null,
    created_at: 'now',
    updated_at: 'now',
  };
  const fetchMock = vi
    .fn()
    .mockImplementation((path: string, init?: RequestInit) => {
      if (init?.method === 'POST')
        return Promise.resolve(
          response(202, {
            request_id: 'request-id',
            recording_id: 'recording-id',
            base_revision: 1,
            target_revision: 2,
            language: 'en',
            hint_applied: true,
            warning: '정확도 비보장',
            job: {
              id: 'job-id',
              kind: 'transcribe',
              status: 'queued',
              input_revision: 1,
            },
          }),
        );
      if (path.endsWith('/retranscriptions/latest')) {
        latestCalls += 1;
        return Promise.resolve(
          latestCalls === 1
            ? response(404, {
                error: { code: 'RETRANSCRIPTION_NOT_FOUND', message: '없음' },
              })
            : response(200, latest),
        );
      }
      return Promise.resolve(response(200, detail));
    });
  vi.stubGlobal('fetch', fetchMock);
  renderDetail();

  await userEvent.click(
    await screen.findByRole('button', { name: '재전사 설정 열기' }),
  );
  await userEvent.selectOptions(screen.getByLabelText('녹음 언어'), 'en');
  await userEvent.type(
    screen.getByLabelText('대략적인 내용 설명 (선택)'),
    '제품 회의',
  );
  await userEvent.type(
    screen.getByLabelText('고유명사·전문용어 (선택)'),
    'Codex, WhisperX',
  );
  await userEvent.click(screen.getByRole('button', { name: '영향 확인' }));
  expect(
    screen.getByRole('region', { name: '재전사 영향 확인' }),
  ).toHaveTextContent('실패하면 현재 성공 결과는 그대로 유지됩니다.');
  expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(
    false,
  );

  await userEvent.click(
    screen.getByRole('button', { name: '영향을 확인했고 STT 다시 수행' }),
  );
  await waitFor(() =>
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/recordings/recording-id/retranscriptions',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          expected_revision: 1,
          language: 'en',
          content_description: '제품 회의',
          terms: ['Codex', 'WhisperX'],
          confirm_impact: true,
        }),
      }),
    ),
  );
  expect(await screen.findByText('재전사 완료')).toBeInTheDocument();
  expect(screen.getByText('ko → en')).toBeInTheDocument();
  expect(screen.getByText('2 → 3')).toBeInTheDocument();
  expect(screen.getByRole('link', { name: '화자 다시 검토' })).toHaveAttribute(
    'href',
    '/recordings/recording-id/speakers',
  );
});

test('자동 분류 근거를 표시하고 허용 범주를 수동 저장한다', async () => {
  let revision = 1;
  const fetchMock = vi
    .fn()
    .mockImplementation((path: string, init?: RequestInit) => {
      if (path.endsWith('/retranscriptions/latest')) {
        return Promise.resolve(
          response(404, {
            error: { code: 'RETRANSCRIPTION_NOT_FOUND', message: '없음' },
          }),
        );
      }
      if (init?.method === 'PATCH') {
        revision = 2;
        return Promise.resolve(
          response(200, {
            recording_id: 'recording-id',
            category: '강의',
            category_source: 'manual',
            revision: 2,
            render_job: {
              id: 'render-id',
              kind: 'render',
              status: 'queued',
              input_revision: 2,
            },
          }),
        );
      }
      return Promise.resolve(
        response(200, {
          recording: {
            id: 'recording-id',
            original_name: 'complete.m4a',
            duration_ms: 2000,
            status: 'COMPLETED',
            category: revision === 1 ? '회의' : '강의',
            automatic_category: '회의',
            category_source: revision === 1 ? 'auto' : 'manual',
            category_confidence: 0.91,
            category_reason: '결정과 할 일이 포함된 대화',
            needs_speaker_review: false,
            revision,
            created_at: 'now',
            updated_at: 'now',
          },
          allowed_categories: ['강의', '회의', '기타'],
          speakers: [],
          segments: [],
          artifacts: [],
          jobs: [],
          summary: null,
        }),
      );
    });
  vi.stubGlobal('fetch', fetchMock);
  renderDetail();

  expect(await screen.findByText('자동 분류 제안')).toBeInTheDocument();
  expect(screen.getByText('91%')).toBeInTheDocument();
  expect(screen.getByText('결정과 할 일이 포함된 대화')).toBeInTheDocument();
  const select = screen.getByRole('combobox', { name: '적용할 범주' });
  const save = screen.getByRole('button', { name: '범주 저장' });
  expect(save).toBeDisabled();
  expect(
    screen.getAllByRole('option').map((option) => option.textContent),
  ).toEqual(['강의', '회의', '기타']);

  await userEvent.selectOptions(select, '강의');
  await userEvent.click(save);

  await waitFor(() =>
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/recordings/recording-id/category',
      expect.objectContaining({
        method: 'PATCH',
        body: JSON.stringify({ category: '강의', expected_revision: 1 }),
      }),
    ),
  );
  expect(await screen.findByText('강의 · 수동')).toBeInTheDocument();
});

test('범주 revision 충돌 시 덮어쓰지 않고 최신 내용을 다시 불러온다', async () => {
  let detailCalls = 0;
  const fetchMock = vi
    .fn()
    .mockImplementation((path: string, init?: RequestInit) => {
      if (path.endsWith('/retranscriptions/latest')) {
        return Promise.resolve(
          response(404, {
            error: { code: 'RETRANSCRIPTION_NOT_FOUND', message: '없음' },
          }),
        );
      }
      if (init?.method === 'PATCH') {
        return Promise.resolve(
          response(409, {
            error: {
              code: 'REVISION_CONFLICT',
              message: '최신 내용을 확인하세요.',
              details: { current_revision: 2 },
            },
          }),
        );
      }
      detailCalls += 1;
      return Promise.resolve(
        response(200, {
          recording: {
            id: 'recording-id',
            original_name: 'complete.m4a',
            duration_ms: 2000,
            status: 'COMPLETED',
            category: detailCalls === 1 ? '회의' : '기타',
            automatic_category: '회의',
            category_source: detailCalls === 1 ? 'auto' : 'manual',
            category_confidence: 0.8,
            category_reason: '회의 근거',
            needs_speaker_review: false,
            revision: detailCalls,
            created_at: 'now',
            updated_at: 'now',
          },
          allowed_categories: ['강의', '회의', '기타'],
          speakers: [],
          segments: [],
          artifacts: [],
          jobs: [],
          summary: null,
        }),
      );
    });
  vi.stubGlobal('fetch', fetchMock);
  renderDetail();

  await userEvent.selectOptions(
    await screen.findByRole('combobox', { name: '적용할 범주' }),
    '강의',
  );
  await userEvent.click(screen.getByRole('button', { name: '범주 저장' }));

  expect(
    await screen.findByText(
      '다른 변경이 먼저 반영되어 최신 내용을 다시 불러옵니다.',
      {
        exact: false,
      },
    ),
  ).toBeInTheDocument();
  await waitFor(() => expect(detailCalls).toBe(2));
  expect(await screen.findByText('기타 · 수동')).toBeInTheDocument();
});

test.each([
  {
    name: '422 응답',
    patchResult: () =>
      Promise.resolve(
        response(422, {
          error: {
            code: 'INVALID_CATEGORY',
            message: '허용되지 않은 범주입니다.',
            details: {},
          },
        }),
      ),
    expected: '허용되지 않은 범주입니다. 다른 범주를 선택해 주세요.',
  },
  {
    name: '네트워크 오류',
    patchResult: () => Promise.reject(new TypeError('offline')),
    expected: '서버에 연결할 수 없습니다.',
  },
])(
  '범주 저장 $name에 다음 행동을 안내한다',
  async ({ patchResult, expected }) => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((path: string, init?: RequestInit) => {
        if (path.endsWith('/retranscriptions/latest')) {
          return Promise.resolve(
            response(404, {
              error: { code: 'RETRANSCRIPTION_NOT_FOUND', message: '없음' },
            }),
          );
        }
        if (init?.method === 'PATCH') return patchResult();
        return Promise.resolve(
          response(200, {
            recording: {
              id: 'recording-id',
              original_name: 'complete.m4a',
              duration_ms: 2000,
              status: 'COMPLETED',
              category: '회의',
              automatic_category: '회의',
              category_source: 'auto',
              category_confidence: 0.8,
              category_reason: '회의 근거',
              needs_speaker_review: false,
              revision: 1,
              created_at: 'now',
              updated_at: 'now',
            },
            allowed_categories: ['강의', '회의'],
            speakers: [],
            segments: [],
            artifacts: [],
            jobs: [],
            summary: null,
          }),
        );
      }),
    );
    renderDetail();
    await userEvent.selectOptions(
      await screen.findByRole('combobox', { name: '적용할 범주' }),
      '강의',
    );
    await userEvent.click(screen.getByRole('button', { name: '범주 저장' }));
    expect(await screen.findByText(expected)).toBeInTheDocument();
  },
);

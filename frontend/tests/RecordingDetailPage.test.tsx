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

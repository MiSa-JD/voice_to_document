import { render, screen } from '@testing-library/react';
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
    vi.fn().mockResolvedValue(
      response(200, {
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
          action_items: [{ assignee: null, due_date: null, task: '초안 준비' }],
          open_questions: [],
        },
      }),
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

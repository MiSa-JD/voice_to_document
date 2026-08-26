import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { ApiError } from '../api/client';
import {
  ACTIVE_STATUSES,
  getRecording,
  statusLabel,
  type RecordingDetailResponse,
} from '../api/recordings';

type ViewState =
  | { kind: 'loading' }
  | { kind: 'success'; data: RecordingDetailResponse }
  | { kind: 'error'; message: string; notFound: boolean };

export function RecordingDetailPage() {
  const { id = '' } = useParams();
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<ViewState>({ kind: 'loading' });

  useEffect(() => {
    const controller = new AbortController();
    let timer: number | undefined;
    const load = async () => {
      try {
        const data = await getRecording(id, controller.signal);
        if (controller.signal.aborted) return;
        setState({ kind: 'success', data });
        if (ACTIVE_STATUSES.has(data.recording.status)) {
          timer = window.setTimeout(load, 3000);
        }
      } catch (error) {
        if (!controller.signal.aborted) {
          setState({
            kind: 'error',
            message:
              error instanceof ApiError
                ? error.message
                : '녹음 상세를 불러오지 못했습니다.',
            notFound: error instanceof ApiError && error.status === 404,
          });
        }
      }
    };
    void load();
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [attempt, id]);

  return (
    <main className="shell shell--wide">
      <Link className="back-link" to="/">
        ← 대시보드
      </Link>

      {state.kind === 'loading' && (
        <section className="panel" aria-live="polite">
          <p className="status status--loading">
            녹음 상세를 불러오고 있습니다…
          </p>
        </section>
      )}

      {state.kind === 'error' && (
        <section className="panel panel--error" role="alert">
          <h1>
            {state.notFound ? '녹음을 찾을 수 없습니다' : '상세 갱신 실패'}
          </h1>
          <p>{state.message}</p>
          {!state.notFound && (
            <button
              type="button"
              onClick={() => setAttempt((value) => value + 1)}
            >
              다시 불러오기
            </button>
          )}
        </section>
      )}

      {state.kind === 'success' && <RecordingDetail data={state.data} />}
    </main>
  );
}

function RecordingDetail({ data }: { data: RecordingDetailResponse }) {
  const { recording } = data;
  return (
    <>
      <p className="eyebrow">RECORDING DETAIL</p>
      <h1>{recording.original_name}</h1>
      <div className="detail-meta">
        <span className={`badge badge--${recording.status.toLowerCase()}`}>
          {statusLabel(recording.status)}
        </span>
        <span>범주: {recording.category ?? '분류 대기'}</span>
        <span>길이: {formatDuration(recording.duration_ms)}</span>
      </div>

      <section className="panel detail-section">
        <h2>전체 내용</h2>
        {data.segments.length === 0 ? (
          <p className="muted">아직 transcript가 없습니다.</p>
        ) : (
          <ol className="transcript">
            {data.segments.map((segment) => (
              <li key={segment.id}>
                <time>{formatDuration(segment.start_ms)}</time>
                <div>
                  <strong>{speakerLabel(segment)}</strong>
                  <p>{segment.text}</p>
                </div>
              </li>
            ))}
          </ol>
        )}
      </section>

      <section className="panel detail-section">
        <h2>요약</h2>
        {data.summary ? (
          <div className="summary-grid">
            <div>
              <h3>목적</h3>
              <p>{data.summary.purpose}</p>
            </div>
            <SummaryList title="논의 내용" items={data.summary.discussion} />
            <SummaryList title="결정 사항" items={data.summary.decisions} />
            <SummaryList
              title="할 일"
              items={data.summary.action_items.map((item) => item.task)}
            />
            <SummaryList
              title="미해결 사항"
              items={data.summary.open_questions}
              empty="없음"
            />
          </div>
        ) : (
          <p className="muted">생성된 요약이 없습니다.</p>
        )}
      </section>

      <section className="panel detail-section">
        <h2>처리 이력</h2>
        <ul className="job-list">
          {data.jobs.map((job) => (
            <li key={job.id}>
              <strong>{job.kind}</strong>
              <span>{job.status}</span>
              <small>{job.attempts}회 시도</small>
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}

function speakerLabel(segment: RecordingDetailResponse['segments'][number]) {
  if (segment.speaker_name) return segment.speaker_name;
  if (segment.assignment_status === 'unassigned') return '화자 미배정';
  const primary = `미확정(${segment.local_speaker_id})`;
  if (segment.assignment_status !== 'overlap') return primary;
  return `${primary} · 겹침(${segment.overlapping_speaker_ids.join(', ')})`;
}

function SummaryList({
  title,
  items,
  empty,
}: {
  title: string;
  items: string[];
  empty?: string;
}) {
  return (
    <div>
      <h3>{title}</h3>
      {items.length ? (
        <ul>
          {items.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : (
        <p>{empty}</p>
      )}
    </div>
  );
}

function formatDuration(milliseconds: number) {
  const seconds = Math.floor(milliseconds / 1000);
  return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
}

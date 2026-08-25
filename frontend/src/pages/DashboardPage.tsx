import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { ApiError } from '../api/client';
import {
  ACTIVE_STATUSES,
  getRecordings,
  type RecordingListResponse,
  type RecordingStatus,
  statusLabel,
} from '../api/recordings';

type ViewState =
  | { kind: 'loading' }
  | { kind: 'success'; data: RecordingListResponse }
  | { kind: 'error'; message: string };

export function DashboardPage() {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<ViewState>({ kind: 'loading' });

  useEffect(() => {
    const controller = new AbortController();
    let timer: number | undefined;
    const load = async () => {
      try {
        const data = await getRecordings(controller.signal);
        if (controller.signal.aborted) return;
        setState({ kind: 'success', data });
        if (data.items.some((item) => ACTIVE_STATUSES.has(item.status))) {
          timer = window.setTimeout(load, 3000);
        }
      } catch (error) {
        if (!controller.signal.aborted) {
          setState({
            kind: 'error',
            message:
              error instanceof ApiError
                ? error.message
                : '녹음 목록을 불러오지 못했습니다.',
          });
        }
      }
    };
    void load();
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [attempt]);

  return (
    <main className="shell shell--wide">
      <p className="eyebrow">VOICE TO DOCUMENT</p>
      <h1>녹음 대시보드</h1>
      <p className="intro">감지된 녹음의 처리 상태와 최근 결과를 확인합니다.</p>

      {state.kind === 'loading' && (
        <section className="panel" aria-live="polite">
          <p className="status status--loading">
            녹음 목록을 불러오고 있습니다…
          </p>
        </section>
      )}

      {state.kind === 'error' && (
        <section className="panel panel--error" role="alert">
          <h2>목록 갱신 실패</h2>
          <p>{state.message}</p>
          <button
            type="button"
            onClick={() => setAttempt((value) => value + 1)}
          >
            다시 불러오기
          </button>
        </section>
      )}

      {state.kind === 'success' && (
        <>
          <section className="status-grid" aria-label="상태별 녹음 수">
            {Object.entries(state.data.status_counts).map(([status, count]) => (
              <article className="stat-card" key={status}>
                <strong>{count}</strong>
                <span>{statusLabel(status as RecordingStatus)}</span>
              </article>
            ))}
          </section>

          <section className="panel">
            <div className="section-heading">
              <h2>최근 녹음</h2>
              <span>총 {state.data.total}개</span>
            </div>
            {state.data.items.length === 0 ? (
              <div className="empty-state">
                <h3>아직 감지된 녹음이 없습니다</h3>
                <p>입력 폴더에 안정된 m4a 파일을 넣으면 여기에 표시됩니다.</p>
              </div>
            ) : (
              <ul className="recording-list">
                {state.data.items.map((recording) => (
                  <li key={recording.id}>
                    <Link to={`/recordings/${recording.id}`}>
                      <span>
                        <strong>{recording.original_name}</strong>
                        <small>{recording.category ?? '분류 대기'}</small>
                      </span>
                      <span
                        className={`badge badge--${recording.status.toLowerCase()}`}
                      >
                        {statusLabel(recording.status)}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </main>
  );
}

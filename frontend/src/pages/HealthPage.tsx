import { useEffect, useState } from 'react';

import { ApiError } from '../api/client';
import { getReadiness, type ReadinessResponse } from '../api/health';

type ViewState =
  | { kind: 'loading' }
  | { kind: 'success'; data: ReadinessResponse }
  | { kind: 'error'; message: string };

export function HealthPage() {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<ViewState>({ kind: 'loading' });

  useEffect(() => {
    const controller = new AbortController();
    setState({ kind: 'loading' });
    getReadiness(controller.signal).then(
      (data) => setState({ kind: 'success', data }),
      (error: unknown) => {
        if (!controller.signal.aborted) {
          setState({
            kind: 'error',
            message:
              error instanceof ApiError
                ? error.message
                : '상태를 확인하지 못했습니다.',
          });
        }
      },
    );
    return () => controller.abort();
  }, [attempt]);

  return (
    <main className="shell">
      <p className="eyebrow">VOICE TO DOCUMENT</p>
      <h1>서비스 준비 상태</h1>
      <p className="intro">
        녹음 처리 서비스를 시작할 준비가 되었는지 확인합니다.
      </p>

      {state.kind === 'loading' && (
        <section className="panel" aria-live="polite">
          <p className="status status--loading">상태를 확인하고 있습니다…</p>
        </section>
      )}

      {state.kind === 'error' && (
        <section className="panel panel--error" role="alert">
          <h2>API 연결 실패</h2>
          <p>{state.message}</p>
          <button
            type="button"
            onClick={() => setAttempt((value) => value + 1)}
          >
            다시 확인
          </button>
        </section>
      )}

      {state.kind === 'success' && (
        <section className="panel" aria-live="polite">
          <h2>
            {state.data.status === 'ready'
              ? '사용할 준비가 되었습니다'
              : '준비가 필요합니다'}
          </h2>
          <p className={`status status--${state.data.status}`}>
            {state.data.status === 'ready' ? '준비 완료' : '준비되지 않음'}
          </p>
          <ul className="checks">
            {Object.entries(state.data.checks).map(([name, check]) => (
              <li key={name}>
                <span>{name}</span>
                <strong>{check.status === 'ok' ? '정상' : '오류'}</strong>
                {check.message && <small>{check.message}</small>}
              </li>
            ))}
          </ul>
        </section>
      )}
    </main>
  );
}

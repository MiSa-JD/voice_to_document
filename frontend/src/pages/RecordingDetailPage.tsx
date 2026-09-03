import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { ApiError } from '../api/client';
import {
  ACTIVE_STATUSES,
  createRetranscription,
  getLatestRetranscription,
  getRecording,
  statusLabel,
  updateRecordingCategory,
  type RecordingDetailResponse,
  type RetranscriptionLatestResponse,
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

      {state.kind === 'success' && (
        <RecordingDetail
          data={state.data}
          onReload={() => setAttempt((value) => value + 1)}
        />
      )}
    </main>
  );
}

function RecordingDetail({
  data,
  onReload,
}: {
  data: RecordingDetailResponse;
  onReload: () => void;
}) {
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

      <Link className="button-link" to={`/recordings/${recording.id}/speakers`}>
        화자 검토
      </Link>

      <CategoryPanel data={data} onReload={onReload} />

      <RetranscriptionPanel data={data} onReload={onReload} />

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
          <SummaryPanel summary={data.summary} />
        ) : (
          <p className="muted">생성된 요약이 없습니다.</p>
        )}
      </section>

      <section className="panel detail-section">
        <h2>처리 이력</h2>
        <ul className="job-list">
          {data.jobs.map((job) => {
            const retryPending = job.status === 'queued' && job.error_code;
            const failureStatus =
              job.status === 'failed' && job.error_code
                ? job.attempts >= 3
                  ? '자동 재시도 종료'
                  : '사용자 조치 필요'
                : job.status;
            return (
              <li key={job.id}>
                <div className="job-summary">
                  <strong>{job.kind}</strong>
                  <span>
                    {retryPending ? '자동 재시도 대기' : failureStatus}
                  </span>
                  <small>{job.attempts}회 시도</small>
                </div>
                {job.error_code && job.error_message && (
                  <p className="job-error" role="status">
                    <code>{job.error_code}</code>
                    <span>{job.error_message}</span>
                  </p>
                )}
              </li>
            );
          })}
        </ul>
      </section>
    </>
  );
}

function CategoryPanel({
  data,
  onReload,
}: {
  data: RecordingDetailResponse;
  onReload: () => void;
}) {
  const { recording } = data;
  const [selected, setSelected] = useState(recording.category ?? '');
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    setSelected(recording.category ?? '');
  }, [recording.category, recording.revision]);

  const submit = async () => {
    setSubmitting(true);
    setMessage(null);
    try {
      await updateRecordingCategory(recording.id, selected, recording.revision);
      setMessage('범주를 저장했습니다. 새 문서를 반영하고 있습니다.');
      onReload();
    } catch (error) {
      if (error instanceof ApiError && error.code === 'REVISION_CONFLICT') {
        setMessage(
          '다른 변경이 먼저 반영되어 최신 내용을 다시 불러옵니다. 확인 후 다시 선택해 주세요.',
        );
        onReload();
      } else if (error instanceof ApiError && error.status === 409) {
        setMessage('관련 결과를 처리 중입니다. 완료된 뒤 다시 저장해 주세요.');
      } else if (error instanceof ApiError && error.status === 422) {
        setMessage(`${error.message} 다른 범주를 선택해 주세요.`);
      } else {
        setMessage(
          error instanceof ApiError
            ? error.message
            : '범주를 저장하지 못했습니다. 연결을 확인하고 다시 시도해 주세요.',
        );
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="panel detail-section category-panel">
      <h2>범주</h2>
      <dl className="category-details">
        <div>
          <dt>현재 적용</dt>
          <dd>
            {recording.category ?? '분류 대기'} ·{' '}
            {recording.category_source === 'manual'
              ? '수동'
              : recording.category_source === 'auto'
                ? '자동'
                : '출처 대기'}
          </dd>
        </div>
        <div>
          <dt>자동 분류 제안</dt>
          <dd>{recording.automatic_category ?? '아직 없음'}</dd>
        </div>
        <div>
          <dt>자동 신뢰도</dt>
          <dd>
            {recording.category_confidence == null
              ? '아직 없음'
              : `${Math.round(recording.category_confidence * 100)}%`}
          </dd>
        </div>
        <div>
          <dt>자동 분류 근거</dt>
          <dd>{recording.category_reason ?? '아직 없음'}</dd>
        </div>
      </dl>
      {recording.category && (
        <div className="category-form">
          <label htmlFor="recording-category">적용할 범주</label>
          <select
            id="recording-category"
            value={selected}
            disabled={submitting}
            onChange={(event) => {
              setSelected(event.target.value);
              setMessage(null);
            }}
          >
            {(data.allowed_categories ?? []).map((category) => (
              <option key={category} value={category}>
                {category}
              </option>
            ))}
          </select>
          <button
            type="button"
            disabled={submitting || selected === recording.category}
            onClick={() => void submit()}
          >
            {submitting ? '저장 중…' : '범주 저장'}
          </button>
        </div>
      )}
      <p className="category-message" aria-live="polite">
        {message}
      </p>
    </section>
  );
}

type RetranscriptionStep = 'closed' | 'edit' | 'confirm';

function RetranscriptionPanel({
  data,
  onReload,
}: {
  data: RecordingDetailResponse;
  onReload: () => void;
}) {
  const [step, setStep] = useState<RetranscriptionStep>('closed');
  const [language, setLanguage] = useState<'auto' | 'ko' | 'en' | 'ja'>('auto');
  const [description, setDescription] = useState('');
  const [terms, setTerms] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [latest, setLatest] = useState<RetranscriptionLatestResponse | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const [pollAttempt, setPollAttempt] = useState(0);
  const refreshedRequest = useState<string | null>(null);
  const refreshedRequestId = refreshedRequest[0];
  const setRefreshedRequestId = refreshedRequest[1];

  useEffect(() => {
    const controller = new AbortController();
    let timer: number | undefined;
    const load = async () => {
      try {
        const result = await getLatestRetranscription(
          data.recording.id,
          controller.signal,
        );
        if (controller.signal.aborted) return;
        setLatest(result);
        if (result.status === 'queued' || result.status === 'running') {
          timer = window.setTimeout(load, 1500);
        } else if (
          result.status === 'succeeded' &&
          refreshedRequestId !== result.request_id
        ) {
          setRefreshedRequestId(result.request_id);
          onReload();
        }
      } catch (loadError) {
        if (
          !controller.signal.aborted &&
          !(loadError instanceof ApiError && loadError.status === 404)
        ) {
          setError(
            loadError instanceof ApiError
              ? loadError.message
              : '재전사 상태를 불러오지 못했습니다.',
          );
        }
      }
    };
    void load();
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [
    data.recording.id,
    onReload,
    pollAttempt,
    refreshedRequestId,
    setRefreshedRequestId,
  ]);

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      await createRetranscription(data.recording.id, {
        expected_revision: data.recording.revision,
        language,
        content_description: description.trim() || null,
        terms: terms
          .split(/[\n,]/)
          .map((value) => value.trim())
          .filter(Boolean),
        confirm_impact: true,
      });
      setStep('closed');
      const result = await getLatestRetranscription(data.recording.id);
      setLatest(result);
      setPollAttempt((value) => value + 1);
    } catch (submitError) {
      setError(
        submitError instanceof ApiError
          ? submitError.message
          : 'STT 재수행을 요청하지 못했습니다.',
      );
    } finally {
      setSubmitting(false);
    }
  };

  const active = latest?.status === 'queued' || latest?.status === 'running';
  return (
    <section className="panel detail-section retranscription-panel">
      <div className="section-heading">
        <div>
          <h2>STT 다시 수행</h2>
          <p className="muted">
            언어와 선택 힌트를 사용해 음성 인식부터 다시 처리합니다.
          </p>
        </div>
        {step === 'closed' && !active && (
          <button type="button" onClick={() => setStep('edit')}>
            재전사 설정 열기
          </button>
        )}
      </div>

      {step === 'edit' && (
        <form
          className="retranscription-form"
          onSubmit={(event) => {
            event.preventDefault();
            setStep('confirm');
          }}
        >
          <label>
            녹음 언어
            <select
              value={language}
              onChange={(event) =>
                setLanguage(event.target.value as typeof language)
              }
            >
              <option value="auto">자동 감지</option>
              <option value="ko">한국어</option>
              <option value="en">영어</option>
              <option value="ja">일본어</option>
            </select>
          </label>
          <label>
            대략적인 내용 설명 (선택)
            <textarea
              value={description}
              maxLength={1000}
              onChange={(event) => setDescription(event.target.value)}
            />
          </label>
          <label>
            고유명사·전문용어 (선택)
            <textarea
              value={terms}
              aria-describedby="terms-help"
              onChange={(event) => setTerms(event.target.value)}
            />
          </label>
          <p id="terms-help" className="muted">
            쉼표 또는 줄바꿈으로 구분하고 최대 50개까지 입력하세요.
          </p>
          <p className="accuracy-warning">
            힌트는 정확도 향상을 보장하지 않습니다. 잘못된 언어 고정이나
            부정확한 힌트는 결과를 악화시킬 수 있습니다.
          </p>
          <button type="submit">영향 확인</button>
          <button
            className="button-secondary"
            type="button"
            onClick={() => setStep('closed')}
          >
            취소
          </button>
        </form>
      )}

      {step === 'confirm' && (
        <section
          className="retranscription-confirm"
          aria-label="재전사 영향 확인"
        >
          <h3>기존 결과 교체 영향</h3>
          <ul>
            <li>새 결과가 모두 성공한 뒤 현재 transcript가 교체됩니다.</li>
            <li>화자 연결과 대표 클립은 다시 검토해야 합니다.</li>
            <li>기존 분류와 요약은 stale 처리되어 다시 생성됩니다.</li>
            <li>실패하면 현재 성공 결과는 그대로 유지됩니다.</li>
          </ul>
          <button
            type="button"
            disabled={submitting}
            onClick={() => void submit()}
          >
            {submitting ? '요청 중…' : '영향을 확인했고 STT 다시 수행'}
          </button>
          <button
            className="button-secondary"
            type="button"
            disabled={submitting}
            onClick={() => setStep('edit')}
          >
            설정으로 돌아가기
          </button>
        </section>
      )}

      {latest && (
        <RetranscriptionStatus
          latest={latest}
          recordingId={data.recording.id}
        />
      )}
      {error && (
        <p className="inline-error" role="alert">
          {error}
        </p>
      )}
      {latest?.status === 'failed' && step === 'closed' && (
        <button type="button" onClick={() => setStep('edit')}>
          설정을 확인하고 다시 시도
        </button>
      )}
    </section>
  );
}

function RetranscriptionStatus({
  latest,
  recordingId,
}: {
  latest: RetranscriptionLatestResponse;
  recordingId: string;
}) {
  const label =
    {
      queued: latest.error_code ? '자동 재시도 대기' : '처리 대기',
      running: '음성 처리 진행 중',
      failed: '재전사 실패',
      succeeded: '재전사 완료',
    }[latest.status] ?? latest.status;
  return (
    <div
      className={`retranscription-status retranscription-status--${latest.status}`}
      role="status"
    >
      <strong>{label}</strong>
      {latest.status === 'failed' && (
        <p>기존 성공 transcript는 계속 표시됩니다.</p>
      )}
      {latest.status === 'succeeded' && (
        <>
          <dl className="comparison-grid">
            <div>
              <dt>언어</dt>
              <dd>
                {latest.previous_language ?? '알 수 없음'} →{' '}
                {latest.new_language ?? latest.requested_language}
              </dd>
            </div>
            <div>
              <dt>발화 수</dt>
              <dd>
                {latest.previous_segment_count} →{' '}
                {latest.new_segment_count ?? 0}
              </dd>
            </div>
            <div>
              <dt>미확정 화자</dt>
              <dd>{latest.unresolved_speaker_count ?? 0}명</dd>
            </div>
          </dl>
          <Link
            className="button-link"
            to={`/recordings/${recordingId}/speakers`}
          >
            화자 다시 검토
          </Link>
        </>
      )}
    </div>
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

type CategorySummary = NonNullable<RecordingDetailResponse['summary']>;

function SummaryPanel({ summary }: { summary: CategorySummary }) {
  const facts = (items: Array<{ text: string }>) =>
    items.map((item) => item.text);
  switch (summary.template) {
    case 'lecture':
      return (
        <div className="summary-grid">
          <SummaryList title="핵심 주제" items={facts(summary.core_topics)} />
          <SummaryList
            title="개념"
            items={facts(summary.concepts)}
            empty="없음"
          />
          <SummaryList
            title="예시"
            items={facts(summary.examples)}
            empty="없음"
          />
          <SummaryList
            title="복습 항목"
            items={facts(summary.review_items)}
            empty="없음"
          />
        </div>
      );
    case 'meeting':
      return (
        <div className="summary-grid">
          <SummaryList title="목적" items={[summary.purpose.text]} />
          <SummaryList
            title="논의 내용"
            items={facts(summary.discussion)}
            empty="없음"
          />
          <SummaryList
            title="결정 사항"
            items={facts(summary.decisions)}
            empty="없음"
          />
          <SummaryList
            title="할 일"
            items={summary.action_items.map(
              (item) =>
                `${item.task} (담당자: ${item.assignee ?? '확인되지 않음'}, 기한: ${item.due_date ?? '확인되지 않음'})`,
            )}
            empty="없음"
          />
          <SummaryList
            title="미해결 사항"
            items={facts(summary.open_questions)}
            empty="없음"
          />
        </div>
      );
    case 'daily_conversation':
      return (
        <div className="summary-grid">
          <SummaryList title="주요 화제" items={facts(summary.main_topics)} />
          <SummaryList
            title="합의·약속"
            items={facts(summary.agreements)}
            empty="없음"
          />
          <SummaryList
            title="기억할 사항"
            items={facts(summary.reminders)}
            empty="없음"
          />
        </div>
      );
    case 'game_list':
      return (
        <div className="summary-grid">
          <SummaryList title="게임" items={facts(summary.games)} />
          <SummaryList
            title="선호·평가"
            items={facts(summary.preferences)}
            empty="없음"
          />
          <SummaryList
            title="후속 확인"
            items={facts(summary.follow_ups)}
            empty="없음"
          />
        </div>
      );
    case 'other':
      return (
        <div className="summary-grid">
          <SummaryList title="핵심 요약" items={[summary.key_summary.text]} />
          <SummaryList
            title="주요 사실"
            items={facts(summary.key_facts)}
            empty="없음"
          />
          <SummaryList
            title="후속 항목"
            items={facts(summary.follow_ups)}
            empty="없음"
          />
        </div>
      );
  }
}

function formatDuration(milliseconds: number) {
  const seconds = Math.floor(milliseconds / 1000);
  return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
}

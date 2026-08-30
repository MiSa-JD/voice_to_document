import { useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { ApiError } from '../api/client';
import {
  assignRecordingSpeaker,
  assignSegmentSpeakers,
  createPerson,
  getPersons,
  getRecording,
  mediaUrl,
  type Person,
  type RecordingDetailResponse,
} from '../api/recordings';

type ViewState =
  | { kind: 'loading' }
  | { kind: 'success'; data: RecordingDetailResponse; persons: Person[] }
  | { kind: 'error'; message: string };

const UNKNOWN = '__unknown__';
const NEW_PERSON = '__new__';

type DraftTarget =
  | { kind: 'person'; personId: string; label: string }
  | { kind: 'unknown'; label: string }
  | { kind: 'new'; displayName: string; label: string };

type RevisionConflict = { currentRevision: number | null };
type NewPersonContext =
  { kind: 'speaker'; localSpeakerId: string } | { kind: 'draft' };

export function SpeakerReviewPage() {
  const { id = '' } = useParams();
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<ViewState>({ kind: 'loading' });

  useEffect(() => {
    const controller = new AbortController();
    setState({ kind: 'loading' });
    Promise.all([
      getRecording(id, controller.signal),
      getPersons(controller.signal),
    ]).then(
      ([data, people]) =>
        setState({ kind: 'success', data, persons: people.items }),
      (error: unknown) => {
        if (!controller.signal.aborted) {
          setState({
            kind: 'error',
            message:
              error instanceof ApiError
                ? error.message
                : '화자 검토 정보를 불러오지 못했습니다.',
          });
        }
      },
    );
    return () => controller.abort();
  }, [attempt, id]);

  return (
    <main className="shell shell--wide">
      <p className="eyebrow">SPEAKER REVIEW</p>
      <h1>화자 검토</h1>

      {state.kind === 'loading' && (
        <section className="panel" aria-live="polite">
          <p className="status status--loading">
            화자 정보를 불러오고 있습니다…
          </p>
        </section>
      )}
      {state.kind === 'error' && (
        <section className="panel panel--error" role="alert">
          <h2>화자 정보 갱신 실패</h2>
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
        <SpeakerReview
          data={state.data}
          persons={state.persons}
          onReload={() => setAttempt((value) => value + 1)}
        />
      )}
    </main>
  );
}

function SpeakerReview({
  data,
  persons,
  onReload,
}: {
  data: RecordingDetailResponse;
  persons: Person[];
  onReload: () => void;
}) {
  const [selectedSpeaker, setSelectedSpeaker] = useState<string | null>(
    data.speakers[0]?.local_speaker_id ?? null,
  );
  const [savingSpeaker, setSavingSpeaker] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [selectedSegments, setSelectedSegments] = useState<Set<string>>(
    new Set(),
  );
  const [draftTarget, setDraftTarget] = useState<DraftTarget | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [savingDraft, setSavingDraft] = useState(false);
  const [conflict, setConflict] = useState<RevisionConflict | null>(null);
  const [newPersonContext, setNewPersonContext] =
    useState<NewPersonContext | null>(null);
  const [newPersonName, setNewPersonName] = useState('');
  const [newPersonError, setNewPersonError] = useState<string | null>(null);
  const [creatingPerson, setCreatingPerson] = useState(false);
  const audioRef = useRef<HTMLAudioElement>(null);
  const newPersonInputRef = useRef<HTMLInputElement>(null);
  const newPersonTriggerRef = useRef<HTMLElement | null>(null);
  const recordingAudio = data.artifacts.find(
    (artifact) => artifact.kind === 'recording_audio',
  );
  const hasDraft = selectedSegments.size > 0 || draftTarget !== null;

  useEffect(() => {
    if (!hasDraft) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [hasDraft]);

  useEffect(() => {
    if (newPersonContext) newPersonInputRef.current?.focus();
  }, [newPersonContext]);

  const seek = (milliseconds: number) => {
    if (!audioRef.current) return;
    audioRef.current.currentTime = milliseconds / 1000;
    void audioRef.current.play().catch(() => undefined);
  };

  const assign = async (localSpeakerId: string, value: string) => {
    const personId: string | null = value === UNKNOWN ? null : value;
    if (value === NEW_PERSON) {
      return;
    }
    setSavingSpeaker(localSpeakerId);
    setMessage(null);
    try {
      await assignRecordingSpeaker(
        data.recording.id,
        localSpeakerId,
        personId,
        data.recording.revision,
      );
      onReload();
    } catch (error) {
      if (isRevisionConflict(error)) {
        setConflict({ currentRevision: currentRevision(error) });
      } else {
        setMessage(
          error instanceof ApiError
            ? error.message
            : '화자 연결을 저장하지 못했습니다.',
        );
      }
    } finally {
      setSavingSpeaker(null);
    }
  };

  const openNewPerson = (context: NewPersonContext, trigger: HTMLElement) => {
    setConfirming(false);
    setNewPersonContext(context);
    setNewPersonName('');
    setNewPersonError(null);
    newPersonTriggerRef.current = trigger;
  };

  const closeNewPerson = () => {
    const trigger = newPersonTriggerRef.current;
    setNewPersonContext(null);
    setNewPersonName('');
    setNewPersonError(null);
    window.setTimeout(() => trigger?.focus(), 0);
  };

  const submitNewPerson = async (event: React.FormEvent) => {
    event.preventDefault();
    const displayName = newPersonName.trim();
    if (!displayName) {
      setNewPersonError('인물 이름을 입력하세요.');
      newPersonInputRef.current?.focus();
      return;
    }
    if (!newPersonContext) return;
    if (newPersonContext.kind === 'draft') {
      setDraftTarget({ kind: 'new', displayName, label: displayName });
      closeNewPerson();
      return;
    }
    setCreatingPerson(true);
    setNewPersonError(null);
    try {
      const person = await createPerson(displayName);
      const speakerId = newPersonContext.localSpeakerId;
      closeNewPerson();
      await assign(speakerId, person.id);
    } catch (error) {
      setNewPersonError(
        error instanceof ApiError ? error.message : '인물을 만들지 못했습니다.',
      );
    } finally {
      setCreatingPerson(false);
    }
  };

  const selectTarget = (value: string) => {
    setConfirming(false);
    if (value === UNKNOWN) {
      setDraftTarget({ kind: 'unknown', label: '알 수 없음' });
      return;
    }
    if (value === NEW_PERSON) {
      return;
    }
    const person = persons.find((item) => item.id === value);
    if (person)
      setDraftTarget({
        kind: 'person',
        personId: person.id,
        label: person.display_name,
      });
  };

  const saveDraft = async () => {
    if (!draftTarget || selectedSegments.size === 0) return;
    setSavingDraft(true);
    setMessage(null);
    try {
      let personId: string | null = null;
      if (draftTarget.kind === 'person') personId = draftTarget.personId;
      if (draftTarget.kind === 'new') {
        const person = await createPerson(draftTarget.displayName);
        personId = person.id;
        setDraftTarget({
          kind: 'person',
          personId: person.id,
          label: person.display_name,
        });
      }
      await assignSegmentSpeakers(
        data.recording.id,
        [...selectedSegments],
        personId,
        data.recording.revision,
      );
      setSelectedSegments(new Set());
      setDraftTarget(null);
      setConfirming(false);
      onReload();
    } catch (error) {
      if (isRevisionConflict(error)) {
        setConflict({ currentRevision: currentRevision(error) });
      } else {
        setMessage(
          error instanceof ApiError
            ? error.message
            : '발화 변경을 저장하지 못했습니다.',
        );
      }
    } finally {
      setSavingDraft(false);
    }
  };

  const discardDraft = () => {
    setSelectedSegments(new Set());
    setDraftTarget(null);
    setConfirming(false);
  };

  const leaveReview = (event: React.MouseEvent<HTMLAnchorElement>) => {
    if (
      hasDraft &&
      !window.confirm('저장하지 않은 발화 변경을 폐기하고 이동할까요?')
    ) {
      event.preventDefault();
    }
  };

  const acceptLatest = () => {
    if (!window.confirm('로컬 변경을 폐기하고 최신 서버 내용을 불러올까요?'))
      return;
    discardDraft();
    setConflict(null);
    onReload();
  };

  return (
    <>
      <Link
        className="back-link"
        to={`/recordings/${data.recording.id}`}
        onClick={leaveReview}
      >
        ← 녹음 상세
      </Link>
      <p className="intro">
        {data.recording.original_name}의 음성을 듣고 인물을 연결합니다.
      </p>
      <aside className="accuracy-warning" role="note">
        <strong>
          화자 후보는 유사도 기반 편의 기능이며 신원 인증이 아닙니다.
        </strong>
        <p>대표 음성을 직접 듣고 연결할 인물이 맞는지 확인해 주세요.</p>
      </aside>
      <section className="panel detail-section">
        <h2>원본 오디오</h2>
        {recordingAudio ? (
          <audio
            ref={audioRef}
            controls
            aria-label="녹음 전체 오디오"
            src={mediaUrl(recordingAudio.id)}
          >
            오디오 재생을 지원하지 않는 브라우저입니다.
          </audio>
        ) : (
          <p className="muted">재생할 원본 오디오가 없습니다.</p>
        )}
      </section>

      {message && (
        <p className="inline-error" role="alert">
          {message}
        </p>
      )}
      {conflict && (
        <section className="conflict-notice" role="alert">
          <h2>다른 변경이 먼저 저장되었습니다</h2>
          <p>
            저장을 중단했습니다. 로컬 변경은 유지됩니다.
            {conflict.currentRevision !== null &&
              ` 서버의 최신 revision은 ${conflict.currentRevision}입니다.`}
          </p>
          <button type="button" onClick={acceptLatest}>
            로컬 변경 폐기 후 최신 내용 불러오기
          </button>
        </section>
      )}

      <section className="speaker-layout">
        <div className="speaker-cards" aria-label="녹음 화자">
          {data.speakers.length === 0 ? (
            <div className="panel empty-state">
              <p>검토할 화자가 없습니다.</p>
            </div>
          ) : (
            data.speakers.map((speaker) => (
              <article
                className={`panel speaker-card${selectedSpeaker === speaker.local_speaker_id ? ' speaker-card--selected' : ''}`}
                key={speaker.local_speaker_id}
              >
                <button
                  className="speaker-select"
                  type="button"
                  aria-pressed={selectedSpeaker === speaker.local_speaker_id}
                  aria-label={`${speaker.speaker_name ?? speaker.local_speaker_id}, ${speaker.segment_count}개 발화, ${selectedSpeaker === speaker.local_speaker_id ? '선택됨' : '선택 안 됨'}`}
                  onClick={() => setSelectedSpeaker(speaker.local_speaker_id)}
                >
                  <span>
                    {speaker.speaker_name ?? speaker.local_speaker_id}
                  </span>
                  <small>
                    {speaker.segment_count}개 발화 ·{' '}
                    {formatDuration(speaker.duration_ms)}
                  </small>
                </button>
                <SpeakerMatchEvidence
                  speaker={speaker}
                  busy={savingSpeaker !== null}
                  onAssign={(personId) =>
                    void assign(speaker.local_speaker_id, personId)
                  }
                />
                {speaker.representative_clip_artifact_id ? (
                  <audio
                    controls
                    aria-label={`${speaker.local_speaker_id} 대표 클립`}
                    src={mediaUrl(speaker.representative_clip_artifact_id)}
                  >
                    대표 클립을 재생할 수 없습니다.
                  </audio>
                ) : (
                  <p className="muted">
                    {clipStatusLabel(speaker.clip_status)}
                  </p>
                )}
                <label>
                  인물 연결
                  <select
                    aria-label={`${speaker.local_speaker_id} 인물 연결`}
                    disabled={savingSpeaker !== null}
                    value={speaker.person_id ?? UNKNOWN}
                    onChange={(event) => {
                      if (event.target.value === NEW_PERSON) {
                        openNewPerson(
                          {
                            kind: 'speaker',
                            localSpeakerId: speaker.local_speaker_id,
                          },
                          event.currentTarget,
                        );
                      } else {
                        void assign(
                          speaker.local_speaker_id,
                          event.target.value,
                        );
                      }
                    }}
                  >
                    <option value={UNKNOWN}>알 수 없음</option>
                    {persons.map((person) => (
                      <option key={person.id} value={person.id}>
                        {person.display_name}
                      </option>
                    ))}
                    <option value={NEW_PERSON}>+ 새 인물</option>
                  </select>
                </label>
                {newPersonContext?.kind === 'speaker' &&
                  newPersonContext.localSpeakerId ===
                    speaker.local_speaker_id && (
                    <NewPersonForm
                      inputRef={newPersonInputRef}
                      value={newPersonName}
                      error={newPersonError}
                      busy={creatingPerson}
                      onChange={setNewPersonName}
                      onSubmit={submitNewPerson}
                      onCancel={closeNewPerson}
                    />
                  )}
                {savingSpeaker === speaker.local_speaker_id && (
                  <small role="status">저장 중…</small>
                )}
              </article>
            ))
          )}
        </div>

        <section className="panel transcript-panel">
          <h2>Transcript</h2>
          {data.segments.length > 0 && (
            <div className="draft-toolbar">
              <strong>{selectedSegments.size}개 발화 선택</strong>
              <label>
                변경할 인물
                <select
                  aria-label="선택 발화 변경 인물"
                  value={
                    draftTarget?.kind === 'person'
                      ? draftTarget.personId
                      : draftTarget?.kind === 'unknown'
                        ? UNKNOWN
                        : draftTarget?.kind === 'new'
                          ? NEW_PERSON
                          : ''
                  }
                  onChange={(event) => {
                    if (event.target.value === NEW_PERSON) {
                      openNewPerson({ kind: 'draft' }, event.currentTarget);
                    } else {
                      selectTarget(event.target.value);
                    }
                  }}
                >
                  <option value="">인물 선택</option>
                  <option value={UNKNOWN}>알 수 없음</option>
                  {persons.map((person) => (
                    <option key={person.id} value={person.id}>
                      {person.display_name}
                    </option>
                  ))}
                  <option value={NEW_PERSON}>+ 새 인물</option>
                </select>
              </label>
              {newPersonContext?.kind === 'draft' && (
                <NewPersonForm
                  inputRef={newPersonInputRef}
                  value={newPersonName}
                  error={newPersonError}
                  busy={creatingPerson}
                  onChange={setNewPersonName}
                  onSubmit={submitNewPerson}
                  onCancel={closeNewPerson}
                />
              )}
              <button
                type="button"
                disabled={!draftTarget || selectedSegments.size === 0}
                onClick={() => setConfirming(true)}
              >
                변경 확인
              </button>
              {hasDraft && (
                <button
                  className="button-secondary"
                  type="button"
                  onClick={discardDraft}
                >
                  변경 폐기
                </button>
              )}
            </div>
          )}
          {confirming && draftTarget && (
            <section
              className="change-confirmation"
              aria-label="발화 변경 확인"
            >
              <h3>저장 전 변경 확인</h3>
              <p>
                <strong>{selectedSegments.size}개 발화</strong>를{' '}
                <strong>{draftTarget.label}</strong>(으)로 변경합니다.
              </p>
              <ul>
                {data.segments
                  .filter((segment) => selectedSegments.has(segment.id))
                  .map((segment) => (
                    <li key={segment.id}>
                      {segment.speaker_name ??
                        segment.local_speaker_id ??
                        '화자 미배정'}{' '}
                      → {draftTarget.label}
                    </li>
                  ))}
              </ul>
              <button
                type="button"
                disabled={savingDraft}
                onClick={() => void saveDraft()}
              >
                {savingDraft ? '저장 중…' : '일괄 저장'}
              </button>
              <button
                className="button-secondary"
                type="button"
                disabled={savingDraft}
                onClick={() => setConfirming(false)}
              >
                계속 수정
              </button>
            </section>
          )}
          {data.segments.length === 0 ? (
            <p className="muted">아직 transcript가 없습니다.</p>
          ) : (
            <ol className="transcript">
              {data.segments.map((segment) => (
                <li
                  className={
                    selectedSpeaker === segment.local_speaker_id
                      ? 'transcript__row--selected'
                      : ''
                  }
                  key={segment.id}
                >
                  <input
                    type="checkbox"
                    aria-label={`${formatDuration(segment.start_ms)} 발화 선택`}
                    checked={selectedSegments.has(segment.id)}
                    onChange={(event) => {
                      setConfirming(false);
                      setSelectedSegments((current) => {
                        const next = new Set(current);
                        if (event.target.checked) next.add(segment.id);
                        else next.delete(segment.id);
                        return next;
                      });
                    }}
                  />
                  <button
                    className="timestamp"
                    type="button"
                    aria-label={`${formatDuration(segment.start_ms)}부터 오디오 재생`}
                    onClick={() => seek(segment.start_ms)}
                  >
                    {formatDuration(segment.start_ms)}
                  </button>
                  <div>
                    <strong>
                      {segment.speaker_name ??
                        segment.local_speaker_id ??
                        '화자 미배정'}
                    </strong>
                    <p>{segment.text}</p>
                  </div>
                </li>
              ))}
            </ol>
          )}
        </section>
      </section>
    </>
  );
}

function NewPersonForm({
  inputRef,
  value,
  error,
  busy,
  onChange,
  onSubmit,
  onCancel,
}: {
  inputRef: React.RefObject<HTMLInputElement | null>;
  value: string;
  error: string | null;
  busy: boolean;
  onChange: (value: string) => void;
  onSubmit: (event: React.FormEvent) => void;
  onCancel: () => void;
}) {
  const errorId = 'new-person-name-error';
  return (
    <form className="inline-person-form" onSubmit={onSubmit}>
      <label htmlFor="new-person-name">새 인물 이름</label>
      <p id="new-person-description" className="muted">
        transcript에 표시할 이름을 입력하세요.
      </p>
      <input
        ref={inputRef}
        id="new-person-name"
        value={value}
        maxLength={100}
        disabled={busy}
        aria-describedby={`new-person-description${error ? ` ${errorId}` : ''}`}
        aria-invalid={Boolean(error)}
        onChange={(event) => onChange(event.target.value)}
      />
      {error && (
        <p id={errorId} className="inline-error" role="alert">
          {error}
        </p>
      )}
      <div className="inline-person-form__actions">
        <button type="submit" disabled={busy}>
          {busy ? '만드는 중…' : '인물 만들기'}
        </button>
        <button
          className="button-secondary"
          type="button"
          disabled={busy}
          onClick={onCancel}
        >
          취소
        </button>
      </div>
    </form>
  );
}

type RecordingSpeaker = RecordingDetailResponse['speakers'][number];

function SpeakerMatchEvidence({
  speaker,
  busy,
  onAssign,
}: {
  speaker: RecordingSpeaker;
  busy: boolean;
  onAssign: (personId: string) => void;
}) {
  const match = speaker.match;
  const best = match?.candidates[0];
  const second = match?.candidates[1];
  return (
    <section
      className="match-evidence"
      aria-label={`${speaker.local_speaker_id} 자동 식별 근거`}
    >
      <p
        className={`assignment-source assignment-source--${speaker.speaker_source}`}
      >
        연결 상태: {speakerSourceLabel(speaker.speaker_source)}
        {speaker.speaker_source === 'auto' &&
          ` · 유사도 ${formatScore(speaker.speaker_score)}`}
      </p>
      {!match ? (
        <p className="candidate-status" role="status">
          {speaker.clip_status === 'pending'
            ? '대표 클립 생성과 후보 계산을 기다리고 있습니다.'
            : '후보 점수가 아직 없거나 계산 중입니다.'}
        </p>
      ) : (
        <>
          <p className="match-decision">
            <strong>판정:</strong> {matchDecisionReason(match.decision)}
          </p>
          {best ? (
            <dl className="match-metrics">
              <div>
                <dt>1순위 후보</dt>
                <dd>
                  {best.display_name} · 유사도 {formatScore(best.score)}
                </dd>
              </div>
              <div>
                <dt>2순위 점수</dt>
                <dd>
                  {formatScore(match.second_best_score)}
                  {!second && ' · 후보 없음'}
                </dd>
              </div>
              <div>
                <dt>1·2위 차이</dt>
                <dd>{formatScore(match.margin)}</dd>
              </div>
            </dl>
          ) : (
            <p className="candidate-status">
              비교할 수 있는 기존 인물 후보가 없습니다.
            </p>
          )}
          {match.candidates.length > 0 && (
            <ol className="match-candidates" aria-label="유사도 후보 목록">
              {match.candidates.map((candidate) => (
                <li key={candidate.person_id}>
                  <span>
                    {candidate.rank}위 {candidate.display_name} ·{' '}
                    {formatScore(candidate.score)}
                    {candidate.rejected && ' · 과거 자동 연결 거부'}
                  </span>
                  <button
                    className="candidate-action"
                    type="button"
                    disabled={busy}
                    onClick={() => onAssign(candidate.person_id)}
                  >
                    {candidate.display_name} 수동 확정
                  </button>
                </li>
              ))}
            </ol>
          )}
        </>
      )}
    </section>
  );
}

function formatDuration(milliseconds: number) {
  const seconds = Math.floor(milliseconds / 1000);
  return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
}

function formatScore(score: number | null) {
  return score === null ? '정보 없음' : `${Math.round(score * 100)}%`;
}

function speakerSourceLabel(source: RecordingSpeaker['speaker_source']) {
  return {
    auto: '자동 확정',
    manual: '수동 확정',
    unresolved: '미확정',
  }[source];
}

function matchDecisionReason(
  decision: NonNullable<RecordingSpeaker['match']>['decision'],
) {
  return {
    insufficient_clips: '대표 클립이 2개보다 적어 비교하지 않았습니다.',
    no_profiles: '같은 모델로 비교할 수 있는 인물 profile이 없습니다.',
    insufficient_profiles: '인물 profile의 수동 확인 표본이 부족합니다.',
    auto_disabled: '후보는 계산했지만 자동 확정 기능이 꺼져 있습니다.',
    below_threshold: '1순위 후보의 절대 유사도가 자동 확정 기준보다 낮습니다.',
    insufficient_margin: '1·2위 유사도 차이가 작아 수동 검토가 필요합니다.',
    duplicate_person:
      '같은 녹음의 다른 화자와 인물이 중복되어 확정하지 않았습니다.',
    rejected_candidate:
      '이 화자와 후보의 과거 자동 연결을 사용자가 거부했습니다.',
    auto_matched: '절대 유사도와 1·2위 차이 기준을 통과해 자동 확정했습니다.',
  }[decision];
}

function clipStatusLabel(
  status: RecordingDetailResponse['speakers'][number]['clip_status'],
) {
  return {
    pending: '대표 클립 생성 대기 중',
    insufficient: '대표 클립으로 적합한 발화가 부족합니다.',
    failed: '대표 클립을 만들지 못했습니다.',
    ready: '대표 클립을 찾을 수 없습니다.',
  }[status];
}

function isRevisionConflict(error: unknown): error is ApiError {
  return (
    error instanceof ApiError &&
    error.status === 409 &&
    error.code === 'REVISION_CONFLICT'
  );
}

function currentRevision(error: ApiError) {
  const value = error.details.current_revision;
  return typeof value === 'number' ? value : null;
}

import { useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { ApiError } from '../api/client';
import {
  assignRecordingSpeaker,
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
      <Link className="back-link" to={`/recordings/${id}`}>
        ← 녹음 상세
      </Link>
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
  const audioRef = useRef<HTMLAudioElement>(null);
  const recordingAudio = data.artifacts.find(
    (artifact) => artifact.kind === 'recording_audio',
  );

  const seek = (milliseconds: number) => {
    if (!audioRef.current) return;
    audioRef.current.currentTime = milliseconds / 1000;
    void audioRef.current.play().catch(() => undefined);
  };

  const assign = async (localSpeakerId: string, value: string) => {
    let personId: string | null = value === UNKNOWN ? null : value;
    if (value === NEW_PERSON) {
      const displayName = window.prompt('새 인물 이름을 입력하세요.');
      if (!displayName?.trim()) return;
      try {
        personId = (await createPerson(displayName)).id;
      } catch (error) {
        setMessage(
          error instanceof ApiError
            ? error.message
            : '인물을 만들지 못했습니다.',
        );
        return;
      }
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
      setMessage(
        error instanceof ApiError
          ? error.message
          : '화자 연결을 저장하지 못했습니다.',
      );
    } finally {
      setSavingSpeaker(null);
    }
  };

  return (
    <>
      <p className="intro">
        {data.recording.original_name}의 음성을 듣고 인물을 연결합니다.
      </p>
      <section className="panel detail-section">
        <h2>원본 오디오</h2>
        {recordingAudio ? (
          <audio ref={audioRef} controls src={mediaUrl(recordingAudio.id)}>
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
                <p className="candidate-status">
                  {speaker.speaker_source === 'auto' && speaker.speaker_name
                    ? `자동 배정 · 유사도 ${formatScore(speaker.speaker_score)}`
                    : speaker.speaker_source === 'manual'
                      ? '수동 배정'
                      : '자동 후보 없음'}
                </p>
                {speaker.representative_clip_artifact_id ? (
                  <audio
                    controls
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
                    onChange={(event) =>
                      void assign(speaker.local_speaker_id, event.target.value)
                    }
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
                {savingSpeaker === speaker.local_speaker_id && (
                  <small role="status">저장 중…</small>
                )}
              </article>
            ))
          )}
        </div>

        <section className="panel transcript-panel">
          <h2>Transcript</h2>
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
                  <button
                    className="timestamp"
                    type="button"
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

function formatDuration(milliseconds: number) {
  const seconds = Math.floor(milliseconds / 1000);
  return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
}

function formatScore(score: number | null) {
  return score === null ? '정보 없음' : `${Math.round(score * 100)}%`;
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

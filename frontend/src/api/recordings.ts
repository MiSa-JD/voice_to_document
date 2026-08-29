import type { components } from './schema';
import { requestJson } from './client';

export type RecordingStatus = components['schemas']['RecordingStatus'];
export type RecordingListResponse =
  components['schemas']['RecordingListResponse'];
export type RecordingDetailResponse =
  components['schemas']['RecordingDetailResponse'];
export type Person = components['schemas']['PersonResponse'];
export type PersonListResponse = components['schemas']['PersonListResponse'];

export const ACTIVE_STATUSES = new Set<RecordingStatus>([
  'DISCOVERED',
  'TRANSCRIBING',
  'CLASSIFYING',
  'READY_FOR_SUMMARY',
  'SUMMARIZING',
]);

const STATUS_LABELS: Record<RecordingStatus, string> = {
  DISCOVERED: '발견됨',
  TRANSCRIBING: '전사 중',
  SPEAKER_REVIEW: '화자 검토 필요',
  CLASSIFYING: '분류 중',
  READY_FOR_SUMMARY: '요약 준비',
  SUMMARIZING: '요약 중',
  COMPLETED: '완료',
  FAILED: '실패',
};

export function statusLabel(status: RecordingStatus) {
  return STATUS_LABELS[status];
}

export function getRecordings(signal?: AbortSignal) {
  return requestJson<RecordingListResponse>('/api/recordings', { signal });
}

export function getRecording(id: string, signal?: AbortSignal) {
  return requestJson<RecordingDetailResponse>(
    `/api/recordings/${encodeURIComponent(id)}`,
    { signal },
  );
}

export function getPersons(signal?: AbortSignal) {
  return requestJson<PersonListResponse>('/api/persons', { signal });
}

export function createPerson(displayName: string) {
  return requestJson<Person>(
    '/api/persons',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ display_name: displayName }),
    },
    [201],
  );
}

export function assignRecordingSpeaker(
  recordingId: string,
  localSpeakerId: string,
  personId: string | null,
  expectedRevision: number,
) {
  return requestJson<components['schemas']['SpeakerAssignmentResponse']>(
    `/api/recordings/${encodeURIComponent(recordingId)}/speakers/${encodeURIComponent(localSpeakerId)}`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        person_id: personId,
        expected_revision: expectedRevision,
      }),
    },
  );
}

export function assignSegmentSpeakers(
  recordingId: string,
  segmentIds: string[],
  personId: string | null,
  expectedRevision: number,
) {
  return requestJson<components['schemas']['SpeakerAssignmentResponse']>(
    '/api/segments/speakers',
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        recording_id: recordingId,
        segment_ids: segmentIds,
        person_id: personId,
        expected_revision: expectedRevision,
      }),
    },
  );
}

export function mediaUrl(artifactId: string) {
  return `/api/media/${encodeURIComponent(artifactId)}`;
}

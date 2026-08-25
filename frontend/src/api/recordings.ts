import type { components } from './schema';
import { requestJson } from './client';

export type RecordingStatus = components['schemas']['RecordingStatus'];
export type RecordingListResponse =
  components['schemas']['RecordingListResponse'];
export type RecordingDetailResponse =
  components['schemas']['RecordingDetailResponse'];

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

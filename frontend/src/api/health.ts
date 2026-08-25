import { requestJson } from './client';

export interface HealthCheck {
  status: 'ok' | 'error';
  message?: string;
}

export interface ReadinessResponse {
  status: 'ready' | 'not_ready';
  checks: Record<string, HealthCheck>;
}

export function getReadiness(signal?: AbortSignal): Promise<ReadinessResponse> {
  return requestJson<ReadinessResponse>(
    '/health/ready',
    { signal },
    [200, 503],
  );
}

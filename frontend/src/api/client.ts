export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number | null,
    readonly code: string | null = null,
    readonly details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export async function requestJson<T>(
  path: string,
  init?: RequestInit,
  acceptedStatuses: readonly number[] = [200],
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers: { Accept: 'application/json', ...init?.headers },
    });
  } catch {
    throw new ApiError('서버에 연결할 수 없습니다.', null);
  }

  if (!acceptedStatuses.includes(response.status)) {
    const body = (await response.json().catch(() => null)) as {
      error?: {
        message?: string;
        code?: string;
        details?: Record<string, unknown>;
      };
    } | null;
    throw new ApiError(
      body?.error?.message ?? `요청에 실패했습니다. (${response.status})`,
      response.status,
      body?.error?.code ?? null,
      body?.error?.details ?? {},
    );
  }
  return (await response.json()) as T;
}

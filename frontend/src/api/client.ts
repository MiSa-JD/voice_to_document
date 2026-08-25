export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number | null,
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
      error?: { message?: string };
    } | null;
    throw new ApiError(
      body?.error?.message ?? `요청에 실패했습니다. (${response.status})`,
      response.status,
    );
  }
  return (await response.json()) as T;
}

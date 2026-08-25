import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';

import { HealthPage } from '../src/pages/HealthPage';

function response(status: number, body: object) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

test('준비 상태를 로딩 후 표시한다', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(
      response(200, {
        status: 'ready',
        checks: { database: { status: 'ok' }, app_data: { status: 'ok' } },
      }),
    ),
  );

  render(<HealthPage />);

  expect(screen.getByText('상태를 확인하고 있습니다…')).toBeInTheDocument();
  expect(await screen.findByText('준비 완료')).toBeInTheDocument();
  expect(screen.getAllByText('정상')).toHaveLength(2);
});

test('503 readiness를 연결 오류와 구분한다', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(
      response(503, {
        status: 'not_ready',
        checks: {
          database: { status: 'error', message: 'database connection failed' },
        },
      }),
    ),
  );

  render(<HealthPage />);

  expect(await screen.findByText('준비되지 않음')).toBeInTheDocument();
  expect(screen.getByText('database connection failed')).toBeInTheDocument();
});

test('연결 실패 후 키보드로 다시 확인할 수 있다', async () => {
  const fetchMock = vi
    .fn()
    .mockRejectedValueOnce(new TypeError('offline'))
    .mockResolvedValueOnce(
      response(200, {
        status: 'ready',
        checks: { database: { status: 'ok' } },
      }),
    );
  vi.stubGlobal('fetch', fetchMock);
  const user = userEvent.setup();

  render(<HealthPage />);

  expect(await screen.findByRole('alert')).toHaveTextContent(
    '서버에 연결할 수 없습니다.',
  );
  await user.tab();
  expect(screen.getByRole('button', { name: '다시 확인' })).toHaveFocus();
  await user.keyboard('{Enter}');

  expect(await screen.findByText('준비 완료')).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(2);
});

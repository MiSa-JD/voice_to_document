import { Link } from 'react-router-dom';

export function NotFoundPage() {
  return (
    <main className="shell">
      <p className="eyebrow">404</p>
      <h1>페이지를 찾을 수 없습니다</h1>
      <p className="intro">요청한 주소를 확인해 주세요.</p>
      <Link className="button-link" to="/">
        서비스 상태로 돌아가기
      </Link>
    </main>
  );
}

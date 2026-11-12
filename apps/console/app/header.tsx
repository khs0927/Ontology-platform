import Link from "next/link";

export function Header({ email }: { email?: string | null }) {
  return (
    <header className="top">
      <strong>Sion Console</strong>
      <nav>
        <Link href="/">대시보드</Link>
        <Link href="/billing">구독</Link>
        {email ? <span className="muted">{email}</span> : null}
        <form action="/auth/signout" method="post">
          <button className="secondary" type="submit">로그아웃</button>
        </form>
      </nav>
    </header>
  );
}

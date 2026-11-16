import { LoginForm } from "./login-form";

export const metadata = { title: "로그인 · Sion Console" };

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ error?: string; next?: string }> }) {
  const { error, next } = await searchParams;
  return (
    <main>
      <h1>Sion Console 로그인</h1>
      <p className="muted">이메일로 받은 로그인 링크를 누르면 바로 들어옵니다. 비밀번호는 쓰지 않습니다.</p>
      {error ? <p className="warn">로그인 링크가 만료되었거나 잘못되었습니다. 다시 요청하세요.</p> : null}
      {next === "/invite" ? <p>로그인하면 받은 초대 화면으로 돌아갑니다.</p> : null}
      <LoginForm next={next === "/invite" ? "/invite" : undefined} />
    </main>
  );
}

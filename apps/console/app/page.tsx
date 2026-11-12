import { redirect } from "next/navigation";
import { Header } from "@/app/header";
import { sionApi, type Billing, type Me } from "@/lib/api";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

export default async function Dashboard() {
  const supabase = await createClient();
  const { data } = await supabase.auth.getClaims();
  const claims = data?.claims;
  if (!claims?.sub) redirect("/login");

  const [me, billing] = await Promise.all([sionApi<Me>("/api/v1/me"), sionApi<Billing>("/api/v1/billing/me")]);
  const email = typeof claims.email === "string" ? claims.email : null;

  return (
    <>
      <Header email={email} />
      <main>
        <h1>대시보드</h1>

        <section className="card">
          <h2>API 접근 권한</h2>
          {me.ok ? (
            <dl>
              <dt>사용자 ID</dt>
              <dd><code>{me.data.subject}</code></dd>
              <dt>권한(scope)</dt>
              <dd>{me.data.scopes.join(", ") || "없음"}</dd>
              <dt>프로젝트</dt>
              <dd>
                {me.data.projects === null
                  ? "전체"
                  : me.data.projects.length
                    ? me.data.projects.map((p) => <code key={p} style={{ display: "block" }}>{p}</code>)
                    : <span className="warn">아직 배정된 프로젝트가 없습니다. 관리자에게 요청하세요.</span>}
              </dd>
            </dl>
          ) : (
            <p className="warn">Sion API에서 계정을 확인하지 못했습니다: {me.error}</p>
          )}
        </section>

        <section className="card">
          <h2>구독</h2>
          {billing.ok ? (
            billing.data.active ? (
              <p className="ok">이용 중인 구독이 있습니다 ({billing.data.price_ids.join(", ")}).</p>
            ) : (
              <p>
                활성 구독이 없습니다. <a href="/billing">구독 시작하기</a>
              </p>
            )
          ) : (
            <p className="warn">구독 정보를 불러오지 못했습니다: {billing.error}</p>
          )}
        </section>
      </main>
    </>
  );
}

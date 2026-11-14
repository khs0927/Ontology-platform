import { redirect } from "next/navigation";
import { Header } from "@/app/header";
import { sionApi, type Billing } from "@/lib/api";
import { createClient } from "@/lib/supabase/server";
import { Checkout } from "./checkout";

export const dynamic = "force-dynamic";
export const metadata = { title: "구독 · Sion Console" };

export default async function BillingPage() {
  const supabase = await createClient();
  const { data } = await supabase.auth.getClaims();
  const claims = data?.claims;
  if (!claims?.sub) redirect("/login");
  const email = typeof claims.email === "string" ? claims.email : null;
  const billing = await sionApi<Billing>("/api/v1/billing/me");

  return (
    <>
      <Header email={email} />
      <main>
        <h1>구독</h1>
        <section className="card">
          <h2>현재 구독</h2>
          {!billing.ok ? (
            <p className="warn">구독 정보를 불러오지 못했습니다: {billing.error}</p>
          ) : billing.data.subscriptions.length === 0 ? (
            <p className="muted">아직 구독이 없습니다.</p>
          ) : (
            billing.data.subscriptions.map((s) => (
              <dl key={s.subscription_id} style={{ marginBottom: 12 }}>
                <dt>상태</dt>
                <dd className={s.active ? "ok" : "warn"}>{s.status}</dd>
                <dt>요금제</dt>
                <dd>{s.price_ids.join(", ")}</dd>
                <dt>현재 기간 종료</dt>
                <dd>{s.current_period_end ? new Date(s.current_period_end).toLocaleDateString("ko-KR") : "-"}</dd>
                {s.scheduled_change ? (
                  <>
                    <dt>예약된 변경</dt>
                    <dd>{s.scheduled_change}</dd>
                  </>
                ) : null}
              </dl>
            ))
          )}
        </section>
        {billing.ok && billing.data.active ? null : (
          <section className="card">
            <h2>구독 시작</h2>
            <p className="muted">결제, 세금계산, 영수증은 Paddle이 처리합니다. 결제 후 반영까지 몇 초 걸릴 수 있습니다.</p>
            <Checkout userId={claims.sub} email={email} />
          </section>
        )}
      </main>
    </>
  );
}

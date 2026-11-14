import { Header } from "@/app/header";
import { AcceptInvite } from "@/app/invite/accept";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";
export const metadata = { title: "프로젝트 초대 · Sion Console" };

/** Public page: the token stays in the URL fragment / this browser until a signed-in user accepts. */
export default async function InvitePage() {
  const supabase = await createClient();
  const { data } = await supabase.auth.getClaims();
  const claims = data?.claims;
  const email = typeof claims?.email === "string" ? claims.email : null;
  return (
    <>
      {claims?.sub ? <Header email={email} /> : null}
      <main>
        <h1>프로젝트 초대</h1>
        <section className="card">
          <AcceptInvite signedIn={Boolean(claims?.sub)} email={email} />
        </section>
      </main>
    </>
  );
}

import { redirect } from "next/navigation";
import { Header } from "@/app/header";
import { sionApi, withQuery, type LawSearch } from "@/lib/api";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";
export const metadata = { title: "법령 검색 · Sion Console" };

export default async function SearchPage({ searchParams }: { searchParams: Promise<{ q?: string; as_of?: string }> }) {
  const supabase = await createClient();
  const { data } = await supabase.auth.getClaims();
  const claims = data?.claims;
  if (!claims?.sub) redirect("/login");
  const email = typeof claims.email === "string" ? claims.email : null;

  const { q = "", as_of = "" } = await searchParams;
  const query = q.trim().slice(0, 500);
  const result = query ? await sionApi<LawSearch>(withQuery("/api/v1/law/search", { q: query, as_of, limit: 20 })) : null;

  return (
    <>
      <Header email={email} />
      <main>
        <h1>법령 검색</h1>
        <form className="card" method="get" style={{ display: "grid", gap: 10 }}>
          <label htmlFor="q">찾을 내용</label>
          <input id="q" name="q" defaultValue={query} placeholder="예: 건축물 높이 제한, 일조 등의 확보" maxLength={500} />
          <label htmlFor="as_of">기준일 (비우면 오늘)</label>
          <input id="as_of" name="as_of" type="date" defaultValue={as_of} style={{ maxWidth: 220 }} />
          <div>
            <button type="submit">검색</button>
          </div>
        </form>

        {result === null ? null : !result.ok ? (
          <p className="warn">검색하지 못했습니다: {result.error}</p>
        ) : result.data.results.length === 0 ? (
          <p className="muted">{result.data.as_of} 기준으로 맞는 조문이 없습니다.</p>
        ) : (
          <>
            <p className="muted">
              {result.data.as_of} 기준 {result.data.total}건 중 상위 {result.data.results.length}건
            </p>
            {result.data.results.map((hit) => (
              <article className="card" key={hit.id}>
                <h2>
                  {hit.citation}
                  {hit.title ? <span className="muted"> ({hit.title})</span> : null}
                </h2>
                <p style={{ whiteSpace: "pre-wrap", margin: "0 0 8px" }}>{hit.snippet}</p>
                <p className="muted" style={{ margin: 0 }}>
                  시행 {hit.effective_from}
                  {hit.source_url ? (
                    <>
                      {" · "}
                      <a href={hit.source_url} target="_blank" rel="noreferrer noopener">
                        원문
                      </a>
                    </>
                  ) : null}
                </p>
              </article>
            ))}
          </>
        )}
      </main>
    </>
  );
}

import { redirect } from "next/navigation";
import { Header } from "@/app/header";
import { sionApi, withQuery, type Graph, type Me } from "@/lib/api";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";
export const metadata = { title: "내 프로젝트 · Sion Console" };

const MAX_NODES = 200;
const STATE_LABEL: Record<string, string> = { unverified: "검토 전", machine_verified: "자동 검증", rejected: "반려" };

export default async function ProjectsPage({ searchParams }: { searchParams: Promise<{ project?: string }> }) {
  const supabase = await createClient();
  const { data } = await supabase.auth.getClaims();
  const claims = data?.claims;
  if (!claims?.sub) redirect("/login");
  const email = typeof claims.email === "string" ? claims.email : null;

  const me = await sionApi<Me>("/api/v1/me");
  const { project } = await searchParams;
  const projects = me.ok ? me.data.projects : null;
  const selected = project ?? (projects && projects.length ? projects[0] : undefined);
  const graph = selected
    ? await sionApi<Graph>(withQuery("/api/v1/graph", { project_id: selected, limit: MAX_NODES }))
    : null;

  const names = new Map<string, string>();
  if (graph?.ok) for (const node of graph.data.nodes) names.set(node.id, node.name);
  const projectNode = graph?.ok ? graph.data.nodes.find((n) => n.id === selected) : undefined;

  return (
    <>
      <Header email={email} />
      <main>
        <h1>내 프로젝트</h1>
        {!me.ok ? (
          <p className="warn">계정을 확인하지 못했습니다: {me.error}</p>
        ) : projects !== null && projects.length === 0 ? (
          <p className="warn">아직 배정된 프로젝트가 없습니다. 관리자에게 요청하세요.</p>
        ) : (
          <>
            {projects && projects.length > 1 ? (
              <nav className="card" style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
                {projects.map((id) => (
                  <a key={id} href={withQuery("/projects", { project: id })} aria-current={id === selected ? "page" : undefined}>
                    <code>{id.slice(0, 8)}</code>
                  </a>
                ))}
              </nav>
            ) : null}
            {!selected ? (
              <p className="muted">전체 접근 계정입니다. 주소에 ?project=&lt;프로젝트 ID&gt;를 붙여 프로젝트를 고르세요.</p>
            ) : !graph?.ok ? (
              <p className="warn">프로젝트를 불러오지 못했습니다: {graph?.error}</p>
            ) : (
              <>
                <section className="card">
                  <h2>{projectNode?.name ?? selected}</h2>
                  <p className="muted" style={{ margin: 0 }}>
                    항목 {graph.data.nodes.length}개 · 관계 {graph.data.edges.length}개
                    {graph.data.nodes.length >= MAX_NODES ? ` (처음 ${MAX_NODES}개만 표시)` : ""}
                  </p>
                </section>
                <section className="card">
                  <h2>항목</h2>
                  {graph.data.nodes.length === 0 ? (
                    <p className="muted">아직 항목이 없습니다.</p>
                  ) : (
                    <dl>
                      {graph.data.nodes.map((node) => (
                        <div key={node.id} style={{ display: "contents" }}>
                          <dt>{node.entity_type_id}</dt>
                          <dd>{node.name}</dd>
                        </div>
                      ))}
                    </dl>
                  )}
                </section>
                <section className="card">
                  <h2>관계</h2>
                  {graph.data.edges.length === 0 ? (
                    <p className="muted">아직 관계가 없습니다.</p>
                  ) : (
                    <ul style={{ margin: 0, paddingLeft: 18 }}>
                      {graph.data.edges.map((edge) => (
                        <li key={edge.id}>
                          {names.get(edge.source) ?? edge.source} <span className="muted">—{edge.type}→</span>{" "}
                          {names.get(edge.target) ?? edge.target}
                          {STATE_LABEL[edge.verification_state] ? (
                            <span className="muted"> ({STATE_LABEL[edge.verification_state]})</span>
                          ) : null}
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
              </>
            )}
          </>
        )}
      </main>
    </>
  );
}

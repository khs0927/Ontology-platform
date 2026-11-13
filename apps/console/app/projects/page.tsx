import { redirect } from "next/navigation";
import { Header } from "@/app/header";
import { editEntity, uploadDocument } from "@/app/projects/actions";
import { sionApi, UPLOAD_SUFFIXES, withQuery, type Graph, type Me, type ProjectDocuments } from "@/lib/api";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";
export const metadata = { title: "내 프로젝트 · Sion Console" };

const MAX_NODES = 200;
const STATE_LABEL: Record<string, string> = { unverified: "검토 전", machine_verified: "자동 검증", rejected: "반려" };
const NOTICES: Record<string, { text: string; ok?: boolean }> = {
  uploaded: { text: "문서를 올렸습니다. 추출된 항목은 검토 전 상태로 추가됩니다.", ok: true },
  upload_duplicate: { text: "이미 올린 문서와 같은 파일이라 새로 추가된 항목이 없습니다.", ok: true },
  upload_empty: { text: "올릴 파일을 고르세요." },
  upload_unsupported: { text: `지원하는 형식은 ${UPLOAD_SUFFIXES.join(", ")} 입니다.` },
  upload_too_large: { text: "파일이 너무 큽니다 (최대 25MB)." },
  upload_unreadable: { text: "파일은 받았지만 글자를 읽지 못했습니다. 스캔 PDF는 아직 지원하지 않습니다." },
  upload_forbidden: { text: "이 프로젝트에 문서를 올릴 권한이 없습니다." },
  upload_not_found: { text: "프로젝트를 찾지 못했습니다." },
  upload_failed: { text: "업로드에 실패했습니다. 잠시 뒤 다시 시도하세요." },
  edited: { text: "저장했습니다.", ok: true },
  edit_empty: { text: "이름은 비워 둘 수 없습니다." },
  edit_forbidden: { text: "이 항목을 수정할 권한이 없습니다." },
  edit_not_found: { text: "항목을 찾지 못했습니다." },
  edit_failed: { text: "저장에 실패했습니다. 잠시 뒤 다시 시도하세요." },
};

function formatBytes(bytes: number | null): string {
  if (bytes === null) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export default async function ProjectsPage({
  searchParams,
}: {
  searchParams: Promise<{ project?: string; notice?: string }>;
}) {
  const supabase = await createClient();
  const { data } = await supabase.auth.getClaims();
  const claims = data?.claims;
  if (!claims?.sub) redirect("/login");
  const email = typeof claims.email === "string" ? claims.email : null;

  const me = await sionApi<Me>("/api/v1/me");
  const { project, notice } = await searchParams;
  const projects = me.ok ? me.data.projects : null;
  const selected = project ?? (projects && projects.length ? projects[0] : undefined);
  const canWrite = me.ok && (me.data.scopes.includes("write:knowledge") || me.data.scopes.includes("*"));
  const [graph, documents] = selected
    ? await Promise.all([
        sionApi<Graph>(withQuery("/api/v1/graph", { project_id: selected, limit: MAX_NODES })),
        sionApi<ProjectDocuments>(`/api/v1/projects/${encodeURIComponent(selected)}/documents`),
      ])
    : [null, null];
  const message = notice ? NOTICES[notice] : undefined;

  const names = new Map<string, string>();
  if (graph?.ok) for (const node of graph.data.nodes) names.set(node.id, node.name);
  const projectNode = graph?.ok ? graph.data.nodes.find((n) => n.id === selected) : undefined;

  return (
    <>
      <Header email={email} />
      <main>
        <h1>내 프로젝트</h1>
        {message ? (
          <p className={message.ok ? "ok" : "warn"} role="status">
            {message.text}
          </p>
        ) : null}
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
                  <h2>문서</h2>
                  {canWrite ? (
                    <form action={uploadDocument} className="upload">
                      <input type="hidden" name="project" value={selected} />
                      <input type="file" name="file" required accept={UPLOAD_SUFFIXES.join(",")} aria-label="올릴 문서" />
                      <button type="submit">올리기</button>
                    </form>
                  ) : (
                    <p className="muted">
                      문서를 올리고 수정하려면 쓰기 권한이 필요합니다. <a href="/billing">요금제 보기</a>
                    </p>
                  )}
                  {!documents?.ok ? (
                    <p className="warn">문서 목록을 불러오지 못했습니다: {documents?.error}</p>
                  ) : documents.data.items.length === 0 ? (
                    <p className="muted">아직 올린 문서가 없습니다.</p>
                  ) : (
                    <ul className="docs">
                      {documents.data.items.map((doc) => (
                        <li key={doc.id}>
                          <strong>{doc.name}</strong>{" "}
                          <span className="muted">
                            {[doc.filename, formatBytes(doc.byte_size), doc.updated_at?.slice(0, 10)].filter(Boolean).join(" · ")}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
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
                          <dd>
                            {canWrite ? (
                              <details>
                                <summary>{node.name}</summary>
                                <form action={editEntity} className="stack edit">
                                  <input type="hidden" name="project" value={selected} />
                                  <input type="hidden" name="entity" value={node.id} />
                                  <label>
                                    이름
                                    <input name="name" defaultValue={node.name} required maxLength={500} />
                                  </label>
                                  <label>
                                    설명
                                    <textarea name="description" defaultValue={node.description ?? ""} rows={3} />
                                  </label>
                                  <button type="submit">저장</button>
                                </form>
                              </details>
                            ) : (
                              node.name
                            )}
                          </dd>
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

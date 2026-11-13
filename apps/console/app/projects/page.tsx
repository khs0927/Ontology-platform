import { redirect } from "next/navigation";
import { Header } from "@/app/header";
import { ROLE_LABELS } from "@/app/invite/labels";
import { editEntity, uploadDocument } from "@/app/projects/actions";
import { InviteForm } from "@/app/projects/invite-form";
import { changeRole, createProject, removeMember, revokeInvite } from "@/app/projects/member-actions";
import {
  sionApi,
  UPLOAD_SUFFIXES,
  withQuery,
  type Graph,
  type InviteList,
  type Me,
  type MemberList,
  type ProjectDocuments,
  type ProjectList,
} from "@/lib/api";
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
  project_created: { text: "프로젝트를 만들었습니다. 이제 문서를 올리고 팀원을 초대하세요.", ok: true },
  project_empty: { text: "프로젝트 이름을 입력하세요." },
  project_forbidden: { text: "프로젝트를 만들려면 쓰기 권한(유료 플랜)이 필요합니다." },
  project_conflict: { text: "만들 수 있는 프로젝트 수를 넘었습니다." },
  project_not_found: { text: "프로젝트를 만들지 못했습니다." },
  project_failed: { text: "프로젝트를 만들지 못했습니다. 잠시 뒤 다시 시도하세요." },
  invite_revoked: { text: "초대를 취소했습니다.", ok: true },
  role_changed: { text: "역할을 바꿨습니다.", ok: true },
  member_removed: { text: "멤버를 내보냈습니다.", ok: true },
  left: { text: "프로젝트에서 나왔습니다.", ok: true },
  member_forbidden: { text: "소유자만 할 수 있는 일입니다." },
  member_not_found: { text: "멤버나 초대를 찾지 못했습니다." },
  member_conflict: { text: "프로젝트에는 소유자가 한 명 이상 있어야 합니다." },
  member_failed: { text: "처리하지 못했습니다. 잠시 뒤 다시 시도하세요." },
};
const INVITE_STATE: Record<string, string> = { pending: "대기", accepted: "수락됨", revoked: "취소됨", expired: "만료" };

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

  const [me, list] = await Promise.all([sionApi<Me>("/api/v1/me"), sionApi<ProjectList>("/api/v1/projects")]);
  const { project, notice } = await searchParams;
  const projects = list.ok ? list.data.items : [];
  const selected = project ?? projects[0]?.id;
  const current = projects.find((p) => p.id === selected);
  const unrestricted = me.ok && me.data.projects === null;
  const hasWriteScope = me.ok && (me.data.scopes.includes("write:knowledge") || me.data.scopes.includes("*"));
  const canWrite = hasWriteScope && (current?.can_write ?? unrestricted);
  const isOwner = current?.role === "owner" || unrestricted;
  const [graph, documents, members, invites] = selected
    ? await Promise.all([
        sionApi<Graph>(withQuery("/api/v1/graph", { project_id: selected, limit: MAX_NODES })),
        sionApi<ProjectDocuments>(`/api/v1/projects/${encodeURIComponent(selected)}/documents`),
        sionApi<MemberList>(`/api/v1/projects/${encodeURIComponent(selected)}/members`),
        isOwner ? sionApi<InviteList>(`/api/v1/projects/${encodeURIComponent(selected)}/invites`) : Promise.resolve(null),
      ])
    : [null, null, null, null];
  const self = me.ok ? me.data.subject : null;
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
        {!me.ok || !list.ok ? (
          <p className="warn">계정을 확인하지 못했습니다: {me.ok ? (list.ok ? "" : list.error) : me.error}</p>
        ) : (
          <>
            <nav className="card switcher" aria-label="프로젝트 목록">
              {projects.map((item) => (
                <a
                  key={item.id}
                  href={withQuery("/projects", { project: item.id })}
                  aria-current={item.id === selected ? "page" : undefined}
                >
                  {item.name}
                  {item.role ? <span className="muted"> · {ROLE_LABELS[item.role]}</span> : null}
                </a>
              ))}
              {projects.length === 0 ? (
                <span className="muted">아직 프로젝트가 없습니다. 새로 만들거나 받은 초대 링크를 여세요.</span>
              ) : null}
              {hasWriteScope ? (
                <form action={createProject} className="new-project">
                  <input name="name" required maxLength={200} placeholder="새 프로젝트 이름" aria-label="새 프로젝트 이름" />
                  <button type="submit">만들기</button>
                </form>
              ) : (
                <span className="muted">
                  프로젝트를 만들려면 <a href="/billing">유료 플랜</a>이 필요합니다.
                </span>
              )}
            </nav>
            {!selected ? null : !graph?.ok ? (
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
                      {current && !current.can_write
                        ? "보기 전용 멤버라 문서를 올리거나 수정할 수 없습니다."
                        : <>문서를 올리고 수정하려면 쓰기 권한이 필요합니다. <a href="/billing">요금제 보기</a></>}
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
                  <h2>멤버</h2>
                  {!members?.ok ? (
                    <p className="warn">멤버를 불러오지 못했습니다: {members?.error}</p>
                  ) : (
                    <ul className="members">
                      {members.data.items.map((member) => (
                        <li key={member.subject}>
                          <span>
                            {member.email ?? <code>{member.subject.slice(0, 8)}</code>}
                            {member.subject === self ? <span className="muted"> (나)</span> : null}
                          </span>
                          {isOwner && member.subject !== self ? (
                            <span className="member-actions">
                              <form action={changeRole}>
                                <input type="hidden" name="project" value={selected} />
                                <input type="hidden" name="subject" value={member.subject} />
                                <select name="role" defaultValue={member.role} aria-label="역할">
                                  <option value="owner">소유자</option>
                                  <option value="editor">편집자</option>
                                  <option value="viewer">보기 전용</option>
                                </select>
                                <button type="submit" className="secondary">변경</button>
                              </form>
                              <form action={removeMember}>
                                <input type="hidden" name="project" value={selected} />
                                <input type="hidden" name="subject" value={member.subject} />
                                <button type="submit" className="secondary">내보내기</button>
                              </form>
                            </span>
                          ) : (
                            <span className="member-actions">
                              <span className="muted">{ROLE_LABELS[member.role]}</span>
                              {member.subject === self ? (
                                <form action={removeMember}>
                                  <input type="hidden" name="project" value={selected} />
                                  <input type="hidden" name="subject" value={member.subject} />
                                  <input type="hidden" name="leaving" value="1" />
                                  <button type="submit" className="secondary">나가기</button>
                                </form>
                              ) : null}
                            </span>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}
                  {isOwner ? (
                    <>
                      <h3>초대</h3>
                      <InviteForm project={selected} />
                      {invites?.ok && invites.data.items.length ? (
                        <ul className="members">
                          {invites.data.items.map((invite) => (
                            <li key={invite.id}>
                              <span>
                                {invite.email ?? "링크를 받은 누구나"} · {ROLE_LABELS[invite.role]}
                                <span className="muted">
                                  {" "}
                                  · {INVITE_STATE[invite.state]} · {invite.expires_at.slice(0, 10)}까지
                                </span>
                              </span>
                              {invite.state === "pending" ? (
                                <form action={revokeInvite}>
                                  <input type="hidden" name="project" value={selected} />
                                  <input type="hidden" name="invite" value={invite.id} />
                                  <button type="submit" className="secondary">취소</button>
                                </form>
                              ) : null}
                            </li>
                          ))}
                        </ul>
                      ) : null}
                    </>
                  ) : null}
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

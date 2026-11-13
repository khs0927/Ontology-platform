"use server";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { sionApi, withQuery } from "@/lib/api";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const ROLES = new Set(["owner", "editor", "viewer"]);

function back(project: string | null, notice: string): never {
  revalidatePath("/projects");
  redirect(withQuery("/projects", { project: project ?? undefined, notice }));
}

function code(status: number): string {
  if (status === 403) return "forbidden";
  if (status === 404) return "not_found";
  if (status === 409) return "conflict";
  return "failed";
}

/** Create a project owned by the signed-in user and open it. */
export async function createProject(formData: FormData) {
  const name = String(formData.get("name") ?? "").trim().slice(0, 200);
  if (!name) back(null, "project_empty");
  const result = await sionApi<{ id: string }>("/api/v1/projects", {
    method: "POST",
    body: JSON.stringify({ name }),
    contentType: "application/json",
  });
  if (!result.ok) back(null, `project_${code(result.status)}`);
  back(result.data.id, "project_created");
}

export type InviteState = { token?: string; role?: string; error?: string };

/** Create a one-time invitation. The token goes back to the owner's browser only, never into a URL. */
export async function createInvite(_prev: InviteState, formData: FormData): Promise<InviteState> {
  const project = String(formData.get("project") ?? "");
  const role = String(formData.get("role") ?? "editor");
  const email = String(formData.get("email") ?? "").trim();
  const days = Number(formData.get("days") ?? 7);
  if (!UUID.test(project) || (role !== "editor" && role !== "viewer")) return { error: "잘못된 요청입니다." };
  const result = await sionApi<{ token: string; role: string }>(`/api/v1/projects/${project}/invites`, {
    method: "POST",
    body: JSON.stringify({ role, email: email || null, expires_in_days: Number.isInteger(days) ? Math.min(Math.max(days, 1), 30) : 7 }),
    contentType: "application/json",
  });
  revalidatePath("/projects");
  if (!result.ok) return { error: result.status === 403 ? "소유자만 초대할 수 있습니다." : "초대 링크를 만들지 못했습니다." };
  return { token: result.data.token, role: result.data.role };
}

export async function revokeInvite(formData: FormData) {
  const project = String(formData.get("project") ?? "");
  const invite = String(formData.get("invite") ?? "");
  if (!UUID.test(project) || !UUID.test(invite)) redirect("/projects");
  const result = await sionApi(`/api/v1/projects/${project}/invites/${invite}`, { method: "DELETE" });
  back(project, result.ok ? "invite_revoked" : `member_${code(result.status)}`);
}

export async function changeRole(formData: FormData) {
  const project = String(formData.get("project") ?? "");
  const subject = String(formData.get("subject") ?? "");
  const role = String(formData.get("role") ?? "");
  if (!UUID.test(project) || !subject || !ROLES.has(role)) redirect("/projects");
  const result = await sionApi(`/api/v1/projects/${project}/members/${encodeURIComponent(subject)}`, {
    method: "PATCH",
    body: JSON.stringify({ role }),
    contentType: "application/json",
  });
  back(project, result.ok ? "role_changed" : `member_${code(result.status)}`);
}

/** Remove a member (owners) or leave the project (the member themselves). */
export async function removeMember(formData: FormData) {
  const project = String(formData.get("project") ?? "");
  const subject = String(formData.get("subject") ?? "");
  const leaving = formData.get("leaving") === "1";
  if (!UUID.test(project) || !subject) redirect("/projects");
  const result = await sionApi(`/api/v1/projects/${project}/members/${encodeURIComponent(subject)}`, { method: "DELETE" });
  if (result.ok && leaving) back(null, "left");
  back(project, result.ok ? "member_removed" : `member_${code(result.status)}`);
}

export type AcceptState = { project?: string; name?: string | null; role?: string; error?: string };

export async function acceptInvite(_prev: AcceptState, formData: FormData): Promise<AcceptState> {
  const token = String(formData.get("token") ?? "");
  if (token.length < 20 || token.length > 200) return { error: "초대 링크가 올바르지 않습니다." };
  const result = await sionApi<{ project_id: string; name: string | null; role: string }>("/api/v1/invites/accept", {
    method: "POST",
    body: JSON.stringify({ token }),
    contentType: "application/json",
  });
  if (!result.ok) {
    return {
      error:
        result.status === 404
          ? "초대가 만료됐거나 이미 사용됐습니다. 이메일이 지정된 초대라면 그 이메일로 로그인했는지 확인하세요."
          : "초대를 수락하지 못했습니다. 잠시 뒤 다시 시도하세요.",
    };
  }
  revalidatePath("/projects");
  return { project: result.data.project_id, name: result.data.name, role: result.data.role };
}

"use server";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { sionApi, UPLOAD_MAX_BYTES, UPLOAD_SUFFIXES, withQuery, type UploadResult } from "@/lib/api";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function back(project: string, params: Record<string, string | number | undefined>): never {
  revalidatePath("/projects");
  redirect(withQuery("/projects", { project, ...params }));
}

function failure(status: number): string {
  if (status === 403) return "forbidden";
  if (status === 404) return "not_found";
  if (status === 413) return "too_large";
  if (status === 415) return "unsupported";
  return "failed";
}

/** Upload one document into a project; the API checks the project ACL and parses the file. */
export async function uploadDocument(formData: FormData) {
  const project = String(formData.get("project") ?? "");
  if (!UUID.test(project)) redirect("/projects");
  const file = formData.get("file");
  if (!(file instanceof File) || file.size === 0) back(project, { notice: "upload_empty" });
  const suffix = file.name.includes(".") ? file.name.slice(file.name.lastIndexOf(".")).toLowerCase() : "";
  if (!UPLOAD_SUFFIXES.includes(suffix)) back(project, { notice: "upload_unsupported" });
  if (file.size > UPLOAD_MAX_BYTES) back(project, { notice: "upload_too_large" });

  const result = await sionApi<UploadResult>(
    withQuery(`/api/v1/projects/${project}/documents`, { filename: file.name }),
    { method: "POST", body: await file.arrayBuffer(), contentType: "application/octet-stream" },
  );
  if (!result.ok) back(project, { notice: `upload_${failure(result.status)}` });
  if (result.data.skipped.length) back(project, { notice: "upload_unreadable" });
  back(project, { notice: result.data.created_nodes ? "uploaded" : "upload_duplicate", n: result.data.created_nodes });
}

/** Rename an entity or change its description; the API keeps it inside the caller's projects. */
export async function editEntity(formData: FormData) {
  const project = String(formData.get("project") ?? "");
  const entity = String(formData.get("entity") ?? "");
  if (!UUID.test(project) || !UUID.test(entity)) redirect("/projects");
  const name = String(formData.get("name") ?? "").trim().slice(0, 500);
  const description = String(formData.get("description") ?? "").trim();
  if (!name) back(project, { notice: "edit_empty" });
  const result = await sionApi(`/api/v1/entities/${entity}`, {
    method: "PATCH",
    body: JSON.stringify({ name, description: description || null }),
    contentType: "application/json",
  });
  back(project, { notice: result.ok ? "edited" : `edit_${failure(result.status)}` });
}

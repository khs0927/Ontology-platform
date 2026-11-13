import "server-only";
import { createClient } from "@/lib/supabase/server";

export type Me = { kind: string; subject: string | null; scopes: string[]; projects: string[] | null };
export type Subscription = {
  subscription_id: string;
  status: string;
  active: boolean;
  price_ids: string[];
  current_period_end: string | null;
  scheduled_change: string | null;
};
export type Billing = { subject: string; active: boolean; price_ids: string[]; subscriptions: Subscription[] };

export type ApiResult<T> = { ok: true; data: T } | { ok: false; status: number; error: string };

/** Call the Sion API with the signed-in user's access token. Server-side only. */
export async function sionApi<T>(path: string): Promise<ApiResult<T>> {
  const base = process.env.SION_API_URL;
  if (!base) return { ok: false, status: 0, error: "SION_API_URL is not set" };
  const supabase = await createClient();
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  if (!token) return { ok: false, status: 401, error: "not signed in" };
  try {
    const response = await fetch(new URL(path, base), {
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
      cache: "no-store",
    });
    if (!response.ok) {
      const body = (await response.json().catch(() => ({}))) as { detail?: unknown };
      return { ok: false, status: response.status, error: typeof body.detail === "string" ? body.detail : response.statusText };
    }
    return { ok: true, data: (await response.json()) as T };
  } catch {
    return { ok: false, status: 0, error: "Sion API is unreachable" };
  }
}

export type LawHit = {
  id: string;
  law_name: string;
  article_label: string;
  title: string | null;
  snippet: string;
  citation: string;
  effective_from: string;
  source_url: string | null;
  score: number;
};
export type LawSearch = { query: string; as_of: string; total: number; results: LawHit[] };

export type Entity = {
  id: string;
  name: string;
  entity_type_id: string;
  category: string | null;
  description: string | null;
};
export type GraphEdge = { id: string; source: string; target: string; type: string; verification_state: string };
export type Graph = { nodes: Entity[]; edges: GraphEdge[] };

export function withQuery(path: string, params: Record<string, string | number | undefined>): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") query.set(key, String(value));
  }
  const text = query.toString();
  return text ? `${path}?${text}` : path;
}

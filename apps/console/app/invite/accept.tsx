"use client";
import Link from "next/link";
import { useActionState, useEffect, useState } from "react";
import { acceptInvite, type AcceptState } from "@/app/projects/member-actions";
import { ROLE_LABELS } from "@/app/invite/labels";

const KEY = "sion.pendingInvite";

function readToken(): string {
  const hash = new URLSearchParams(window.location.hash.slice(1)).get("token");
  if (hash) {
    // Keep it across the sign-in round trip, then drop it from the address bar.
    try {
      window.localStorage.setItem(KEY, hash);
    } catch {}
    window.history.replaceState(null, "", window.location.pathname);
    return hash;
  }
  try {
    return window.localStorage.getItem(KEY) ?? "";
  } catch {
    return "";
  }
}

export function AcceptInvite({ signedIn, email }: { signedIn: boolean; email: string | null }) {
  const [token, setToken] = useState<string | null>(null);
  const [state, action, pending] = useActionState<AcceptState, FormData>(acceptInvite, {});

  useEffect(() => setToken(readToken()), []);
  useEffect(() => {
    if (state.project) {
      try {
        window.localStorage.removeItem(KEY);
      } catch {}
    }
  }, [state.project]);

  if (token === null) return <p className="muted">초대 확인 중…</p>;
  if (!token) return <p className="warn">초대 링크가 없습니다. 받은 링크 전체를 주소창에 붙여 넣으세요.</p>;
  if (!signedIn) {
    return (
      <>
        <p>프로젝트에 참여하려면 먼저 로그인하세요. 로그인 후 이 화면으로 돌아옵니다.</p>
        <Link className="button" href="/login?next=/invite">로그인하기</Link>
      </>
    );
  }
  if (state.project) {
    return (
      <>
        <p className="ok" role="status">
          {state.name ?? "프로젝트"}에 {ROLE_LABELS[state.role ?? ""] ?? state.role}(으)로 참여했습니다.
        </p>
        <Link className="button" href={`/projects?project=${state.project}`}>프로젝트 열기</Link>
      </>
    );
  }
  return (
    <form action={action} className="stack">
      <input type="hidden" name="token" value={token} />
      <p style={{ margin: 0 }}>
        <strong>{email ?? "현재 계정"}</strong>(으)로 초대를 수락합니다.
      </p>
      <button type="submit" disabled={pending}>{pending ? "참여하는 중…" : "초대 수락"}</button>
      {state.error ? <p className="warn" role="status">{state.error}</p> : null}
    </form>
  );
}

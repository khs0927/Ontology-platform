"use client";
import { useActionState, useState } from "react";
import { createInvite, type InviteState } from "@/app/projects/member-actions";

export function InviteForm({ project }: { project: string }) {
  const [state, action, pending] = useActionState<InviteState, FormData>(createInvite, {});
  const [copied, setCopied] = useState(false);
  // The token lives only in this page's memory; the link carries it in the #fragment, which
  // browsers never send to a server.
  const link = state.token ? `${window.location.origin}/invite#token=${state.token}` : "";

  return (
    <div>
      <form action={action} className="invite">
        <input type="hidden" name="project" value={project} />
        <label>
          역할
          <select name="role" defaultValue="editor">
            <option value="editor">편집자 (읽기·쓰기)</option>
            <option value="viewer">보기 전용</option>
          </select>
        </label>
        <label>
          받는 사람 이메일 (선택)
          <input type="email" name="email" placeholder="지정하면 이 이메일로만 수락" />
        </label>
        <label>
          유효 기간
          <select name="days" defaultValue="7">
            <option value="1">1일</option>
            <option value="7">7일</option>
            <option value="30">30일</option>
          </select>
        </label>
        <button type="submit" disabled={pending}>{pending ? "만드는 중…" : "초대 링크 만들기"}</button>
      </form>
      {state.error ? <p className="warn" role="status">{state.error}</p> : null}
      {link ? (
        <div className="invite-link" role="status">
          <p className="ok" style={{ margin: "8px 0 4px" }}>
            초대 링크를 만들었습니다. 한 번만 보여 드리니 지금 복사해 전달하세요. 한 사람만 쓸 수 있습니다.
          </p>
          <input readOnly value={link} aria-label="초대 링크" onFocus={(e) => e.currentTarget.select()} />
          <button
            type="button"
            className="secondary"
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(link);
                setCopied(true);
              } catch {
                setCopied(false);
              }
            }}
          >
            {copied ? "복사했습니다" : "복사"}
          </button>
        </div>
      ) : null}
    </div>
  );
}

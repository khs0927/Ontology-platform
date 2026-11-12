"use client";
import { useState } from "react";
import { createClient } from "@/lib/supabase/client";

export function LoginForm() {
  const [email, setEmail] = useState("");
  const [state, setState] = useState<"idle" | "sending" | "sent" | "error">("idle");
  const [message, setMessage] = useState("");

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setState("sending");
    const supabase = createClient();
    const { error } = await supabase.auth.signInWithOtp({
      email,
      options: { emailRedirectTo: `${window.location.origin}/auth/callback` },
    });
    if (error) {
      setState("error");
      setMessage(error.message);
    } else {
      setState("sent");
    }
  }

  if (state === "sent") {
    return <p className="ok">{email} 로 로그인 링크를 보냈습니다. 메일함을 확인하세요.</p>;
  }
  return (
    <form className="stack" onSubmit={onSubmit}>
      <label htmlFor="email">이메일</label>
      <input id="email" type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
      <button type="submit" disabled={state === "sending"}>
        {state === "sending" ? "보내는 중…" : "로그인 링크 받기"}
      </button>
      {state === "error" ? <p className="warn">{message}</p> : null}
    </form>
  );
}

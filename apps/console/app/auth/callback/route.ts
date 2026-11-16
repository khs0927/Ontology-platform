import { NextResponse, type NextRequest } from "next/server";
import { createClient } from "@/lib/supabase/server";

/** PKCE callback for the magic link: exchange the one-time code for a session cookie. */
export async function GET(request: NextRequest) {
  const code = request.nextUrl.searchParams.get("code");
  if (code) {
    const supabase = await createClient();
    const { error } = await supabase.auth.exchangeCodeForSession(code);
    // Only known in-app destinations, so the link cannot be turned into an open redirect.
    const next = request.nextUrl.searchParams.get("next") === "/invite" ? "/invite" : "/";
    if (!error) return NextResponse.redirect(new URL(next, request.url));
  }
  return NextResponse.redirect(new URL("/login?error=callback", request.url));
}

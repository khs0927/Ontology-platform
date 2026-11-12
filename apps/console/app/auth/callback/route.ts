import { NextResponse, type NextRequest } from "next/server";
import { createClient } from "@/lib/supabase/server";

/** PKCE callback for the magic link: exchange the one-time code for a session cookie. */
export async function GET(request: NextRequest) {
  const code = request.nextUrl.searchParams.get("code");
  if (code) {
    const supabase = await createClient();
    const { error } = await supabase.auth.exchangeCodeForSession(code);
    if (!error) return NextResponse.redirect(new URL("/", request.url));
  }
  return NextResponse.redirect(new URL("/login?error=callback", request.url));
}

"use client";
import { createBrowserClient } from "@supabase/ssr";

export function createClient() {
  // Literal access so Next inlines the public values into the browser bundle.
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY!,
  );
}

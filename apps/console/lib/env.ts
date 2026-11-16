function required(name: string, value: string | undefined): string {
  if (!value) throw new Error(`${name} is not set (see apps/console/env.example)`);
  return value;
}

// NEXT_PUBLIC_* values must be read with literal property access so Next can inline them.
export const supabaseUrl = () => required("NEXT_PUBLIC_SUPABASE_URL", process.env.NEXT_PUBLIC_SUPABASE_URL);
export const supabaseKey = () =>
  required("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY", process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY);

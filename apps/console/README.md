# Sion Console (hosted mode)

Next.js 16 web app for the hosted Sion service: Supabase magic-link sign-in, an account dashboard
backed by the Sion API, and Paddle checkout. Self-hosted installs do not need it.

```bash
cd apps/console
cp env.example .env.local   # fill in Supabase, Sion API and Paddle values
npm ci
npm run dev                  # http://localhost:3000
```

The Sion API must run with `SION_API_AUTH_MODE=bearer` (or `local-or-bearer`) and
`SION_OIDC_ISSUER=https://<project-ref>.supabase.co/auth/v1`; see [`docs/SAAS.md`](../../docs/SAAS.md).

How it fits together

- `proxy.ts` (Next 16's replacement for `middleware.ts`) refreshes the Supabase session cookie and
  verifies it with `getClaims()` (JWKS signature check), sending signed-out visitors to `/login`.
- Server components call the Sion API from the server with the user's access token
  (`lib/api.ts`); the browser never talks to the API directly and no API secret exists here.
- `/projects` lists the entities and relations of the user's projects (`/api/v1/graph?project_id=`),
  and `/search` searches published law text (`/api/v1/law/search`, with an optional 기준일). Both
  need the project-scoped API from phase 8a.
- `/billing` opens Paddle checkout with `customData.sion_user_id`; the API's Paddle webhook links
  the subscription to the user. The page re-reads entitlements after `checkout.completed`.
- Supabase projects must use asymmetric JWT signing keys; the API refuses HS256 tokens.

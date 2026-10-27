#!/usr/bin/env node

import { readFile } from "node:fs/promises";
import { execFile } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);
const inputPath = process.argv[2];
if (!inputPath) {
  console.error("Usage: node jev.mjs <request.json>");
  process.exit(2);
}

const skillDirectory = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const accountRoot = resolve(skillDirectory, "../../..");
// Windows only: optional DPAPI-encrypted TypeSafe key (Aside layout). Override with JEV_TYPESAFE_DPAPI_FILE.
const encryptedFallbackPath = process.env.JEV_TYPESAFE_DPAPI_FILE || resolve(accountRoot, "secrets", "jev-typesafe.dpapi");
const openCodeKey = process.env.OPENCODE_API_KEY?.trim() || null;

const request = JSON.parse(await readFile(inputPath, "utf8"));
if (!request || request.state === undefined || !request.questions || typeof request.questions !== "object") {
  console.error("The request must contain state and questions.");
  process.exit(4);
}

async function loadTypeSafeFallbackKey() {
  const environmentKey = process.env.TYPESAFE_API_KEY?.trim();
  if (environmentKey) return environmentKey;
  if (process.platform !== "win32") return null;

  try {
    const encrypted = (await readFile(encryptedFallbackPath, "utf8")).trim();
    if (!encrypted) return null;
    const decryptScript = [
      "$ErrorActionPreference = 'Stop'",
      // PowerShell 7 does not resolve [Security.Cryptography.ProtectedData]
      // until the assembly is loaded; without this the TypeSafe fallback dies
      // with TypeNotFound instead of returning a key.
      "Add-Type -AssemblyName System.Security",
      "$bytes = [Convert]::FromBase64String($env:JEV_ENCRYPTED_KEY)",
      "$plain = [Security.Cryptography.ProtectedData]::Unprotect($bytes, $null, [Security.Cryptography.DataProtectionScope]::CurrentUser)",
      "[Text.Encoding]::UTF8.GetString($plain)",
    ].join("; ");
    const { stdout } = await execFileAsync(
      "powershell.exe",
      ["-NoProfile", "-NonInteractive", "-Command", decryptScript],
      { env: { ...process.env, JEV_ENCRYPTED_KEY: encrypted }, windowsHide: true, maxBuffer: 1024 * 1024 },
    );
    return stdout.trim() || null;
  } catch {
    return null;
  }
}

async function invoke({ provider, url, model, apiKey }) {
  const headers = { "Content-Type": "application/json" };
  if (apiKey) headers.Authorization = `Bearer ${apiKey}`;

  try {
    const response = await fetch(url, {
      method: "POST",
      headers,
      body: JSON.stringify({ ...request, model }),
      signal: AbortSignal.timeout(120000),
    });

    const text = await response.text();
    let body;
    try {
      body = JSON.parse(text);
    } catch {
      body = { raw: text };
    }

    return { ok: response.ok, provider, endpoint: url, model, status: response.status, body };
  } catch (error) {
    return {
      ok: false,
      provider,
      endpoint: url,
      model,
      networkError: true,
      error: { name: error?.name || "Error", message: error?.message || "Network request failed" },
    };
  }
}

// Server-side error types the endpoint reports in the body.
//
// The free route can report an upstream outage as HTTP 422 with
// `type: "server_error"` in the body rather than a 5xx. Observed live, not
// theorized: with the free model down the endpoint answers 422 and
// "Upstream request failed: Endpoint is unavailable." Treating 422 purely as a
// request error would refuse the TypeSafe fallback at exactly the moment it is
// needed, so the body is consulted as the stronger fault signal.
const SERVER_ERROR_TYPES = new Set(["server_error", "api_error", "overloaded_error"]);

function isServerErrorResponse(body) {
  if (!body || typeof body !== "object") return false;
  // The endpoint nests the payload one or two levels deep depending on the
  // gateway in front of it, so check each level rather than one fixed path.
  let cursor = body;
  for (let depth = 0; depth < 3; depth += 1) {
    if (!cursor || typeof cursor !== "object") return false;
    if (typeof cursor.type === "string" && SERVER_ERROR_TYPES.has(cursor.type)) return true;
    cursor = cursor.error;
  }
  return false;
}

function canUseFallback(result) {
  if (result.networkError) return true;
  if (isServerErrorResponse(result.body)) return true;
  return [401, 403, 404, 408, 425, 429].includes(result.status) || result.status >= 500;
}

function emitError(result) {
  const detail = result.networkError
    ? { error: result.error }
    : { status: result.status, error: result.body };
  console.error(JSON.stringify({ provider: result.provider, endpoint: result.endpoint, model: result.model, ...detail }, null, 2));
}

const freeResult = await invoke({
  provider: "opencode-zen-free",
  url: "https://opencode.ai/zen/v1/systemone",
  model: "jev-1.13-free",
  apiKey: openCodeKey,
});

if (freeResult.ok) {
  console.log(JSON.stringify({
    provider: freeResult.provider,
    endpoint: freeResult.endpoint,
    requestedModel: freeResult.model,
    result: freeResult.body,
  }, null, 2));
  process.exit(0);
}

if (!canUseFallback(freeResult)) {
  emitError(freeResult);
  process.exit(5);
}

const typeSafeKey = await loadTypeSafeFallbackKey();
if (!typeSafeKey) {
  emitError(freeResult);
  console.error(JSON.stringify({ fallbackAvailable: false, reason: "No TypeSafe fallback key is configured." }));
  process.exit(5);
}

const fallbackResult = await invoke({
  provider: "typesafe",
  url: "https://api.typesafe.ai/v1/systemone",
  model: "jev-1.13.0",
  apiKey: typeSafeKey,
});

if (!fallbackResult.ok) {
  emitError(freeResult);
  emitError(fallbackResult);
  process.exit(5);
}

console.log(JSON.stringify({
  provider: fallbackResult.provider,
  endpoint: fallbackResult.endpoint,
  requestedModel: fallbackResult.model,
  fallbackUsed: true,
  result: fallbackResult.body,
}, null, 2));

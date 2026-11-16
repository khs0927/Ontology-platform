# Remote MCP server (knowledge core)

`sion-mcp` serves the knowledge core to MCP clients: Claude, ChatGPT connectors and deep research,
Cursor, and others. It runs over **stateless Streamable HTTP**. Each request is a self-contained
JSON-RPC call answered with JSON, with no session id and no server-side state. One process can
therefore sit behind any load balancer and be scaled horizontally. It is built on the official
Python SDK (`mcp` 2.3, `MCPServer`), and that SDK accepts both:
- the 2026-07-28 per-request protocol envelope (`MCP-Protocol-Version`, `Mcp-Method` headers and
  `params._meta`);
- the older `initialize` handshake.

The server is separate from the local CAD/AEC MCP servers in [`docs/mcp/`](mcp/README.md).

```bash
pip install -e '.[mcp]'
sion-mcp                                   # http://127.0.0.1:8765/mcp, loopback only
# remote: bearer tokens are required before binding beyond loopback
export SION_API_AUTH_MODE=bearer
export SION_API_TOKENS_JSON='{"<token of 16+ chars>": ["read:knowledge"]}'
export SION_MCP_PUBLIC_URL=https://kb.example.com          # used in links and resource metadata
sion-mcp --host 0.0.0.0 --port 8765                        # put TLS in front (reverse proxy)
```

The server reads the same database as the API (`SION_DATABASE_URL`).

## Tools

Every tool is read-only and annotated `readOnlyHint`.

| Tool | Arguments | Returns |
|---|---|---|
| `search` | `query`, `limit` | `{results: [{id, title, url}]}`: law articles (hybrid search) and graph entities. This is the ChatGPT connector / deep-research contract. |
| `fetch` | `id` (`law:<law_id>:<article>` or `entity:<stable_key>`) | `{id, title, text, url, metadata}` |
| `law_search` | `query`, `law`, `as_of`, `limit` | hybrid search results with `channels` and citations |
| `law_article` | `law_id`, `article` (`61`, `61-2` or `제61조의2`), `as_of` | the version in force on `as_of` |
| `law_refs` | `law_id`, `article`, `as_of` | outgoing and incoming citations |
| `get_entity` | `key_or_name` | entity with aliases |
| `neighbors` | `key_or_name`, `relation_type`, `include_candidates`, `limit` | relations. Review candidates are hidden unless asked for, and always flagged. |
| `evidence_for` | `relation_id` | source URI, locator, excerpt, extractor and model of each evidence row |

A bad argument, such as an unknown id or no article in force on that date, comes back as a tool
error with the reason. The server instructions tell models to cite `citation` and `content_hash`,
and that search results are not legal conclusions.

## Authentication

- `SION_API_AUTH_MODE=bearer`: a request needs a token from `SION_API_TOKENS_JSON` with the
  `read:knowledge` scope (or `*`). **Project-restricted tokens are refused**, because these tools
  are not project-scoped.
- `local-only` (the default): only loopback requests with a localhost `Host` header are served,
  using the same rule as the API. `sion-mcp` will not bind beyond loopback in this mode.
- `local-or-bearer`: either of the above.
- A refused request gets `401` with a `WWW-Authenticate: Bearer resource_metadata="…"` challenge.
  `GET /.well-known/oauth-protected-resource` serves RFC 9728 metadata. When
  `SION_MCP_AUTHORIZATION_SERVER` is set, the metadata lists it under `authorization_servers`, so
  OAuth clients can find where to get a token.

Static bearer tokens fit private deployments and agents. ChatGPT and Claude connectors expect
OAuth with Client ID Metadata Documents (CIMD), as in the 2026-07 specification. Verifying tokens
issued by that authorization server (for example Supabase Auth or Better Auth) belongs to the
SaaS phase (upgrade phase 7). Until then, front the server with a gateway that exchanges OAuth for
a bearer token, or use it from clients that accept a static header.

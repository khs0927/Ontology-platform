# Jev 1.13 source map

## Official model and API

- OpenCode Zen documentation: https://opencode.ai/docs/zen
  - Free model ID: `jev-1.13-free`
  - Endpoint: `POST https://opencode.ai/zen/v1/systemone`
  - It is advertised as free for a limited time.
  - At installation time, the tested endpoint also accepted an anonymous System One request without an `Authorization` header. This may change, so the helper reports 401/403 clearly and supports authenticated keys.
- TypeSafe documentation: https://docs.typesafe.ai/
- TypeSafe models: https://docs.typesafe.ai/models
  - Pinned model: `jev-1.13.0`
  - Endpoint: `POST https://api.typesafe.ai/v1/systemone`
  - 64k combined request context, with 32k for state plus the longest question.
  - Text input only; Jev returns structured decisions, not generated prose.

## Official open-source repositories

- Agent skill, MIT: https://github.com/typesafe-ai/skills
- TypeScript/JavaScript SDK, MIT: https://github.com/typesafe-ai/typesafe-sdk-js
- Python SDK, MIT: https://github.com/typesafe-ai/typesafe-sdk-python
- Open-source alternative using open-weight models: https://github.com/ikermoel/open-alternative-jev

## Important boundary

The repositories above are official client, workflow, and skill code. Jev itself is not published as open weights or an open inference implementation. An open-source alternative can reproduce the System One decision layer, but it is not the same hosted model and should not be described as TypeSafe Jev 1.13.

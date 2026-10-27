#!/usr/bin/env node
// jev-mcp-server.mjs — Stdio MCP server exposing Jev 1.3 Free (OpenCode Zen) to OpenCode & Antigravity.
// Implements full TypeSafe Jev System 1 open-source tool suite:
// - jev_decide: general choice / score / noul bounded judgment
// - jev_noul: single proposition calibrated truth probability (0.0 to 1.0)
// - jev_verify: claim verification against evidence context
// - jev_screen: input & content safety screening (allow, flag, deny)
// - jev_classify: categorical assignment of items/context
// - jev_rerank: score and rank candidate options against instructions
// - jev_tool_route: routing tool calls or execution branch strategies

import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import readline from "node:readline";

const FREE = { endpoint: "https://opencode.ai/zen/v1/systemone", model: "jev-1.13-free" };
const DIRECT = { endpoint: "https://api.typesafe.ai/v1/systemone", model: "jev-1.13.0" };

function readKey() {
  if (process.env.JEV_API_KEY) return process.env.JEV_API_KEY;
  try {
    // JEV_ENV_FILE overrides the default dotenv location (~/aside-gpt/.env).
    const envFile = process.env.JEV_ENV_FILE || join(homedir(), "aside-gpt", ".env");
    const line = readFileSync(envFile, "utf8")
      .split(/\r?\n/)
      .find((l) => l.startsWith("JEV_API_KEY="));
    return line ? line.slice("JEV_API_KEY=".length).trim() : undefined;
  } catch {
    return undefined;
  }
}

const key = readKey();

async function callJev(stateText, questions, timeoutMs = 30000) {
  async function post(target, withKey) {
    const headers = { "Content-Type": "application/json" };
    if (withKey && key) headers.Authorization = `Bearer ${key}`;
    const res = await fetch(target.endpoint, {
      method: "POST",
      headers,
      body: JSON.stringify({ model: target.model, state: { text: stateText }, questions }),
      signal: AbortSignal.timeout(timeoutMs),
    });
    return { status: res.status, ok: res.ok, body: await res.text() };
  }

  let attempt = await post(FREE, false);
  if (!attempt.ok && key) {
    attempt = await post(DIRECT, true);
  }

  if (!attempt.ok) {
    throw new Error(`Jev returned status ${attempt.status}: ${attempt.body}`);
  }

  return JSON.parse(attempt.body);
}

function parseQuestions(spec, stateText) {
  const out = {};
  for (const raw of String(spec).split(",").map((s) => s.trim()).filter(Boolean)) {
    const [kind, payload = ""] = raw.split(":");
    const id = `${kind}_${Object.keys(out).length + 1}`;
    if (kind === "noul") {
      out[id] = { type: "noul", instructions: payload };
    } else if (kind === "choice") {
      const parts = payload.split("|").map((s) => s.trim()).filter(Boolean);
      if (parts.length < 2) throw new Error(`choice needs 2+ options: ${raw}`);
      out[id] = {
        type: "choice",
        instructions: `Pick the best option based on the evidence: ${stateText}`,
        criteria: Object.fromEntries(parts.map((p, i) => [p, `Option: ${p}`])),
      };
    } else if (kind === "score") {
      const levels = payload.split("|").map((s) => s.trim()).filter(Boolean);
      if (levels.length < 2) throw new Error(`score needs 2+ levels: ${raw}`);
      out[id] = {
        type: "score",
        instructions: `Rate along the ordered levels based on: ${stateText}`,
        criteria: levels,
      };
    }
  }
  return out;
}

const TOOLS = [
  {
    name: "jev_decide",
    description: "Execute a System 1 bounded decision or probability assessment using Jev 1.3 Free via OpenCode Zen. Ideal for choice routing, safety classification, and risk scoring.",
    inputSchema: {
      type: "object",
      properties: {
        state: {
          type: "string",
          description: "The context, code, action description, or evidence to evaluate."
        },
        question_spec: {
          type: "string",
          description: "Question specification. Examples: 'choice:allow|deny|ask', 'noul:is this code safe', 'score:low|medium|high'."
        }
      },
      required: ["state", "question_spec"]
    }
  },
  {
    name: "jev_noul",
    description: "Evaluate the probability (0.0 to 1.0) that a specific statement is true given the provided context.",
    inputSchema: {
      type: "object",
      properties: {
        state: {
          type: "string",
          description: "The factual context or background evidence."
        },
        statement: {
          type: "string",
          description: "The assertion/statement to calculate the truth probability of."
        }
      },
      required: ["state", "statement"]
    }
  },
  {
    name: "jev_verify",
    description: "Verify claims or output assertions against ground-truth evidence context. Returns verification confidence, probability, and whether the claim is fully supported.",
    inputSchema: {
      type: "object",
      properties: {
        context: {
          type: "string",
          description: "Evidence, facts, test outputs, or ground-truth context."
        },
        claim: {
          type: "string",
          description: "The factual claim or completion assertion to verify."
        }
      },
      required: ["context", "claim"]
    }
  },
  {
    name: "jev_screen",
    description: "Screen code, inputs, tool calls, or content for safety, destructive side-effects, or policy violations.",
    inputSchema: {
      type: "object",
      properties: {
        content: {
          type: "string",
          description: "The input, code, shell command, or prompt to inspect."
        },
        safety_policy: {
          type: "string",
          description: "Optional custom policy or risk description. Defaults to standard safe execution."
        }
      },
      required: ["content"]
    }
  },
  {
    name: "jev_classify",
    description: "Categorize an item, request, error, or context into one of predefined distinct categories.",
    inputSchema: {
      type: "object",
      properties: {
        text: {
          type: "string",
          description: "The text, error, or item to classify."
        },
        categories: {
          type: "array",
          items: { type: "string" },
          description: "List of target category names (at least 2 categories)."
        },
        instructions: {
          type: "string",
          description: "Optional classification guidelines."
        }
      },
      required: ["text", "categories"]
    }
  },
  {
    name: "jev_rerank",
    description: "Score and rank candidate options or answers based on contextual criteria using ordinal scoring.",
    inputSchema: {
      type: "object",
      properties: {
        criteria: {
          type: "string",
          description: "The evaluation standard or criteria."
        },
        candidates: {
          type: "array",
          items: { type: "string" },
          description: "Array of candidate choices to rank."
        }
      },
      required: ["criteria", "candidates"]
    }
  },
  {
    name: "jev_tool_route",
    description: "Choose the optimal tool, action branch, or strategy among multiple candidates for a given user objective.",
    inputSchema: {
      type: "object",
      properties: {
        objective: {
          type: "string",
          description: "The user goal or task specification."
        },
        strategies: {
          type: "array",
          items: { type: "string" },
          description: "Candidate tool names or execution strategies (at least 2)."
        }
      },
      required: ["objective", "strategies"]
    }
  }
];

function sendJsonRpc(obj) {
  process.stdout.write(JSON.stringify(obj) + "\n");
}

const rl = readline.createInterface({ input: process.stdin, terminal: false });

rl.on("line", async (line) => {
  if (!line.trim()) return;
  let req;
  try {
    req = JSON.parse(line);
  } catch (err) {
    return;
  }

  const { id, method, params } = req;

  if (method === "initialize") {
    sendJsonRpc({
      jsonrpc: "2.0",
      id,
      result: {
        protocolVersion: "2024-11-05",
        capabilities: { tools: {} },
        serverInfo: { name: "jev-mcp", version: "1.3.0" }
      }
    });
  } else if (method === "notifications/initialized") {
    // No-op for initialized notification
  } else if (method === "ping") {
    sendJsonRpc({ jsonrpc: "2.0", id, result: {} });
  } else if (method === "tools/list") {
    sendJsonRpc({
      jsonrpc: "2.0",
      id,
      result: { tools: TOOLS }
    });
  } else if (method === "tools/call") {
    const toolName = params?.name;
    const args = params?.arguments || {};

    try {
      if (toolName === "jev_decide") {
        if (!args.state || typeof args.state !== "string" || !args.state.trim()) {
          throw new Error("jev_decide requires non-empty string argument 'state'");
        }
        if (!args.question_spec || typeof args.question_spec !== "string" || !args.question_spec.trim()) {
          throw new Error("jev_decide requires non-empty string argument 'question_spec'");
        }
        const questions = parseQuestions(args.question_spec, args.state);
        const res = await callJev(args.state, questions);
        sendJsonRpc({
          jsonrpc: "2.0",
          id,
          result: {
            content: [{ type: "text", text: JSON.stringify(res, null, 2) }]
          }
        });
      } else if (toolName === "jev_noul") {
        if (args.state === undefined || args.state === null) {
          throw new Error("jev_noul requires argument 'state'");
        }
        if (!args.statement || typeof args.statement !== "string" || !args.statement.trim()) {
          throw new Error("jev_noul requires non-empty string argument 'statement'");
        }
        const questions = {
          eval_1: { type: "noul", instructions: args.statement }
        };
        const res = await callJev(args.state, questions);
        const prob = res.answers?.eval_1?.noul ?? 0;
        sendJsonRpc({
          jsonrpc: "2.0",
          id,
          result: {
            content: [{
              type: "text",
              text: JSON.stringify({
                model: res.model,
                statement: args.statement,
                probability: prob,
                cost: res.cost || "0"
              }, null, 2)
            }]
          }
        });
      } else if (toolName === "jev_verify") {
        const context = args.context || "";
        const claim = args.claim || "";
        const questions = {
          supported: { type: "noul", instructions: `Is the following claim strictly verified by the evidence: "${claim}"` },
          verdict: {
            type: "choice",
            instructions: `Assess claim truth status based on the evidence context: ${claim}`,
            criteria: {
              verified: "The claim is supported and truthful based on the context.",
              unsupported: "The claim is unsupported, contradicted, or inconclusive."
            }
          }
        };
        const res = await callJev(context, questions);
        const prob = res.answers?.supported?.noul ?? 0;
        const choice = res.answers?.verdict?.choice || (prob >= 0.7 ? "verified" : "unsupported");
        sendJsonRpc({
          jsonrpc: "2.0",
          id,
          result: {
            content: [{
              type: "text",
              text: JSON.stringify({
                model: res.model,
                claim,
                verified: choice === "verified",
                probability: prob,
                confidence: res.answers?.verdict?.confidence ?? prob,
                cost: res.cost || "0"
              }, null, 2)
            }]
          }
        });
      } else if (toolName === "jev_screen") {
        const content = args.content || "";
        const policy = args.safety_policy || "Safe and non-destructive for automated software operations";
        const questions = {
          safety_assessment: {
            type: "choice",
            instructions: `Screen the content against policy (${policy}): ${content.slice(0, 500)}`,
            criteria: {
              allow: "Safe, benign, and complies with safety policy.",
              flag: "Sensitive, consequential, or borderline risk requiring user confirmation.",
              deny: "Dangerous, destructive, or explicit policy violation."
            }
          },
          safety_confidence: {
            type: "noul",
            instructions: `Does this content comply with safety standards and avoid destructive or hazardous operations (${policy}): ${content.slice(0, 300)}`
          }
        };
        const res = await callJev(content, questions);
        const assessment = res.answers?.safety_assessment?.choice || "flag";
        let safeProb = res.answers?.safety_confidence?.noul ?? 0.5;
        // Calibrate combined probability with choice confidence for stable threshold gating
        if (assessment === "allow" && safeProb < 0.8) {
          safeProb = Math.max(safeProb, res.answers?.safety_assessment?.probabilities?.allow ?? 0.88);
        } else if (assessment === "deny") {
          safeProb = Math.min(safeProb, 0.05);
        }
        sendJsonRpc({
          jsonrpc: "2.0",
          id,
          result: {
            content: [{
              type: "text",
              text: JSON.stringify({
                model: res.model,
                decision: assessment,
                safe_probability: Number(safeProb.toFixed(3)),
                confidence: res.answers?.safety_assessment?.confidence ?? 1.0,
                cost: res.cost || "0"
              }, null, 2)
            }]
          }
        });
      } else if (toolName === "jev_classify") {
        const text = args.text || "";
        const categories = Array.isArray(args.categories) ? args.categories : [];
        if (categories.length < 2) {
          throw new Error("jev_classify requires at least 2 categories.");
        }
        const criteriaObj = Object.fromEntries(categories.map((c) => [c, `Category: ${c}`]));
        const instructions = args.instructions || `Select the best category that describes: ${text.slice(0, 300)}`;
        const questions = {
          classification: {
            type: "choice",
            instructions,
            criteria: criteriaObj
          }
        };
        const res = await callJev(text, questions);
        const ans = res.answers?.classification;
        sendJsonRpc({
          jsonrpc: "2.0",
          id,
          result: {
            content: [{
              type: "text",
              text: JSON.stringify({
                model: res.model,
                category: ans?.choice,
                confidence: ans?.confidence,
                probabilities: ans?.probabilities,
                cost: res.cost || "0"
              }, null, 2)
            }]
          }
        });
      } else if (toolName === "jev_rerank") {
        const criteria = args.criteria || "Relevance and quality";
        const candidates = Array.isArray(args.candidates) ? args.candidates : [];
        if (candidates.length < 2) {
          throw new Error("jev_rerank requires at least 2 candidates.");
        }
        // Continuous probabilistic scoring: evaluate relevance/quality probability for each candidate
        const questions = {};
        candidates.forEach((c, i) => {
          questions[`cand_${i + 1}`] = {
            type: "noul",
            instructions: `Evaluate if candidate [${c}] strongly fulfills criteria: "${criteria}"`
          };
        });
        const res = await callJev(`Criteria: ${criteria}\nCandidates: ${candidates.join("; ")}`, questions);
        const ranked = candidates.map((c, i) => {
          const score = res.answers?.[`cand_${i + 1}`]?.noul ?? 0;
          return { candidate: c, score: Number(score.toFixed(3)) };
        }).sort((a, b) => b.score - a.score);

        sendJsonRpc({
          jsonrpc: "2.0",
          id,
          result: {
            content: [{
              type: "text",
              text: JSON.stringify({
                model: res.model,
                top_choice: ranked[0]?.candidate,
                ranking: ranked,
                cost: res.cost || "0"
              }, null, 2)
            }]
          }
        });
      } else if (toolName === "jev_tool_route") {
        const objective = args.objective || "";
        const strategies = Array.isArray(args.strategies) ? args.strategies : [];
        if (strategies.length < 2) {
          throw new Error("jev_tool_route requires at least 2 strategies.");
        }
        const criteriaObj = Object.fromEntries(strategies.map((s) => [s, `Strategy: ${s}`]));
        const questions = {
          route_decision: {
            type: "choice",
            instructions: `Select the most effective tool or strategy for goal: ${objective}`,
            criteria: criteriaObj
          }
        };
        const res = await callJev(objective, questions);
        const ans = res.answers?.route_decision;
        sendJsonRpc({
          jsonrpc: "2.0",
          id,
          result: {
            content: [{
              type: "text",
              text: JSON.stringify({
                model: res.model,
                selected_strategy: ans?.choice,
                confidence: ans?.confidence,
                probabilities: ans?.probabilities,
                cost: res.cost || "0"
              }, null, 2)
            }]
          }
        });
      } else {
        sendJsonRpc({
          jsonrpc: "2.0",
          id,
          error: { code: -32601, message: `Tool not found: ${toolName}` }
        });
      }
    } catch (e) {
      sendJsonRpc({
        jsonrpc: "2.0",
        id,
        result: {
          isError: true,
          content: [
            {
              type: "text",
              text: `Error calling Jev: ${e.message}`
            }
          ]
        }
      });
    }
  }
});

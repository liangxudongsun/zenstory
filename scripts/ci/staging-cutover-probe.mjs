#!/usr/bin/env node

import { createHash } from "node:crypto";
import { open, mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { parseArgs } from "node:util";
import { setTimeout as delay } from "node:timers/promises";

const origin = "https://staging-api-staging-a289.up.railway.app";
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const hash = value => createHash("sha256").update(value).digest("hex");

export function validateProbeInput(input, sourceSha) {
  if (!/^[a-f0-9]{40}$/.test(sourceSha ?? "")) throw new Error("exact source SHA required");
  if (!input || typeof input.accessToken !== "string" || !input.accessToken.trim()) throw new Error("access token required on stdin");
  for (const key of ["userId", "projectId", "fileId"]) {
    if (!uuid.test(input[key] ?? "")) throw new Error(`invalid ${key}`);
  }
  if (!/^[a-f0-9]{64}$/.test(input.contentSha256 ?? "")) throw new Error("expected file SHA-256 required");
  return input;
}

function containsFile(nodes, fileId) {
  return Array.isArray(nodes) && nodes.some(node => node?.id === fileId || containsFile(node?.children, fileId));
}

export async function probeOnce(input, { fetchImpl = fetch, timeoutMs = 5000 } = {}) {
  const targets = [
    ["current_user", "/api/auth/me", body => body?.id === input.userId],
    ["project", `/api/v1/projects/${input.projectId}`, body => body?.id === input.projectId && body?.owner_id === input.userId],
    ["file_tree", `/api/v1/projects/${input.projectId}/file-tree`, body => containsFile(body?.tree, input.fileId)],
    ["file", `/api/v1/files/${input.fileId}`, body => body?.id === input.fileId && body?.project_id === input.projectId && typeof body.content === "string" && hash(body.content) === input.contentSha256],
  ];
  return Promise.all(targets.map(async ([target, path, check]) => {
    const started = performance.now();
    const sample = { at: new Date().toISOString(), target, status: null, valid: false };
    try {
      const response = await fetchImpl(`${origin}${path}`, {
        method: "GET",
        headers: { Authorization: `Bearer ${input.accessToken}`, Accept: "application/json" },
        signal: AbortSignal.timeout(timeoutMs),
        redirect: "error",
      });
      sample.status = response.status;
      sample.requestId = response.headers.get("x-request-id");
      if (response.status === 200) {
        try {
          const body = await response.json();
          sample.valid = check(body);
          if (target === "file" && typeof body?.content === "string") sample.contentSha256 = hash(body.content);
        } catch {
          sample.invalidJson = true;
        }
      } else {
        await response.body?.cancel();
      }
    } catch (error) {
      sample.transportError = ["TimeoutError", "AbortError", "TypeError"].includes(error?.name) ? error.name : "Error";
    }
    sample.durationMs = Math.round(performance.now() - started);
    return sample;
  }));
}

export function summarizeSamples(samples) {
  const statusCounts = {};
  for (const sample of samples) {
    const status = sample.status ?? "transport_error";
    statusCounts[status] = (statusCounts[status] ?? 0) + 1;
  }
  return {
    readProbesPassed: samples.length > 0 && samples.every(sample => sample.status === 200 && sample.valid),
    samples: samples.length,
    invalidSamples: samples.filter(sample => !sample.valid).length,
    statusCounts,
    // Only separate provider/lifecycle and SSE receipts can establish these.
    cutoverVerified: false,
    sseVerified: false,
    providerSourceBinding: "NOT_VERIFIED",
  };
}

async function main() {
  const { values } = parseArgs({ options: {
    "source-sha": { type: "string" },
    output: { type: "string" },
    "duration-seconds": { type: "string", default: "600" },
    "interval-seconds": { type: "string", default: "2" },
  } });
  const duration = Number(values["duration-seconds"]);
  const interval = Number(values["interval-seconds"]);
  if (!Number.isFinite(duration) || duration < 1 || duration > 1800 || !Number.isFinite(interval) || interval < 1 || interval > 60) {
    throw new Error("duration must be 1–1800 seconds and interval 1–60 seconds");
  }
  if (!values.output) throw new Error("private output directory required");
  let stdin = "";
  for await (const chunk of process.stdin) {
    stdin += chunk;
    if (stdin.length > 16384) throw new Error("stdin fixture is too large");
  }
  let input;
  try { input = JSON.parse(stdin); } catch { throw new Error("stdin must contain a JSON fixture"); }
  stdin = "";
  validateProbeInput(input, values["source-sha"]);
  const output = resolve(values.output);
  await mkdir(output, { recursive: true, mode: 0o700 });
  const stream = await open(resolve(output, "read-probes.ndjson"), "wx", 0o600);
  const startedAt = new Date().toISOString();
  const end = performance.now() + duration * 1000;
  const samples = [];
  let interrupted = false;
  const stop = () => { interrupted = true; };
  process.once("SIGINT", stop);
  process.once("SIGTERM", stop);
  try {
    do {
      const cycleStarted = performance.now();
      const cycle = await probeOnce(input);
      samples.push(...cycle);
      await stream.write(cycle.map(sample => JSON.stringify(sample)).join("\n") + "\n");
      if (interrupted || performance.now() >= end) break;
      await delay(Math.max(0, Math.min(interval * 1000 - (performance.now() - cycleStarted), end - performance.now())));
    } while (!interrupted && performance.now() < end);
  } finally {
    input.accessToken = "";
    process.removeListener("SIGINT", stop);
    process.removeListener("SIGTERM", stop);
    await stream.close();
  }
  const receipt = {
    schemaVersion: 1,
    environment: "staging",
    origin,
    requestedSourceSha: values["source-sha"],
    startedAt,
    finishedAt: new Date().toISOString(),
    interrupted,
    ...summarizeSamples(samples),
  };
  const file = await open(resolve(output, "read-probe-summary.json"), "wx", 0o600);
  try { await file.writeFile(JSON.stringify(receipt, null, 2) + "\n"); } finally { await file.close(); }
  process.stdout.write(JSON.stringify(receipt) + "\n");
  if (!receipt.readProbesPassed || interrupted) process.exitCode = 1;
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  main().catch(() => {
    process.stderr.write("staging-cutover-probe: failed; validate fixture, arguments and private output permissions\n");
    process.exitCode = 1;
  });
}

import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import test from "node:test";

import { probeOnce, summarizeSamples, validateProbeInput } from "./staging-cutover-probe.mjs";

const content = "合成验收稿件，不含用户数据。";
const input = {
  accessToken: "synthetic-token-never-record",
  userId: "11111111-1111-4111-8111-111111111111",
  projectId: "22222222-2222-4222-8222-222222222222",
  fileId: "33333333-3333-4333-8333-333333333333",
  contentSha256: createHash("sha256").update(content).digest("hex"),
};
const sourceSha = "a".repeat(40);

function transport({ status = 200, changed = false } = {}) {
  const calls = [];
  return {
    calls,
    async fetch(url, options) {
      calls.push({ url, options });
      let data = { id: input.userId };
      if (url.endsWith(`/projects/${input.projectId}`)) data = { id: input.projectId, owner_id: input.userId };
      if (url.endsWith("/file-tree")) data = { tree: [{ id: "synthetic-folder", children: [{ id: input.fileId, children: [] }] }] };
      if (url.endsWith(`/files/${input.fileId}`)) data = { id: input.fileId, project_id: input.projectId, content: changed ? "unexpected overwrite" : content };
      return new Response(JSON.stringify(data), { status, headers: { "X-Request-ID": "synthetic-request" } });
    },
  };
}

test("only accepts exact source and scoped synthetic identifiers before requests", () => {
  assert.deepEqual(validateProbeInput(input, sourceSha), input);
  for (const patch of [{ userId: "../user" }, { projectId: "x?secret" }, { fileId: "" }, { contentSha256: "bad" }, { accessToken: "" }]) {
    assert.throws(() => validateProbeInput({ ...input, ...patch }, sourceSha));
  }
  assert.throws(() => validateProbeInput(input, "main"), /source SHA/);
});

test("samples actual authenticated paths with GET only and records no credentials or manuscript", async () => {
  const http = transport();
  const samples = await probeOnce(input, { fetchImpl: http.fetch });
  assert.equal(http.calls.length, 4);
  for (const { url, options } of http.calls) {
    assert.equal(new URL(url).origin, "https://staging-api-staging-a289.up.railway.app");
    assert.equal(options.method, "GET");
    assert.equal(options.headers.Authorization, `Bearer ${input.accessToken}`);
    assert.equal(options.redirect, "error");
  }
  assert.deepEqual(samples.map(value => value.target), ["current_user", "project", "file_tree", "file"]);
  assert.ok(samples.every(value => value.status === 200 && value.valid));
  assert.equal(samples.at(-1).contentSha256, input.contentSha256);
  assert.ok(samples.every(value => value.requestId === "synthetic-request"));
  const receipt = JSON.stringify(summarizeSamples(samples));
  assert.ok(!receipt.includes(input.accessToken));
  assert.ok(!receipt.includes(content));
});

test("HTTP 200 cannot conceal a changed manuscript or wrong account", async () => {
  const http = transport({ changed: true });
  const samples = await probeOnce(input, { fetchImpl: http.fetch });
  assert.equal(samples.find(value => value.target === "file").valid, false);
  assert.equal(summarizeSamples(samples).readProbesPassed, false);
  const wrongAccount = await probeOnce(input, { fetchImpl: async () => new Response(JSON.stringify({ id: "another-account" })) });
  assert.equal(wrongAccount[0].valid, false);
  const wrongOwner = await probeOnce(input, { fetchImpl: async () => new Response(JSON.stringify({ id: input.projectId, owner_id: "another-account", user_id: input.userId })) });
  assert.equal(wrongOwner[1].valid, false);
});

test("401 and 502 remain individual observations with no refresh or write retry", async () => {
  const http = transport({ status: 401 });
  const unauthorized = await probeOnce(input, { fetchImpl: http.fetch });
  assert.equal(http.calls.length, 4);
  assert.ok(unauthorized.every(value => !value.valid && value.status === 401));
  const failed = await probeOnce(input, { fetchImpl: transport({ status: 502 }).fetch });
  const summary = summarizeSamples([...unauthorized, ...failed]);
  assert.equal(summary.readProbesPassed, false);
  assert.equal(summary.statusCounts[401], 4);
  assert.equal(summary.statusCounts[502], 4);
  assert.equal(summary.cutoverVerified, false);
  assert.equal(summary.sseVerified, false);
});

test("network failure is retained without leaking transport error text", async () => {
  const samples = await probeOnce(input, { fetchImpl: async () => { throw new Error(`private ${input.accessToken}`); } });
  assert.ok(samples.every(value => value.status === null && !value.valid && value.transportError === "Error"));
  assert.ok(!JSON.stringify(samples).includes(input.accessToken));
  assert.equal(summarizeSamples([]).readProbesPassed, false);
});

import test from "node:test";
import assert from "node:assert/strict";
import { chunkDocument, stableId } from "../src/text.js";

test("chunkDocument preserves content with overlap", () => {
  const text = "A".repeat(900);
  const chunks = chunkDocument(text, { size: 300, overlap: 50 });
  assert.equal(chunks.length, 4);
  assert.equal(chunks[0].length, 300);
  assert.equal(chunks[1].slice(0, 50), chunks[0].slice(-50));
});

test("stableId is deterministic", () => {
  assert.equal(stableId("seekdb"), stableId("seekdb"));
  assert.notEqual(stableId("seekdb"), stableId("StepFun"));
});

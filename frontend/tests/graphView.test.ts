import test from "node:test";
import assert from "node:assert/strict";
import { graphView, normalizeSearch, ViewNode } from "../src/features/nodes/graphView";
const nodes: ViewNode[] = [
  { id: "1", label: "root", order: 0 },
  { id: "2", parentId: "1", label: "가나다\nHello", order: 0, tags: ["a", "b"] },
  { id: "3", parentId: "2", label: "HELLO", order: 0, tags: ["b"] },
  { id: "4", parentId: "1", label: "other", order: 1, tags: ["a"] },
];
test("NFC, case, whitespace and OR tags combine without duplicates", () => {
  assert.equal(normalizeSearch("  가나".normalize("NFD")), "가나");
  const v = graphView([...nodes, nodes[1]], " HELLO ", ["a", "b", "b"], [], null);
  assert.deepEqual(v.results.map(n => n.id), ["2", "3"]);
  assert.deepEqual([...v.visible], ["1", "2", "3"]);
  assert.equal(v.matches.has("1"), false);
});
test("collapsed results remain searchable; focus expands only temporarily", () => {
  const folded = graphView(nodes, "hello", [], ["1", "2"]);
  assert.deepEqual([...folded.visible], ["1"]);
  assert.equal(folded.results.length, 2);
  assert.equal(folded.hiddenCounts.get("1"), 3);
  assert.deepEqual([...graphView(nodes, "hello", [], ["1", "2"], "3").visible], ["1", "2", "3"]);
  assert.deepEqual([...graphView(nodes, "", [], ["1", "2"], "3").visible], ["1"]);
});
test("no results, deletion and cycles terminate without mutating data", () => {
  const original = JSON.stringify(nodes);
  assert.equal(graphView(nodes, "missing", [], []).visible.size, 0);
  assert.equal(graphView(nodes.slice(0, 2), "", [], ["3"]).collapsed.size, 0);
  assert.equal(graphView([{ ...nodes[0], parentId: "1" }], "", [], []).visible.size, 0);
  assert.equal(JSON.stringify(nodes), original);
  assert.equal(graphView([], "", [], []).nodes.length, 0);
});
test("1000 nodes with depth 20 keep complete result and descendant counts", () => {
  const fixture: ViewNode[] = Array.from({ length: 1000 }, (_, i) => ({ id: String(i + 1),
    parentId: i ? String(i % 20 === 0 ? 1 : i) : undefined, label: `노드 ${i}`, order: i }));
  const v = graphView(fixture, "노드", [], ["1"], "1000");
  assert.equal(v.results.length, 1000);
  assert.equal(v.hiddenCounts.get("1"), 999);
  assert.equal(v.visible.has("1000"), true);
});

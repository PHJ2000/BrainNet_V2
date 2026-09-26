import fs from "node:fs";

const files = process.argv.slice(2);
if (!files.length) throw new Error("Usage: node summarize-events.mjs <events.jsonl> [...]");
const totals = { input_tokens: 0, cached_input_tokens: 0, cache_write_input_tokens: 0, output_tokens: 0, reasoning_tokens: 0 };
let malformed = 0;
for (const file of files) {
  const maxima = { input_tokens: 0, cached_input_tokens: 0, cache_write_input_tokens: 0, output_tokens: 0, reasoning_tokens: 0 };
  function visit(value) {
    if (!value || typeof value !== "object") return;
    const usage = value.usage;
    if (usage && typeof usage === "object") {
      const candidate = {
        input_tokens: Number(usage.input_tokens ?? 0),
        cached_input_tokens: Number(usage.cached_input_tokens ?? usage.input_tokens_details?.cached_tokens ?? 0),
        cache_write_input_tokens: Number(usage.cache_write_input_tokens ?? usage.input_tokens_details?.cache_write_tokens ?? 0),
        output_tokens: Number(usage.output_tokens ?? 0),
        reasoning_tokens: Number(usage.reasoning_tokens ?? usage.reasoning_output_tokens ?? usage.output_tokens_details?.reasoning_tokens ?? 0),
      };
      for (const name of Object.keys(maxima)) maxima[name] = Math.max(maxima[name], candidate[name]);
    }
    for (const child of Object.values(value)) if (child && typeof child === "object") visit(child);
  }
  for (const line of fs.readFileSync(file, "utf8").split(/\r?\n/).filter(Boolean)) {
    try { visit(JSON.parse(line)); } catch { malformed++; }
  }
  for (const name of Object.keys(totals)) totals[name] += maxima[name];
}
console.log(JSON.stringify({ ...totals, process_count: files.length, malformed_lines: malformed }));

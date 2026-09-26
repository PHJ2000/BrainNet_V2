import fs from "node:fs";
import path from "node:path";

const [runPath, pricingPath] = process.argv.slice(2);
if (!runPath || !pricingPath) throw new Error("Usage: node calculate-api-cost.mjs <run.json> <api-pricing.json>");
const run = JSON.parse(fs.readFileSync(runPath, "utf8"));
const pricing = JSON.parse(fs.readFileSync(pricingPath, "utf8"));
const runDirectory = path.dirname(runPath);
const unit = Number(pricing.unit_tokens);

function readUsage(file) {
  const maxima = { input_tokens: 0, cached_input_tokens: 0, cache_write_input_tokens: 0, output_tokens: 0, reasoning_tokens: 0 };
  let malformed = 0;
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
      for (const key of Object.keys(maxima)) maxima[key] = Math.max(maxima[key], candidate[key]);
    }
    for (const child of Object.values(value)) if (child && typeof child === "object") visit(child);
  }
  for (const line of fs.readFileSync(file, "utf8").split(/\r?\n/).filter(Boolean)) {
    try { visit(JSON.parse(line)); } catch { malformed++; }
  }
  return { ...maxima, malformed_lines: malformed };
}

function calculate(usage, rates) {
  const uncached = Math.max(0, usage.input_tokens - usage.cached_input_tokens - usage.cache_write_input_tokens);
  return (
    uncached * rates.input +
    usage.cached_input_tokens * rates.cached_input +
    usage.cache_write_input_tokens * rates.cache_write +
    usage.output_tokens * rates.output
  ) / unit;
}

function emptyTotals() {
  return {
    input_tokens: 0,
    cached_input_tokens: 0,
    cache_write_input_tokens: 0,
    output_tokens: 0,
    reasoning_tokens: 0,
    standard_short_context_usd: 0,
    all_long_context_sensitivity_usd: 0,
  };
}

function add(target, usage, shortCost, longCost) {
  for (const key of ["input_tokens", "cached_input_tokens", "cache_write_input_tokens", "output_tokens", "reasoning_tokens"]) {
    target[key] += usage[key];
  }
  target.standard_short_context_usd += shortCost;
  target.all_long_context_sensitivity_usd += longCost;
}

const totals = emptyTotals();
const byModel = {};
const byStep = [];
for (const step of run.steps ?? []) {
  const rates = pricing.models[step.model];
  if (!rates) throw new Error(`No API pricing for ${step.model}`);
  const eventsPath = path.join(runDirectory, "steps", step.name, "events.jsonl");
  const usage = readUsage(eventsPath);
  const shortCost = calculate(usage, rates.short_context);
  const longCost = calculate(usage, rates.long_context);
  if (!byModel[step.model]) byModel[step.model] = emptyTotals();
  add(totals, usage, shortCost, longCost);
  add(byModel[step.model], usage, shortCost, longCost);
  byStep.push({
    name: step.name,
    model: step.model,
    reasoning: step.reasoning,
    ...usage,
    standard_short_context_usd: shortCost,
    all_long_context_sensitivity_usd: longCost,
  });
}

console.log(JSON.stringify({
  pricing_snapshot_date: pricing.snapshot_date,
  pricing_source_url: pricing.source_url,
  currency: pricing.currency,
  processing_tier: pricing.processing_tier,
  primary_estimate: "standard_short_context_usd",
  assumptions: [
    `Primary estimate uses Standard API rates for requests up to ${pricing.short_context_max_input_tokens} input tokens.`,
    "The long-context value is a sensitivity scenario that prices every recorded token at the long-context rate; aggregate CLI logs cannot identify which individual model calls crossed the threshold.",
    "Cached and cache-write tokens are treated as subsets of input_tokens. Reasoning tokens are already included in output_tokens and are not charged twice.",
    "Token-equivalent API cost is an evaluation metric, not the actual ChatGPT subscription or Codex charge.",
    "Tool-specific fees and regional or Fast mode uplifts are excluded.",
  ],
  totals,
  by_model: byModel,
  by_step: byStep,
}, null, 2));

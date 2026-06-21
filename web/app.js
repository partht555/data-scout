const conversation = document.querySelector("#conversation");
const form = document.querySelector("#search-form");
const input = document.querySelector("#prompt-input");
const dryRun = document.querySelector("#dry-run");
const modeNote = document.querySelector("#mode-note");

const catalog = [
  { title: "Food Nutrition Dataset", source: "kaggle", score: 1, url: "https://www.kaggle.com/datasets/utsavdey1410/food-nutrition-dataset", summary: "Food nutrition information including calories, protein, carbohydrates, and fat.", files: ["csv"], schema: ["food_name", "calories", "protein", "carbohydrates"], matchedFields: ["title", "tags", "schema.name"] },
  { title: "Retail Sales Data", source: "kaggle", score: .96, url: "https://www.kaggle.com/datasets/shivkumarganesh/retail-sales-data", summary: "Retail transactions with dates, products, quantities, and sales amounts.", files: ["csv"], schema: ["date", "quantity", "sales"], matchedFields: ["title", "tags", "schema.name"] },
  { title: "Formula 1 World Championship Results", source: "kaggle", score: .91, url: "https://www.kaggle.com/datasets/rohanrao/formula-1-world-championship-1950-2020", summary: "Formula 1 races, drivers, constructors, lap times, and championship results.", files: ["csv"], schema: ["race_id", "driver_id", "position"], matchedFields: ["title", "tags"] },
];

function buildPayload(query) {
  const lower = query.toLowerCase();
  const limitMatch = lower.match(/\b(\d{1,2})\s+(?:(?:[a-z-]+\s+){0,3})?(?:datasets?|results?)\b/);
  const payload = { query, limit: limitMatch ? Math.min(Math.max(Number(limitMatch[1]), 1), 20) : 5 };
  const formats = [["csv", /\bcsv\b/], ["json", /\bjson\b/], ["parquet", /\bparquet\b/], ["tsv", /\btsv\b/], ["xlsx", /\b(?:xlsx|excel|spreadsheet)\b/]]
    .filter(([, pattern]) => pattern.test(lower))
    .map(([format]) => format);
  const licenseMatch = lower.match(/(?:license[\s:=-]*|under\s+)(cc[-\s]?by(?:[-\s]?\d(?:\.\d)?)?)/);
  if (formats.length || lower.includes("kaggle") || licenseMatch) payload.filters = {};
  if (formats.length) payload.filters.format = formats;
  if (lower.includes("kaggle")) payload.filters.source = ["kaggle"];
  if (licenseMatch) payload.filters.license = [licenseMatch[1].replace(/[\s-]+/g, "-")];
  return payload;
}

function localResponse(payload) {
  const lower = payload.query.toLowerCase();
  const term = lower.includes("food") || lower.includes("nutrition") ? "Food Nutrition Dataset" : lower.includes("retail") || lower.includes("sales") || lower.includes("forecast") ? "Retail Sales Data" : lower.includes("formula") || lower.includes("race") || lower.includes("sports") ? "Formula 1 World Championship Results" : null;
  const results = term ? catalog.filter((item) => item.title === term) : [];
  return { results: results.slice(0, payload.limit) };
}

function appendMessage(kind, content) {
  const article = document.createElement("article");
  article.className = `message ${kind}-message`;
  article.innerHTML = kind === "assistant" ? `<div class="avatar">✦</div><div class="bubble">${content}</div>` : `<div class="bubble">${content}</div>`;
  conversation.append(article);
  conversation.scrollTo({ top: conversation.scrollHeight, behavior: "smooth" });
  return article;
}

function renderResults(payload, response) {
  const intent = response.interpretedIntent || {};
  const plan = [
    `limit: ${payload.limit}`,
    `mode: ${intent.mode || "dry-run"}`,
    ...(intent.preferredFormats || payload.filters?.format || []).map((value) => `format: ${value}`),
    ...(intent.sources || payload.filters?.source || []).map((value) => `source: ${value}`),
    ...(intent.licenses || payload.filters?.license || []).map((value) => `license: ${value}`),
    ...(intent.requiredColumns || []).map((value) => `field: ${value}`),
  ];
  if (!response.results.length) {
    return `<p>I couldn't find a close match in this preview catalog.</p><p class="result-summary">Try broadening the request or remove a filter.</p><div class="plan">${plan.map((item) => `<span>${item}</span>`).join("")}</div>`;
  }
  return `<p>I found ${response.results.length} dataset${response.results.length === 1 ? "" : "s"}.</p><div class="plan">${plan.map((item) => `<span>${item}</span>`).join("")}</div><div class="result-list">${response.results.map(renderResult).join("")}</div>`;
}

function renderResult(item) {
  const metadata = [
    compactValues(item.files, "name", "format"),
    compactValues(item.schema, "name"),
    readableMatchedFields(item.matchedFields),
  ].filter(Boolean).join(" · ");
  return `<a class="result" href="${item.url}" target="_blank" rel="noreferrer"><div class="result-top"><span>${item.title}</span><span class="score">${Number(item.score || 0).toFixed(2)}</span></div><p class="result-summary">${item.summary}</p>${metadata ? `<div class="result-meta">${metadata}</div>` : ""}</a>`;
}

function compactValues(values, ...keys) {
  if (!Array.isArray(values) || !values.length) return "";
  return values.map((value) => {
    if (typeof value === "string") return value;
    return keys.map((key) => value?.[key]).find(Boolean);
  }).filter(Boolean).join(", ");
}

function readableMatchedFields(fields) {
  const labels = {
    title: "Title", tags: "Tags", summary: "Summary", "schema.name": "Schema fields",
    "files.name": "File names", "files.format": "File format", source: "Source",
    license: "License", keyword: "Keyword match",
  };
  const values = [...new Set((fields || []).map((field) => labels[field] || field))];
  return values.length ? `Matched: ${values.join(", ")}` : "";
}

async function search(query) {
  const payload = buildPayload(query);
  appendMessage("user", query);
  const loading = appendMessage("assistant", '<p class="loading">Searching the catalog...</p>');
  try {
    let response;
    if (dryRun.checked) response = localResponse(payload);
    else {
      if (!window.DATA_CURATOR_API_URL) throw new Error("No API endpoint is configured for this environment.");
      const request = await fetch(window.DATA_CURATOR_API_URL, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      response = await request.json();
      if (!request.ok) throw new Error(response.error?.message || "The search API returned an error.");
    }
    loading.querySelector(".bubble").innerHTML = renderResults(payload, response);
    conversation.scrollTo({ top: conversation.scrollHeight, behavior: "smooth" });
  } catch (error) {
    loading.querySelector(".bubble").innerHTML = `<p class="error">${error.message}</p><p class="result-summary">Check the endpoint configuration or try again.</p>`;
  }
}

form.addEventListener("submit", (event) => { event.preventDefault(); const query = input.value.trim(); if (query) { input.value = ""; search(query); } });
input.addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); form.requestSubmit(); } });
document.querySelectorAll(".prompt").forEach((button) => button.addEventListener("click", () => { input.value = button.dataset.prompt; form.requestSubmit(); }));
document.querySelector("#new-chat").addEventListener("click", () => { conversation.querySelectorAll(".message:not(.intro-message)").forEach((message) => message.remove()); input.focus(); });
dryRun.addEventListener("change", () => { modeNote.textContent = dryRun.checked ? "Using a local response preview. No network request is sent." : "Requests are sent to the configured API Gateway endpoint."; });

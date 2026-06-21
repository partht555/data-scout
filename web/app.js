const conversation = document.querySelector("#conversation");
const form = document.querySelector("#search-form");
const input = document.querySelector("#prompt-input");

const catalog = [
  {
    datasetId: "kaggle:utsavdey1410/food-nutrition-dataset",
    title: "Food Nutrition Dataset", source: "kaggle", score: 1,
    url: "https://www.kaggle.com/datasets/utsavdey1410/food-nutrition-dataset",
    summary: "Food nutrition information including calories, protein, carbohydrates, and fat content across hundreds of common foods.",
    files: [{ name: "food_nutrition.csv", format: "csv", sizeBytes: null }],
    schema: [
      { name: "food_name", type: "string", nullable: false },
      { name: "calories", type: "number", nullable: true },
      { name: "protein", type: "number", nullable: true },
      { name: "carbohydrates", type: "number", nullable: true },
    ],
    matchedFields: ["title", "tags", "schema.name"],
  },
  {
    datasetId: "kaggle:shivkumarganesh/retail-sales-data",
    title: "Retail Sales Data", source: "kaggle", score: .96,
    url: "https://www.kaggle.com/datasets/shivkumarganesh/retail-sales-data",
    summary: "Retail transactions with dates, products, quantities, and sales amounts suitable for forecasting and trend analysis.",
    files: [{ name: "retail_sales.csv", format: "csv", sizeBytes: null }],
    schema: [
      { name: "date", type: "date", nullable: false },
      { name: "product", type: "string", nullable: false },
      { name: "quantity", type: "integer", nullable: false },
      { name: "sales", type: "float", nullable: true },
    ],
    matchedFields: ["title", "tags", "schema.name"],
  },
  {
    datasetId: "kaggle:rohanrao/formula-1-world-championship-1950-2020",
    title: "Formula 1 World Championship Results", source: "kaggle", score: .91,
    url: "https://www.kaggle.com/datasets/rohanrao/formula-1-world-championship-1950-2020",
    summary: "Formula 1 races, drivers, constructors, lap times, and championship results from 1950 to 2020.",
    files: [
      { name: "races.csv", format: "csv", sizeBytes: null },
      { name: "results.csv", format: "csv", sizeBytes: null },
    ],
    schema: [],
    matchedFields: ["title", "tags"],
  },
];

function buildPayload(query) {
  return { query };
}

function localResponse(payload) {
  const lower = payload.query.toLowerCase();
  const term = lower.includes("food") || lower.includes("nutrition") ? "Food Nutrition Dataset"
    : lower.includes("retail") || lower.includes("sales") || lower.includes("forecast") ? "Retail Sales Data"
    : lower.includes("formula") || lower.includes("race") || lower.includes("sports") ? "Formula 1 World Championship Results"
    : null;
  const results = term ? catalog.filter((item) => item.title === term) : [];
  return { interpretedIntent: { mode: "dry-run", keywords: lower.split(/\s+/), suggestedLimit: 5 }, results: results.slice(0, 5) };
}

function appendMessage(kind, content) {
  const article = document.createElement("article");
  article.className = `message ${kind}-message`;
  article.innerHTML = kind === "assistant"
    ? `<div class="avatar">✦</div><div class="bubble">${content}</div>`
    : `<div class="bubble">${content}</div>`;
  conversation.append(article);
  conversation.scrollTo({ top: conversation.scrollHeight, behavior: "smooth" });
  return article;
}

function renderResults(payload, response) {
  const intent = response.interpretedIntent || {};
  const plan = [
    `limit: ${intent.suggestedLimit || payload.limit || 5}`,
    `mode: ${intent.mode || "dry-run"}`,
    ...(intent.preferredFormats || payload.filters?.format || []).map((value) => `format: ${value}`),
    ...(intent.sources || payload.filters?.source || []).map((value) => `source: ${value}`),
    ...(intent.licenses || payload.filters?.license || []).map((value) => `license: ${value}`),
    ...(intent.requiredColumns || []).map((value) => `field: ${value}`),
  ];
  if (!response.results.length) {
    return `<p>I couldn't find a close match in this preview catalog.</p><p class="result-summary">Try broadening the request or remove a filter.</p><div class="plan">${plan.map((item) => `<span>${item}</span>`).join("")}</div>`;
  }
  const summaryText = response.resultSummary || `I found ${response.results.length} dataset${response.results.length === 1 ? "" : "s"}.`;
  return `<p>${summaryText}</p><div class="plan">${plan.map((item) => `<span>${item}</span>`).join("")}</div><div class="result-list">${response.results.map((item) => renderResult(item, intent)).join("")}</div>`;
}

function renderResult(item, intent) {
  const author = extractAuthor(item);
  const bylineParts = [author ? `by ${author}` : null, item.source].filter(Boolean);
  const byline = bylineParts.length ? `<div class="result-byline">${bylineParts.join(" · ")}</div>` : "";

  const filesText = compactValues(item.files, "name", "format");
  const filesHtml = filesText ? `<div class="result-files">${filesText}</div>` : "";

  const schemaHtml = renderSchema(item.schema, intent);
  const matchHtml = renderMatchDetails(item, intent);

  return `<div class="result">
    <div class="result-top">
      <a class="result-title" href="${item.url}" target="_blank" rel="noreferrer">${item.title}</a>
      <span class="score">${Number(item.score || 0).toFixed(2)}</span>
    </div>
    ${byline}
    <p class="result-summary">${item.summary}</p>
    ${filesHtml}
    ${schemaHtml}
    ${matchHtml}
  </div>`;
}

function extractAuthor(item) {
  const id = item.datasetId || "";
  const match = id.match(/^[^:]+:([^/]+)\//);
  return match ? match[1] : null;
}

function renderSchema(schema, intent) {
  if (!Array.isArray(schema) || !schema.length) {
    return "";
  }
  const queryTokens = new Set((intent?.keywords || []).map((k) => k.toLowerCase()));
  const pills = schema.map((col) => {
    const name = typeof col === "string" ? col : col?.name;
    const type = typeof col === "object" ? col?.type : null;
    if (!name) return "";
    const nameTokens = name.toLowerCase().split(/[^a-z0-9]+/);
    const isMatched = nameTokens.some((t) => t && queryTokens.has(t));
    return `<span class="col-pill${isMatched ? " col-matched" : ""}">${name}${type ? `<em>${type}</em>` : ""}</span>`;
  }).filter(Boolean).join("");
  return `<div class="schema-row">${pills}</div>`;
}

function renderMatchDetails(item, intent) {
  const fieldLabels = {
    title: "Title", tags: "Tags", summary: "Summary", "schema.name": "Schema columns",
    "files.name": "File names", "files.format": "File format", source: "Source",
    license: "License", keyword: "Keyword match",
  };
  const matchedFieldNames = [...new Set((item.matchedFields || []).map((f) => fieldLabels[f] || f))];
  const fieldsLine = matchedFieldNames.length
    ? `<div class="match-row"><span class="match-label">Matched on</span>${matchedFieldNames.join(", ")}</div>`
    : "";

  const queryTokens = new Set((intent?.keywords || []).map((k) => k.toLowerCase()));

  // Collect all text from the document to find which keywords appear in this result
  const docText = [
    item.title || "",
    ...(item.tags || []),
    item.summary || "",
    ...(item.files || []).map((f) => (typeof f === "string" ? f : f?.name || "")),
    ...(item.schema || []).map((c) => (typeof c === "string" ? c : c?.name || "")),
  ].join(" ").toLowerCase();
  const docTokens = new Set(docText.split(/[^a-z0-9]+/).filter(Boolean));
  const matchedKeywords = [...queryTokens].filter((k) => docTokens.has(k));
  const keywordsLine = matchedKeywords.length
    ? `<div class="match-row"><span class="match-label">Keywords</span>${matchedKeywords.join(", ")}</div>`
    : "";

  const schema = item.schema || [];
  const colMatches = schema
    .map((col) => (typeof col === "string" ? col : col?.name))
    .filter(Boolean)
    .filter((name) => name.toLowerCase().split(/[^a-z0-9]+/).some((t) => t && queryTokens.has(t)));
  const colsLine = colMatches.length
    ? `<div class="match-row"><span class="match-label">Columns</span>${colMatches.join(", ")}</div>`
    : "";

  if (!fieldsLine && !keywordsLine && !colsLine) return "";

  return `<details class="match-details"><summary>Match details</summary><div class="match-body">${fieldsLine}${keywordsLine}${colsLine}</div></details>`;
}

function compactValues(values, ...keys) {
  if (!Array.isArray(values) || !values.length) return "";
  return values.map((value) => {
    if (typeof value === "string") return value;
    return keys.map((key) => value?.[key]).find(Boolean);
  }).filter(Boolean).join(", ");
}

async function search(query) {
  const payload = buildPayload(query);
  appendMessage("user", query);
  const loading = appendMessage("assistant", '<p class="loading">Searching the catalog...</p>');
  try {
    let response;
    if (!window.DATA_CURATOR_API_URL) throw new Error("No API endpoint is configured for this environment.");
    const request = await fetch(window.DATA_CURATOR_API_URL, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    response = await request.json();
    if (!request.ok) throw new Error(response.error?.message || "The search API returned an error.");
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

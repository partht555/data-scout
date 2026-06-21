const { spawnSync } = require("node:child_process");

const python = process.platform === "win32" ? "python" : "python3";
const result = spawnSync(python, ["app.py", ...process.argv.slice(2)], { stdio: "inherit" });

if (result.error) {
  console.error(`Unable to run ${python}. Install Python 3 and ensure '${python}' is on PATH.`);
  process.exit(1);
}

process.exit(result.status ?? 1);

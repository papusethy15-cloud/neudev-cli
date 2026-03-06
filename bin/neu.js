#!/usr/bin/env node

const { spawnSync } = require("child_process");

const userArgs = process.argv.slice(2);

function pythonCandidates() {
  if (process.env.NEUDEV_PYTHON) {
    return [{ command: process.env.NEUDEV_PYTHON, args: [] }];
  }
  if (process.platform === "win32") {
    return [
      { command: "py", args: ["-3"] },
      { command: "python", args: [] },
    ];
  }
  return [
    { command: "python3", args: [] },
    { command: "python", args: [] },
  ];
}

function tryRun(candidate) {
  const result = spawnSync(
    candidate.command,
    [...candidate.args, "-m", "neudev.cli", ...userArgs],
    { encoding: "utf-8", stdio: "pipe" }
  );
  if (result.error) {
    return { ok: false, retry: true };
  }

  const combined = `${result.stdout || ""}${result.stderr || ""}`;
  if (result.status !== 0 && /No module named neudev|ModuleNotFoundError/i.test(combined)) {
    return { ok: false, retry: true };
  }

  if (result.stdout) {
    process.stdout.write(result.stdout);
  }
  if (result.stderr) {
    process.stderr.write(result.stderr);
  }
  process.exit(result.status === null ? 1 : result.status);
}

for (const candidate of pythonCandidates()) {
  const outcome = tryRun(candidate);
  if (outcome.ok) {
    break;
  }
  if (!outcome.retry) {
    process.exit(1);
  }
}

console.error("NeuDev could not find a working Python runtime with the neudev package installed.");
console.error("Run `npm rebuild -g neudev-cli` or install the Python package manually with `python -m pip install --user --upgrade <repo-path>`.");
process.exit(1);

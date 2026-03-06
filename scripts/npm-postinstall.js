const { spawnSync } = require("child_process");
const path = require("path");

const packageRoot = path.resolve(__dirname, "..");

function candidates() {
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

function run(candidate, args) {
  return spawnSync(candidate.command, [...candidate.args, ...args], {
    cwd: packageRoot,
    encoding: "utf-8",
  });
}

function isVirtualEnv(candidate) {
  const result = run(candidate, [
    "-c",
    "import sys; print(1 if sys.prefix != getattr(sys, 'base_prefix', sys.prefix) else 0)",
  ]);
  return result.status === 0 && String(result.stdout || "").trim() === "1";
}

const failures = [];

for (const candidate of candidates()) {
  const probe = run(candidate, ["-c", "import sys; print(sys.executable)"]);
  if (probe.error || probe.status !== 0) {
    continue;
  }

  const pipArgs = ["-m", "pip", "install", "--upgrade", "--force-reinstall"];
  if (!isVirtualEnv(candidate)) {
    pipArgs.push("--user");
  }
  pipArgs.push(packageRoot);

  const install = run(candidate, pipArgs);
  if (install.status === 0) {
    process.stdout.write("NeuDev npm install: Python runtime bootstrapped successfully.\n");
    process.exit(0);
  }

  failures.push(
    `${candidate.command} ${candidate.args.join(" ")} -> ${String(install.stderr || install.stdout || "").trim()}`
  );
}

process.stderr.write("NeuDev npm install could not bootstrap the Python runtime.\n");
for (const failure of failures) {
  process.stderr.write(`${failure}\n`);
}
process.stderr.write(
  "Install Python 3.10+ and pip, then run `python -m pip install --user --upgrade <repo-path>`.\n"
);
process.exit(1);

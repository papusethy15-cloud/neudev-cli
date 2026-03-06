const { spawnSync } = require("child_process");

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

for (const candidate of candidates()) {
  const result = spawnSync(candidate.command, [...candidate.args, "-m", "pip", "uninstall", "-y", "neudev"], {
    encoding: "utf-8",
  });
  if (!result.error) {
    if (result.stdout) {
      process.stdout.write(result.stdout);
    }
    if (result.stderr) {
      process.stderr.write(result.stderr);
    }
    process.exit(0);
  }
}

process.stdout.write(
  "NeuDev npm uninstall: no working Python interpreter was found for automatic package cleanup. If needed, run `python -m pip uninstall neudev` manually.\n"
);

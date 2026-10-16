import { copyFileSync, constants, existsSync } from "node:fs";
import { loadEnvFile } from "node:process";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { root, python } from "./python.mjs";

const config = path.join(root, ".env.agents");
if (process.argv.includes("--setup")) {
  if (existsSync(config)) console.log(".env.agents already exists; it was preserved.");
  else { copyFileSync(path.join(root, ".env.agents.example"), config, constants.COPYFILE_EXCL); console.log("Created ignored .env.agents. Fill ANTHROPIC_API_KEY locally; never paste it into chat."); }
} else {
  if (!existsSync(config)) { console.error("Run npm run setup:agents first, then fill ANTHROPIC_API_KEY in .env.agents."); process.exit(1); }
  loadEnvFile(config);
  const result = spawnSync(python, ["scripts/check-agent-config.py"], { cwd: root, env: process.env, stdio: "inherit", windowsHide: true });
  if (result.error || result.status !== 0) process.exit(result.status || 1);
  if (!process.argv.includes("--check")) await import("./dev.mjs");
}

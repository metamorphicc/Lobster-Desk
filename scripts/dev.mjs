import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { root, python } from "./python.mjs";

if (!existsSync(python)) { console.error("Create .venv and install apps/api[dev] first. See README.md."); process.exit(1); }
const next = path.join(root, "node_modules/next/dist/bin/next");
if (!existsSync(next)) { console.error("Run npm install first."); process.exit(1); }
const children = [];
let stopping = false;
function stop() {
  if (stopping) return;
  stopping = true;
  for (const child of children) {
    if (process.platform === "win32") spawn("taskkill", ["/PID", String(child.pid), "/T", "/F"], { windowsHide: true, stdio: "ignore" });
    else child.kill("SIGTERM");
  }
}
function run(command, args, cwd) {
  const child = spawn(command, args, { cwd, stdio: "inherit", shell: false, windowsHide: true });
  children.push(child);
  child.on("error", error => { console.error(error.message); process.exitCode = 1; stop(); });
  child.on("exit", code => { if (!stopping) { process.exitCode = code || 0; stop(); } });
}
console.log("Claw Desk — http://127.0.0.1:3000 — local paper execution only");
run(python, ["-m", "uvicorn", "lobster.main:create_app", "--factory", "--app-dir", "apps/api", "--host", "127.0.0.1", "--port", "8000"], root);
run(process.execPath, [next, "dev", "--hostname", "127.0.0.1", "--port", "3000"], path.join(root, "apps/web"));
process.on("SIGINT", stop);
process.on("SIGTERM", stop);


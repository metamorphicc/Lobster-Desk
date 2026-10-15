import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

export const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const python = path.join(root, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
if (process.argv[1] === fileURLToPath(import.meta.url)) {
  if (!existsSync(python)) { console.error("Create the virtual environment and install apps/api[dev] first. See README.md."); process.exit(1); }
  const result = spawnSync(python, process.argv.slice(2), { cwd: root, stdio: "inherit", shell: false });
  process.exit(result.status ?? 1);
}


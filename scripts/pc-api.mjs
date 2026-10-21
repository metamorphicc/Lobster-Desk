import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { randomBytes } from "node:crypto";
import { loadEnvFile } from "node:process";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { root, python } from "./python.mjs";

const config = path.join(root, ".env.pc");
if (process.argv.includes("--setup")) {
  if (existsSync(config)) console.log(".env.pc exists and was preserved. No secrets were read or printed.");
  else {
    const source = readFileSync(path.join(root, ".env.pc.example"), "utf8")
      .replace(/^PROXY_TOKEN=$/m, `PROXY_TOKEN=${randomBytes(48).toString("base64url")}`)
      .replace(/^OPERATOR_TOKEN=$/m, `OPERATOR_TOKEN=${randomBytes(48).toString("base64url")}`);
    writeFileSync(config, source, { flag: "wx", mode: 0o600 });
    console.log("Created ignored .env.pc with separate proxy/operator secrets. Set WEB_ORIGIN locally. No server or tunnel was started.");
  }
} else {
  if (!existsSync(config)) { console.error("Run npm run setup:pc first, then fill WEB_ORIGIN in .env.pc."); process.exit(1); }
  loadEnvFile(config);
  const validation = `from lobster.config import Settings
import sys
try:
    c = Settings()
    assert c.deployment_mode == 'public-single-host'
except Exception:
    print('PC API configuration is invalid. Check WEB_ORIGIN and separate proxy/operator secrets in .env.pc. Values withheld.', file=sys.stderr)
    sys.exit(1)
print('PC API configuration valid. No credential values printed.')
`;
  const check = spawnSync(python, ["-c", validation],
    { cwd: root, env: { ...process.env, PYTHONPATH: path.join(root, "apps/api") }, stdio: "inherit", windowsHide: true });
  if (check.error || check.status !== 0) process.exit(check.status || 1);
  if (!process.argv.includes("--check")) {
    const result = spawnSync(python, ["-m", "uvicorn", "lobster.main:create_app", "--factory", "--app-dir", "apps/api", "--host", "127.0.0.1", "--port", "8000"],
      { cwd: root, env: process.env, stdio: "inherit", windowsHide: true });
    process.exit(result.status ?? 1);
  }
}

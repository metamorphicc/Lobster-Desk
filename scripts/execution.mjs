import {existsSync} from "node:fs";
import {loadEnvFile} from "node:process";
import path from "node:path";
import {spawn} from "node:child_process";
import {root, python} from "./python.mjs";

const preset = path.join(root, ".env.agents");
if (existsSync(preset)) loadEnvFile(preset);
const child = spawn(python, ["scripts/project-runner.py", ...process.argv.slice(2)], {cwd:root,stdio:"inherit",windowsHide:true});
child.on("error",()=>{console.error("Project runner unavailable. Check the local Python runtime.");process.exitCode=1;});
child.on("exit",code=>{process.exitCode=code ?? 1;});
process.on("SIGINT",()=>child.kill("SIGINT"));
process.on("SIGTERM",()=>child.kill("SIGTERM"));

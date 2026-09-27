import {copyFile, mkdir, readFile, writeFile, rm, lstat, realpath} from "node:fs/promises";
import {existsSync} from "node:fs";
import path from "node:path";
import {fileURLToPath} from "node:url";
import {createHash} from "node:crypto";
import {build} from "esbuild";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "../..");
const dist = path.join(here, "dist");
const runtime = path.join(here, "node_modules/pyodide");
const teamSource = path.join(root, "web/team-simulator");
const teamGenerated = path.join(teamSource, "generated");
const packageData = JSON.parse(await readFile(path.join(runtime, "package.json"), "utf8"));
if (packageData.version !== "314.0.7") throw new Error(`Expected pinned Pyodide 314.0.7; found ${packageData.version}`);
const runtimeFiles = ["pyodide.mjs", "pyodide.asm.mjs", "pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json"];
const sourceFiles = ["simulator.py", "arm_simulator.py", "arm_handoff.py"];
// Validate the exact intended output directory before deleting prior build output.
if (path.dirname(dist) !== here || path.basename(dist) !== "dist") throw new Error("Invalid static output path");
if (existsSync(dist)) {
  if ((await lstat(dist)).isSymbolicLink() || await realpath(dist) !== dist) throw new Error("Refusing linked static output directory");
  await rm(dist, {recursive: true});
}
await mkdir(path.join(dist, "static"), {recursive: true});
await mkdir(path.join(dist, "runtime"), {recursive: true});
await mkdir(path.join(dist, "python/relay_gateway"), {recursive: true});
await mkdir(path.join(dist, "static/team-simulator/generated"), {recursive: true});
await mkdir(path.join(dist, "licenses"), {recursive: true});
for (const file of ["simulator.js", "arm-simulator.js"]) await copyFile(path.join(root, "web", file), path.join(dist, "static", file));
await copyFile(path.join(here, "boot.js"), path.join(dist, "boot.js"));
await copyFile(path.join(here, "worker.mjs"), path.join(dist, "worker.mjs"));
for (const file of ["workflow-proof.html", "workflow-proof.css"]) await copyFile(path.join(here, file), path.join(dist, file));
// Bundle only the teammate's browser scene. No Fleet API, Bluetooth, or backend
// module is an entry point. Keep identical local and hosted static asset paths.
if (existsSync(teamGenerated) && ((await lstat(teamGenerated)).isSymbolicLink() || await realpath(teamGenerated) !== teamGenerated)) {
  throw new Error("Refusing linked teammate simulator output directory");
}
await mkdir(teamGenerated, {recursive: true});
const teamBuild = await build({
  entryPoints: [path.join(teamSource, "main.tsx")], outfile: path.join(teamGenerated, "street.js"),
  bundle: true, write: false, format: "esm", platform: "browser", target: ["es2022"],
  jsx: "automatic", minify: true, sourcemap: false, legalComments: "external", metafile: true,
  nodePaths: [path.join(here, "node_modules")], define: {"process.env.NODE_ENV": '"production"'},
});
for (const output of teamBuild.outputFiles) {
  const name = path.basename(output.path);
  if (!["street.js", "street.js.LEGAL.txt"].includes(name)) throw new Error("Unexpected teammate bundle output");
  await writeFile(path.join(teamGenerated, name), output.contents);
  await writeFile(path.join(dist, "static/team-simulator/generated", name), output.contents);
}
await copyFile(path.join(teamSource, "style.css"), path.join(dist, "static/team-simulator/style.css"));
await copyFile(path.join(teamSource, "provenance.json"), path.join(dist, "team-simulator-provenance.json"));
for (const name of ["react", "react-dom", "scheduler", "lucide-react"]) {
  await copyFile(path.join(here, "node_modules", name, "LICENSE"), path.join(dist, "licenses", `${name}.txt`));
}
const teamHashes = {};
for (const name of ["RoverDemo.tsx", "contracts.ts", "main.tsx", "fixtures.json", "provenance.json", "style.css"]) {
  teamHashes[name] = createHash("sha256").update(await readFile(path.join(teamSource, name))).digest("hex");
}
for (const file of runtimeFiles) await copyFile(path.join(runtime, file), path.join(dist, "runtime", file));
for (const file of ["LICENSE", "LICENSE.md", "LICENSE.txt"]) {
  if (existsSync(path.join(runtime, file))) await copyFile(path.join(runtime, file), path.join(dist, "runtime", file));
}
for (const file of ["PYODIDE-LICENSE", "PYODIDE-NOTICE"]) await copyFile(path.join(here, "third-party", file), path.join(dist, "runtime", file));
await writeFile(path.join(dist, "python/relay_gateway/__init__.py"), "# Isolated browser simulation package. No application or hardware imports.\n");
const hashes = {};
for (const file of sourceFiles) {
  const data = await readFile(path.join(root, "src/relay_gateway", file));
  await writeFile(path.join(dist, "python/relay_gateway", file), data);
  hashes[file] = createHash("sha256").update(data).digest("hex");
}
const bannerCss = `\n.browser-boot{margin:20px 0 0;padding:15px 18px;border:1px solid #ccdcbc;background:#eaf2df;border-radius:8px;display:flex;gap:12px;align-items:center;justify-content:space-between}.browser-boot strong{font-size:12px;color:#547443;display:block}.browser-boot p{font-size:10px;line-height:1.6;color:#7d9070;margin:5px 0 0}.browser-boot button{font-size:10px;padding:9px 12px;background:#fff9ee;border:1px solid #d4b893;border-radius:5px;color:#845e33;white-space:nowrap}.browser-boot-failed{background:#f9eee1;border-color:#e6ccb0}.browser-boot-failed strong{color:#976435}.browser-boot-ready{background:#edf4e7}@media(max-width:620px){.browser-boot{padding:13px;align-items:flex-start;flex-direction:column}.browser-boot strong{font-size:11px}.browser-boot p{font-size:9px}}\n`;
const sessionCss = `\n.browser-reset-group{flex:0 1 320px;min-width:210px}.browser-boot .browser-reset-group button{background:#176c57;color:white;border:1px solid #176c57;font-size:12px;font-weight:650;min-height:44px;padding:11px 18px;cursor:pointer}.browser-boot .browser-reset-group button:hover{background:#115442}.browser-boot .browser-reset-group p{font-size:10px;color:#596d50;line-height:1.5}.browser-boot .browser-technologies{font-weight:650;color:#3e6745;margin-top:9px}.browser-boot button:focus-visible{outline:3px solid #d4963e;outline-offset:3px}@media(max-width:620px){.browser-reset-group{flex:auto;width:100%;min-width:0}.browser-reset-group button{width:100%}}\n`;
await writeFile(path.join(dist, "static/simulator.css"), await readFile(path.join(root, "web/simulator.css"), "utf8") + bannerCss + sessionCss);
let html = await readFile(path.join(root, "web/simulator.html"), "utf8");
for (const file of ["simulator.js", "arm-simulator.js"]) html = html.replace(`<script src="/static/${file}" defer></script>`, "");
html = html.replace("</head>", '<script type="module" src="/boot.js"></script>\n</head>');
html = html.replace('<a href="/">Mission lab</a>', "");
html = html.replace('<nav aria-label="Main navigation">', '<nav aria-label="Main navigation"><a href="/workflow-proof.html">AI workflow</a>');
html = html.replace("<main>", '<main>\n<section id="browser-boot" class="browser-boot" aria-label="Simulation session"><div><div role="status" aria-live="polite"><strong id="browser-boot-status">Preparing the browser simulation engine…</strong><p id="browser-boot-detail">JavaScript, WebAssembly, and module workers are required. Each browser tab runs an independent simulation.</p></div><p class="browser-technologies">Python · Pyodide · WebAssembly · Hosted on Vercel</p><button id="browser-boot-retry" type="button" hidden>Reload simulator</button></div><div class="browser-reset-group"><button id="browser-reset-all" type="button" aria-describedby="browser-reset-help">↻ Reset all simulations</button><p id="browser-reset-help">Restarts fleet, street and arm. Clears findings, faults and taught virtual poses in this tab.</p></div></section>');
html = html.replace("<title>FieldSight — Robotics simulator</title>", "<title>FieldSight — Browser robotics simulator</title>");
html = html.replace("</footer>", '<a href="/runtime/PYODIDE-NOTICE" target="_blank" rel="noopener noreferrer">Python runtime · Pyodide 314.0.7</a></footer>');
await writeFile(path.join(dist, "index.html"), html);
await writeFile(path.join(dist, "simulator.html"), html);
await writeFile(path.join(dist, "build-manifest.json"), JSON.stringify({runtime: "pyodide", runtime_version: packageData.version, simulated: true, physical_connections: false, source_sha256: hashes,
  teammate_simulator: {runtime: "react_browser", source_sha256: teamHashes,
    javascript_bytes: teamBuild.outputFiles.find((file) => file.path.endsWith("street.js")).contents.length,
    upstream_provenance: "/team-simulator-provenance.json", model_calls: 0, physical_commands: 0}}, null, 2) + "\n");
console.log(`Built isolated static simulator at ${dist}; Pyodide ${packageData.version}; ${sourceFiles.length} exact Python modules.`);

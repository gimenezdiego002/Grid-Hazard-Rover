// Package only the reviewed static build; source, accounts and ledgers stay local.
import {cp, lstat, mkdir, readdir, readFile, realpath, rm, writeFile} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const root = path.dirname(fileURLToPath(import.meta.url));
const source = path.resolve(root, 'dist');
const output = path.resolve(root, '.vercel/output');
if (output !== path.join(root, '.vercel', 'output') || source !== path.join(root, 'dist')) {
  throw new Error('Static package paths escaped the deployment workspace');
}
const canonicalRoot = await realpath(root);
for (const relative of ['dist', '.vercel', '.vercel/output']) {
  const candidate = path.join(root, relative);
  try {
    if ((await lstat(candidate)).isSymbolicLink() ||
        await realpath(candidate) !== path.join(canonicalRoot, relative)) {
      throw new Error('Refusing a linked deployment directory');
    }
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
  }
}
const forbidden = /(^|\/)(?:\.state|\.env[^/]*|\.git|\.venv|node_modules|credentials[^/]*|service-account[^/]*)(\/|$)|\.(?:sqlite|db|pem|key|pfx)$/i;
async function audit(directory, relative = '') {
  const files = [];
  for (const entry of await readdir(directory, {withFileTypes: true})) {
    const name = relative ? `${relative}/${entry.name}` : entry.name;
    if (forbidden.test(name) || entry.isSymbolicLink()) throw new Error(`Unsafe deployment path: ${name}`);
    if (entry.isDirectory()) files.push(...await audit(path.join(directory, entry.name), name));
    else if (entry.isFile()) files.push(name);
    else throw new Error(`Unexpected deployment entry: ${name}`);
  }
  return files;
}
const files = await audit(source);
if (!files.includes('index.html') || !files.includes('runtime/pyodide.asm.wasm')) {
  throw new Error('Build the complete static simulator before preparing Vercel');
}
const config = JSON.parse(await readFile(path.join(root, 'vercel-output-config.json'), 'utf8'));
await rm(output, {recursive: true, force: true});
await mkdir(output, {recursive: true});
await cp(source, path.join(output, 'static'), {recursive: true});
await writeFile(path.join(output, 'config.json'), `${JSON.stringify(config, null, 2)}\n`);
console.log(JSON.stringify({static_files: files.length, functions: 0, output}));

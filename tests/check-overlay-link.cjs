// Link the actual renderer dependency graph in V8 without evaluating app code.
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const selected = process.env.BETTER_CODEX_TEST_DEPLOYMENT || fs.readFileSync(path.join(root, '.local/deployment-path.txt'), 'utf8').trim();
const deployment = path.resolve(root, selected);
const manifest = JSON.parse(fs.readFileSync(path.join(deployment, 'Deployment.json'), 'utf8'));
const overlay = JSON.parse(fs.readFileSync(path.join(deployment, 'Provider-Overlay.json'), 'utf8'));
const archive = fs.openSync(path.join(manifest.source_app, 'resources/app.asar'), 'r');
function read(offset, length) {
  const data = Buffer.alloc(length);
  assert.equal(fs.readSync(archive, data, 0, length, offset), length);
  return data;
}
const headerSize = read(0, 8).readUInt32LE(4);
const header = read(8, headerSize);
const tree = JSON.parse(header.subarray(8, 8 + header.readUInt32LE(4)).toString()).files;
const overrides = new Map([[`webview/assets/${overlay.filename}`, 'Provider-Overlay.source.js'],
  ...overlay.additional_assets.map(asset => [`webview/assets/${asset.filename}`, asset.source_file])]);
const modules = new Map();
function moduleAt(identifier, patched = true) {
  const key = `${patched}:${identifier}`;
  if (modules.has(key)) return modules.get(key);
  let entry = {files: tree};
  for (const part of identifier.split('/')) entry = entry.files[part];
  assert.ok(entry && !entry.unpacked, `Missing packed renderer module ${identifier}`);
  const bytes = read(8 + headerSize + Number(entry.offset), entry.size);
  assert.equal(crypto.createHash('sha256').update(bytes).digest('hex'), entry.integrity.hash);
  const source = patched && overrides.has(identifier)
    ? fs.readFileSync(path.join(deployment, overrides.get(identifier)), 'utf8') : bytes.toString();
  const module = new vm.SourceTextModule(source, {identifier});
  modules.set(key, module);
  return module;
}
async function link(patched) {
  for (const identifier of overrides.keys()) {
    const module = moduleAt(identifier, patched);
    if (module.status !== 'unlinked') continue;
    await module.link((specifier, parent) => {
      assert.ok(specifier.startsWith('./') || specifier.startsWith('../'), 'Only local renderer dependencies are allowed');
      return moduleAt(path.posix.normalize(path.posix.join(path.posix.dirname(parent.identifier), specifier)), patched);
    });
  }
}
(async () => {
  await link(false);
  await link(true);
  console.log(`PASS: original and custom renderer/settings module graphs link in V8 (${modules.size} modules); no app code executed.`);
})().catch(error => { console.error(error.message); process.exitCode = 1; }).finally(() => fs.closeSync(archive));

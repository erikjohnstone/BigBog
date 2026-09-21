/**
 * Bundle budget: the shell must paint before any canvas library downloads.
 * The entry chunk stays under 350 kB gzip and the heavy runtimes (three,
 * xyflow, uplot) are their own lazily loaded chunks.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { gzipSync } from 'node:zlib';

const assets = join(process.cwd(), '..', 'src', 'bactalk', 'static-next', 'assets');
const ENTRY_BUDGET = 350 * 1024;
const LAZY = ['three', 'xyflow', 'uplot'];

const files = readdirSync(assets).filter((name) => name.endsWith('.js'));
const gz = (name) => gzipSync(readFileSync(join(assets, name))).length;
const entry = files.filter((name) => name.startsWith('index-'));
if (entry.length !== 1) {
  console.error(`expected one entry chunk, found ${entry.length}`);
  process.exit(1);
}
const html = readFileSync(join(assets, '..', 'index.html'), 'utf8');
// The budget covers everything the shell loads before it paints: the entry
// plus every chunk index.html preloads.
const eager = files.filter((name) => html.includes(name));
const entrySize = eager.reduce((sum, name) => sum + gz(name), 0);
let failed = false;
console.log(`eager (${eager.join(', ')}): ${(entrySize / 1024).toFixed(1)} kB gzip (budget ${ENTRY_BUDGET / 1024} kB)`);
if (entrySize > ENTRY_BUDGET) {
  console.error('the eagerly loaded chunks exceed the budget');
  failed = true;
}
for (const lib of LAZY) {
  const chunk = files.find((name) => name.startsWith(`${lib}-`));
  if (!chunk) {
    console.error(`no separate chunk for ${lib}`);
    failed = true;
    continue;
  }
  const eager = html.includes(chunk);
  console.log(`${chunk}: ${(gz(chunk) / 1024).toFixed(1)} kB gzip, ${statSync(join(assets, chunk)).size} bytes raw, ${eager ? 'EAGER' : 'lazy'}`);
  if (eager) {
    console.error(`${lib} is referenced from index.html; it must load lazily`);
    failed = true;
  }
}
process.exit(failed ? 1 : 0);

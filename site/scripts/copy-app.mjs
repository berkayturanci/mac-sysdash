// Copy the live dashboard (repo-root index.html + its assets) into public/demo/
// so the marketing site can host an interactive ?demo build with no backend.
// Runs automatically on `prebuild`, so the demo never drifts from the real app.
import { mkdirSync, copyFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url)); // site/scripts
const repo = join(here, '..', '..');                  // repo root
const out = join(here, '..', 'public', 'demo');       // site/public/demo
mkdirSync(out, { recursive: true });

// Everything the app references with a relative path — so it resolves under
// /mac-sysdash/demo/ exactly as it does when opened locally.
const files = [
  'index.html',
  'sw.js',
  'manifest.webmanifest',
  'icon.svg',
  'icon-180.png',
  'icon-192.png',
  'icon-512.png',
];
for (const f of files) copyFileSync(join(repo, f), join(out, f));
console.log(`[copy-app] copied ${files.length} app files into public/demo/`);

#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const srcDir = path.join(root, 'frontend-react', 'src');
const deModule = await import(pathToFileURL(path.join(srcDir, 'i18n', 'de.js')).href);
const enModule = await import(pathToFileURL(path.join(srcDir, 'i18n', 'en.js')).href);

function flatten(value, prefix = '', output = new Set()) {
  if (!value || typeof value !== 'object') {
    if (prefix) output.add(prefix);
    return output;
  }
  for (const [key, child] of Object.entries(value)) {
    const next = prefix ? `${prefix}.${key}` : key;
    if (child && typeof child === 'object' && !Array.isArray(child)) flatten(child, next, output);
    else output.add(next);
  }
  return output;
}

function walk(dir, files = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === 'node_modules' || entry.name === 'dist') continue;
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(fullPath, files);
    else if (/\.(jsx?|tsx?)$/.test(entry.name)) files.push(fullPath);
  }
  return files;
}

const used = new Map();
const keyPattern = /\bt(?:\?\.)?\(\s*(['"`])([^'"`$\n]+)\1/g;
for (const file of walk(srcDir)) {
  const text = fs.readFileSync(file, 'utf8');
  for (const match of text.matchAll(keyPattern)) {
    const key = match[2];
    if (!used.has(key)) used.set(key, []);
    used.get(key).push(path.relative(root, file));
  }
}

const deKeys = flatten(deModule.de);
const enKeys = flatten(enModule.en);
const usedKeys = [...used.keys()].sort();
const missingDe = usedKeys.filter((key) => !deKeys.has(key));
const missingEn = usedKeys.filter((key) => !enKeys.has(key));

function printMissing(label, keys) {
  if (!keys.length) return;
  console.error(`\n${label}:`);
  for (const key of keys) {
    const locations = [...new Set(used.get(key) || [])].slice(0, 4).join(', ');
    console.error(`- ${key} (${locations})`);
  }
}

console.log(`React i18n audit: ${usedKeys.length} keys used, ${deKeys.size} DE keys, ${enKeys.size} EN keys.`);
printMissing('Missing German keys', missingDe);
printMissing('Missing English keys', missingEn);

if (missingDe.length || missingEn.length) {
  process.exitCode = 1;
}

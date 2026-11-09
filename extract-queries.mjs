// Liest die Overpass-Abfragen direkt aus der Karte (index.html) und schreibt queries.json.
// So bleiben Datenstand und App automatisch synchron: ändert sich eine Abfrage in der App,
// ändert sich ihr Schlüssel (SHA-256 des Abfragetextes) und der Workflow lädt sie neu.
//
//   node extract-queries.mjs https://karte.lupos.li/ queries.json
//   node extract-queries.mjs ./index.html queries.json
import { readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';

const [src = 'https://karte.lupos.li/', out = 'queries.json'] = process.argv.slice(2);
const html = /^https?:/.test(src)
  ? await (await fetch(src, { headers: { 'User-Agent': 'oesterreich-karte-daten/1.0' } })).text()
  : await readFile(src, 'utf8');
const lines = html.split('\n');

// Ausschnitt ab „const NAME“ bis zum Zeilenende-Muster holen
function block(start, endRx, single = false) {
  const i = lines.findIndex(l => l.startsWith(start));
  if (i < 0) throw new Error(`Nicht gefunden in der Karte: ${start}`);
  if (single) return lines[i];
  for (let j = i; j < lines.length; j++) if (endRx.test(lines[j])) return lines.slice(i, j + 1).join('\n');
  throw new Error(`Ende nicht gefunden: ${start}`);
}
// Der ganze Themen-Abschnitt: Definition, spätere THEMES.push(...) und nachträglich ergänzte Abfragen.
// Von „const T = “ bis zur letzten Zeile „for (const th of THEMES) …“ nach dem letzten THEMES.push.
function themesBlock() {
  const i = lines.findIndex(l => l.startsWith('const T = '));
  let p = -1; lines.forEach((l, k) => { if (l.startsWith('THEMES.push(')) p = k; });
  const j = lines.findIndex((l, k) => k > Math.max(i, p) && l.startsWith('for (const th of THEMES)'));
  if (i < 0 || j < 0) throw new Error('Themen-Abschnitt nicht gefunden');
  return lines.slice(i, j + 1).join('\n');
}
const code = [
  block('const AREA_AT', null, true),
  ...['Q_POLY', 'Q_DOC', 'Q_DENT', 'Q_ADM'].map(n => block(`const ${n} = \``, /`;\s*$/)),
  themesBlock(),
  block('const themeQuery', null, true),
  block('function snapshotQueries(', /^}\s*$/),
  'return snapshotQueries();',
].join('\n');

// Alles, was die Themen-Definitionen sonst noch brauchen (Farben, Hilfsfunktionen), durch Platzhalter ersetzen
const stub = new Proxy(function () { return stub; }, { get: (t, k) => (k === Symbol.toPrimitive ? () => '' : stub) });
const scope = new Proxy({}, {
  has: (_, k) => !(k in globalThis),
  get: (_, k) => (k === Symbol.unscopables ? undefined : stub),
});
const list = new Function('scope', `with (scope) { ${code} }`)(scope);

const queries = list.map(({ label, q }) => ({
  key: createHash('sha256').update(q, 'utf8').digest('hex').slice(0, 16), label, q,
}));
if (queries.length < 5) throw new Error(`Zu wenige Abfragen gefunden (${queries.length})`);
await writeFile(out, JSON.stringify(queries, null, 1) + '\n');
console.log(`${queries.length} Abfragen nach ${out} geschrieben`);

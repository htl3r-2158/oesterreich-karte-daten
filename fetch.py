#!/usr/bin/env python3
"""Holt alle Abfragen aus queries.json bei Overpass und schreibt komprimierte Dateien.

Läuft täglich in GitHub Actions. Ergebnis in --out:
  files/<schlüssel>.json.gz   ein Paket je Abfrage (minimiertes JSON, gzip)
  manifest.partial.json       Inhaltsverzeichnis (ohne Commit-SHA, die setzt der Workflow)

Scheitert eine Abfrage trotz aller Versuche, wird die Datei vom letzten Lauf übernommen
(sofern nicht älter als --keep-days). So bleibt die Karte bei Overpass-Ausfällen benutzbar.
Nur Python-Standardbibliothek.
"""
import argparse, concurrent.futures as cf, gzip, json, os, sys, threading, time, urllib.error, urllib.parse, urllib.request

ENDPOINTS = [
    'https://overpass-api.de/api/interpreter',
    'https://overpass.private.coffee/api/interpreter',
    'https://overpass.kumi.systems/api/interpreter',
    'https://maps.mail.ru/osm/tools/overpass/api/interpreter',
]
UA = 'oesterreich-karte-daten/1.0 (+https://karte.lupos.li; taeglicher Datenstand)'
WAITS = [0, 60, 180, 420, 900]          # Pausen zwischen den Runden über alle Server (Sekunden)
LOCK = threading.Lock()
BUSY = {e: 0 for e in ENDPOINTS}         # pro Server höchstens eine Abfrage gleichzeitig


def log(*a):
    with LOCK:
        print(time.strftime('%H:%M:%S'), *a, flush=True)


def get(url, timeout=60):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def overpass(ep, q):
    data = urllib.parse.urlencode({'data': q}).encode()
    req = urllib.request.Request(ep, data=data, headers={'User-Agent': UA, 'Referer': 'https://karte.lupos.li/',
                                                         'Content-Type': 'application/x-www-form-urlencoded'})
    with urllib.request.urlopen(req, timeout=420) as r:
        body = r.read()
    j = json.loads(body)
    rem = j.get('remark') or ''
    if any(w in rem.lower() for w in ('error', 'timed out', 'runtime', 'out of memory')):
        raise RuntimeError(rem[:160])
    if not isinstance(j.get('elements'), list):
        raise RuntimeError('keine elements in der Antwort')
    return j


def pick():
    with LOCK:
        ep = min(ENDPOINTS, key=lambda e: BUSY[e])
        BUSY[ep] += 1
        return ep


def release(ep):
    with LOCK:
        BUSY[ep] -= 1


def fetch_one(item):
    """Probiert alle Server, mehrere Runden mit wachsenden Pausen."""
    errs = []
    for rnd, wait in enumerate(WAITS):
        if wait:
            log(f"  {item['label']}: Runde {rnd + 1} in {wait} s")
            time.sleep(wait)
        tried = set()
        while len(tried) < len(ENDPOINTS):
            ep = pick()
            if ep in tried:
                release(ep)
                ep = next(e for e in ENDPOINTS if e not in tried)
                with LOCK:
                    BUSY[ep] += 1
            tried.add(ep)
            host = urllib.parse.urlsplit(ep).hostname
            t0 = time.time()
            try:
                j = overpass(ep, item['q'])
                log(f"OK  {item['label']} von {host} in {time.time() - t0:.0f} s, {len(j['elements'])} Objekte")
                return j, errs
            except urllib.error.HTTPError as e:
                errs.append(f'{host}: HTTP {e.code}')
                if e.code == 429:
                    time.sleep(30)
            except Exception as e:
                errs.append(f'{host}: {str(e)[:120]}')
            finally:
                release(ep)
    return None, errs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--queries', default='queries.json')
    ap.add_argument('--out', default='out')
    ap.add_argument('--repo', default=os.environ.get('GITHUB_REPOSITORY', ''))
    ap.add_argument('--parallel', type=int, default=2)
    ap.add_argument('--keep-days', type=float, default=14)
    a = ap.parse_args()

    queries = json.load(open(a.queries, encoding='utf-8'))
    os.makedirs(os.path.join(a.out, 'files'), exist_ok=True)

    # Vorheriger Datenstand: Ersatz für Abfragen, die heute scheitern
    prev = {}
    if a.repo:
        try:
            pm = json.loads(get(f'https://raw.githubusercontent.com/{a.repo}/data/manifest.json'))
            prev = {k: dict(v, sha=pm.get('sha')) for k, v in pm.get('files', {}).items()}
            log(f'Vorheriger Datenstand: {len(prev)} Pakete')
        except Exception as e:
            log(f'Kein vorheriger Datenstand ({e})')

    files, failed = {}, []

    def work(item):
        j, errs = fetch_one(item)
        key, path = item['key'], f"files/{item['key']}.json.gz"
        if j is not None:
            raw = json.dumps({'elements': j['elements']}, ensure_ascii=False, separators=(',', ':')).encode()
            gz = gzip.compress(raw, 9, mtime=0)
            with open(os.path.join(a.out, path), 'wb') as f:
                f.write(gz)
            return key, {'f': path, 't': int(time.time() * 1000), 'n': len(j['elements']), 'raw': len(raw), 'gz': len(gz), 'label': item['label']}, None
        p = prev.get(key)
        if p and p.get('sha') and time.time() * 1000 - p['t'] < a.keep_days * 864e5:
            try:
                gz = get(f"https://raw.githubusercontent.com/{a.repo}/{p['sha']}/{p['f']}", timeout=180)
                with open(os.path.join(a.out, path), 'wb') as f:
                    f.write(gz)
                log(f"ALT {item['label']}: Overpass gescheitert, Datei vom {time.strftime('%d.%m.', time.localtime(p['t'] / 1000))} übernommen")
                return key, {k: v for k, v in p.items() if k != 'sha'} | {'f': path, 'old': True}, errs
            except Exception as e:
                errs.append(f'alter Stand: {e}')
        log(f"FEHLT {item['label']}: " + ' | '.join(errs[-4:]))
        return key, None, errs

    with cf.ThreadPoolExecutor(max_workers=max(1, min(a.parallel, len(ENDPOINTS)))) as ex:
        for key, entry, errs in ex.map(work, queries):
            if entry:
                files[key] = entry
            if errs and (not entry or entry.get('old')):
                failed.append({'key': key, 'errors': errs[-6:]})

    man = {'generated': int(time.time() * 1000), 'files': files, 'failed': failed,
           'count': len(queries), 'ok': len(files)}
    json.dump(man, open(os.path.join(a.out, 'manifest.partial.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    total = sum(v['gz'] for v in files.values())
    log(f'Fertig: {len(files)}/{len(queries)} Pakete, {total / 1e6:.1f} MB komprimiert, {len(failed)} mit Problemen')
    if not files:
        sys.exit('Kein einziges Paket geladen, Datenstand wird nicht veröffentlicht.')


if __name__ == '__main__':
    main()

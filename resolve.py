"""Звідки брати набори ДСА: спершу data.gov.ua, а якщо портал недоступний — сайт ДСА (dsa.court.gov.ua, «Відкриті дані»).

Запуск:
  python3 resolve.py hearings  -> «URL<TAB>MOD»   (Список справ призначених до розгляду)
  python3 resolve.py status    -> «URL»           (Стан розгляду справ, лише ZIP з data.gov.ua; на сайті ДСА — CSV, пропускаємо)
  python3 resolve.py edrsr     -> рядки «РІК<TAB>URL» (ЄДРСР за поточний і два попередні роки)
Код виходу 1 — жодне джерело не відповіло.
"""
import datetime
import json
import subprocess
import sys

API = 'https://data.gov.ua/api/3/action'
DSA = 'https://dsa.court.gov.ua/open_data_json.php?json='
DSA_HEARINGS = 513
DSA_EDRSR = {2024: 829, 2025: 879, 2026: 7636}  # нові роки додаються на сайті ДСА з новими номерами


def get(url, timeout=60):
    r = subprocess.run(['curl', '-fsS', '--retry', '2', '-m', str(timeout), url], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr.strip() or f'curl {r.returncode}')
    return json.loads(r.stdout)


def last_modified(url):
    r = subprocess.run(['curl', '-fsSI', '-m', '60', url], capture_output=True, text=True)
    for line in r.stdout.splitlines():
        if line.lower().startswith('last-modified:'):
            return 'dsa:' + line.split(':', 1)[1].strip()
    return 'dsa:' + datetime.date.today().isoformat()


def dsa_files(ds):
    files = get(DSA + str(ds)).get('Файли') or []
    return [(name, url) for f in files for name, url in f.items()]


def hearings():
    try:
        r = get(f'{API}/resource_show?id=98d6ba0d-1c18-4835-ae68-bfc0af724bfa')['result']
        return f"{r['url']}\t{r.get('last_modified') or ''}"
    except Exception as e:
        print(f'data.gov.ua: {e}; беру з сайту ДСА', file=sys.stderr)
    url = next(u for n, u in dsa_files(DSA_HEARINGS) if n.lower().endswith('.csv'))
    return f'{url}\t{last_modified(url)}'


def status():
    rs = [r for r in get(f'{API}/package_show?id=0ad60ea9-b029-456d-abc0-8c77a99b205c')['result']['resources'] if r['url'].endswith('.zip')]
    rs.sort(key=lambda r: r.get('last_modified') or r.get('created') or '')
    return rs[-1]['url'] if rs else ''


def edrsr():
    y = datetime.date.today().year
    want = {str(y - 2), str(y - 1), str(y)}
    found = {}
    try:
        res = get(f'{API}/package_search?q=%D0%84%D0%B4%D0%B8%D0%BD%D0%B8%D0%B9%20%D0%B4%D0%B5%D1%80%D0%B6%D0%B0%D0%B2%D0%BD%D0%B8%D0%B9%20%D1%80%D0%B5%D1%94%D1%81%D1%82%D1%80%20%D1%81%D1%83%D0%B4%D0%BE%D0%B2%D0%B8%D1%85%20%D1%80%D1%96%D1%88%D0%B5%D0%BD%D1%8C&fq=organization:derzhavna-sudova-administratsiia-ukrayiny&rows=100')
        for p in res['result']['results']:
            for r in p.get('resources', []):
                for yy in want:
                    if r.get('url', '').endswith(f'edrsr_data_{yy}.zip'):
                        found[yy] = r['url']
    except Exception as e:
        print(f'data.gov.ua: {e}; беру з сайту ДСА', file=sys.stderr)
    for yy in sorted(want - set(found)):
        ds = DSA_EDRSR.get(int(yy))
        if not ds:
            continue
        try:
            found[yy] = next(u for n, u in dsa_files(ds) if n.lower().endswith('.zip'))
        except Exception as e:
            print(f'ДСА {yy}: {e}', file=sys.stderr)
    return '\n'.join(f'{yy}\t{found[yy]}' for yy in sorted(found))


if __name__ == '__main__':
    kind = sys.argv[1]
    try:
        out = {'hearings': hearings, 'status': status, 'edrsr': edrsr}[kind]()
    except Exception as e:
        print(f'{kind}: {e}', file=sys.stderr)
        sys.exit(1)
    if not out:
        sys.exit(1)
    print(out)

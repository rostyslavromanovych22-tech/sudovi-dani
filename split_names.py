#!/usr/bin/env python3
"""
Індекс сторін справ для моніторингу за ПІБ або назвою.

Вхід: out/p/<суд>_<рік>.json (накопичені учасники: { "номер": [учасники, опис, дата, стадія] }), усі роки.
Записи потерпілих і неповнолітніх в індекс не йдуть; решта справи — йде.

Ключі (усі в нижньому регістрі, латинські літери-двійники замінені кириличними):
  - окреме слово (від 3 літер), крім надто частих;
  - уся назва сторони, якщо в ній до 6 слів: «панасюк олександр петрович»;
  - прізвище й ім'я з ПІБ: «панасюк олександр»;
  - назва в лапках: «мобіус енерджі».

Вихід:
  out/n/<fnv1a32(ключ) % 4096 у hex, 3 знаки>.json   { "ключ": ["номер справи", ...] }
  out/n/common.json   ["слово", ...] — надто часті слова, яких в індексі немає
  meta.json: names_cases, names_words, names_generated

Нормалізація й хеш мають збігатися з src/watches.ts (normName, nameBucket).

Запуск: python3 split_names.py <out_dir>
"""
import datetime
import glob
import json
import os
import re
import sys

BUCKETS = 4096
MAX_CASES_PER_WORD = 50_000
MAX_NAME_WORDS = 6

APOS = re.compile(r"[ʼ’`´‘]")
LATIN = str.maketrans("aceiopxykmthb", "асеіорхукмтнв")
TOKEN = re.compile(r"[a-zа-яґєії'\-]+")
QUOTED = re.compile(r"[\"«“„]([^\"«»“”„]{2,80})[\"»”“]")
HIDDEN = re.compile(r"потерпіл|неповнолітн|малолітн", re.I)
SEGMENT = re.compile(r",(?=\s*[^,]*:)")
NAME_WORD = r"[А-ЯІЇЄҐ][а-яіїєґ'’ʼ\-]+"
PERSON = re.compile(rf"{NAME_WORD} {NAME_WORD} {NAME_WORD}(?:вич|вна|ична|ївна)\b")


def norm(text: str) -> list:
    return TOKEN.findall(APOS.sub("'", text.lower()).translate(LATIN))


def bucket(key: str) -> str:
    h = 0x811C9DC5
    for b in key.encode("utf-8"):
        h ^= b
        h = (h * 0x01000193) & 0xFFFFFFFF
    return f"{h % BUCKETS:03x}"


def keys(involved: str):
    words, names = set(), set()
    for seg in SEGMENT.split(involved):
        role, _, name = seg.partition(":")
        if not name:
            role, name = "", seg
        if HIDDEN.search(role):
            continue
        toks = norm(name)
        words.update(t for t in toks if len(t) >= 3)
        if 2 <= len(toks) <= MAX_NAME_WORDS:
            names.add(" ".join(toks))
        if len(toks) == 3:
            names.add(" ".join(toks[:2]))
        # ПІБ усередині довшого запису: «адвокат Драгомирова Олена Миколаївна, в інтересах ...»
        for person in PERSON.findall(name):
            pt = norm(person)
            names.add(" ".join(pt))
            names.add(" ".join(pt[:2]))
        for q in QUOTED.findall(name):
            qt = norm(q)
            if qt:
                names.add(" ".join(qt))
    return words, names


def main():
    out = sys.argv[1]
    words_index: dict[str, list] = {}
    names_index: dict[str, list] = {}
    cases = 0
    for path in glob.glob(os.path.join(out, "p", "*.json")):
        with open(path, encoding="utf-8") as fh:
            parties = json.load(fh)
        for number, row in parties.items():
            involved = row[0] if row else ""
            if not involved:
                continue
            cases += 1
            words, names = keys(involved)
            for w in words:
                words_index.setdefault(w, []).append(number)
            for n in names - words:
                names_index.setdefault(n, []).append(number)

    if cases < 100_000:
        print(f"ERROR: too few cases ({cases}), skipping")
        sys.exit(1)

    common = sorted(w for w, l in words_index.items() if len(l) > MAX_CASES_PER_WORD)
    buckets: dict[str, dict] = {}
    for w, numbers in words_index.items():
        if len(numbers) <= MAX_CASES_PER_WORD:
            buckets.setdefault(bucket(w), {})[w] = numbers
    for n, numbers in names_index.items():
        buckets.setdefault(bucket(n), {})[n] = numbers

    ndir = os.path.join(out, "n")
    os.makedirs(ndir, exist_ok=True)
    size = biggest = 0
    for b, content in buckets.items():
        p = os.path.join(ndir, f"{b}.json")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(content, fh, ensure_ascii=False, separators=(",", ":"))
        n = os.path.getsize(p)
        size += n
        biggest = max(biggest, n)
    with open(os.path.join(ndir, "common.json"), "w", encoding="utf-8") as fh:
        json.dump(common, fh, ensure_ascii=False, separators=(",", ":"))

    meta_p = os.path.join(out, "meta.json")
    meta = {}
    if os.path.exists(meta_p):
        with open(meta_p, encoding="utf-8") as fh:
            meta = json.load(fh)
    meta["names_cases"] = cases
    meta["names_words"] = len(words_index) - len(common)
    meta["names_keys"] = len(names_index)
    meta["names_generated"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    with open(meta_p, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=1)
    print(f"names cases {cases}, words {meta['names_words']}, names {len(names_index)}, common {len(common)}, files {len(buckets)}, total {size // 1048576}MB, max {biggest // 1024}KB")


if __name__ == "__main__":
    main()

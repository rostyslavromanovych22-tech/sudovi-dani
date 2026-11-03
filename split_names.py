#!/usr/bin/env python3
"""
Індекс сторін справ для моніторингу за ПІБ або назвою.

Вхід: out/p/<суд>_<рік>.json (накопичені учасники: { "номер": [учасники, опис, дата, стадія] }).
Беремо справи поточного й попереднього років. Кримінальні справи й справи про адмінправопорушення
в індекс не йдуть: шукати за ПІБ обвинувачених, потерпілих чи неповнолітніх застосунок не має.

Вихід:
  out/n/<fnv1a32(слово) % 4096 у hex, 3 знаки>.json   { "слово": ["номер справи", ...] }
  out/n/common.json   ["слово", ...] — надто часті слова, яких в індексі немає
  meta.json: names_cases, names_words, names_generated

Нормалізація й хеш мають збігатися з src/watches.ts (nameWords, nameBucket).

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

APOS = re.compile(r"[ʼ’`´‘]")
WORD = re.compile(r"[a-zа-яґєії'\-]{3,}")
EXCLUDED = re.compile(r"обвинувачен|підозрюван|засуджен|потерпіл|неповнолітн|кримінальн|притягається", re.I)


def words(text: str) -> set:
    return set(WORD.findall(APOS.sub("'", text.lower())))


def bucket(word: str) -> str:
    h = 0x811C9DC5
    for b in word.encode("utf-8"):
        h ^= b
        h = (h * 0x01000193) & 0xFFFFFFFF
    return f"{h % BUCKETS:03x}"


def main():
    out = sys.argv[1]
    year = datetime.date.today().year % 100
    wanted = {f"{year:02d}", f"{year - 1:02d}"}
    index: dict[str, list] = {}
    cases = skipped = 0
    for path in glob.glob(os.path.join(out, "p", "*.json")):
        if os.path.basename(path)[:-5].split("_")[-1] not in wanted:
            continue
        with open(path, encoding="utf-8") as fh:
            parties = json.load(fh)
        for number, row in parties.items():
            involved = row[0] if row else ""
            if not involved:
                continue
            if EXCLUDED.search(involved) or EXCLUDED.search(row[1] if len(row) > 1 else ""):
                skipped += 1
                continue
            cases += 1
            for w in words(involved):
                index.setdefault(w, []).append(number)

    if cases < 100_000:
        print(f"ERROR: too few cases ({cases}), skipping")
        sys.exit(1)

    common = sorted(w for w, l in index.items() if len(l) > MAX_CASES_PER_WORD)
    buckets: dict[str, dict] = {}
    for w, numbers in index.items():
        if len(numbers) <= MAX_CASES_PER_WORD:
            buckets.setdefault(bucket(w), {})[w] = numbers

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
    meta["names_words"] = len(index) - len(common)
    meta["names_generated"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    with open(meta_p, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=1)
    print(f"names cases {cases} (excluded {skipped}), words {meta['names_words']}, common {len(common)}, files {len(buckets)}, total {size // 1048576}MB, max {biggest // 1024}KB")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Щоденна нарізка набору ДСА «Список справ призначених до розгляду» (data.gov.ua, CC-BY 4.0)
на маленькі файли за кодом суду і роком з номера справи: 464/3078/26 -> s/464_26.json.

Застосунок завантажує лише файли для своїх справ (кілька КБ замість 400 МБ).

Додатково накопичує учасників справ з усіх засідань (зокрема минулих) у p/<суд>_<рік>.json:
{ "464/3078/26": [учасники, суть, "дата засідання"] }. Попередня версія береться з <prev_dir>,
тож з кожним днем учасників стає більше.

Запуск: python3 split.py <csv> <out_dir> [source_modified] [prev_dir]
"""
import csv
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

csv.field_size_limit(10_000_000)

CASE_RE = re.compile(r"^\s*(\d{1,4})/\d+/(\d{2})")
DATE_RE = re.compile(r"^(\d{2})\.(\d{2})\.(\d{4})(?:\s+(\d{2}):(\d{2}))?")


def main():
    src, out = sys.argv[1], sys.argv[2]
    source_modified = sys.argv[3] if len(sys.argv) > 3 else ""
    prev_dir = sys.argv[4] if len(sys.argv) > 4 else ""
    kyiv_today = (datetime.now(timezone.utc) + timedelta(hours=3)).date()
    keep_from = kyiv_today - timedelta(days=3)

    shards: dict[str, list] = {}
    parties: dict[str, dict[str, list]] = {}  # key -> case -> [involved, description, "YYYY-MM-DD"]
    total = kept = 0

    # учасники з попередньої публікації
    prev_p = os.path.join(prev_dir, "p") if prev_dir else ""
    if prev_p and os.path.isdir(prev_p):
        for fn in os.listdir(prev_p):
            if fn.endswith(".json"):
                try:
                    with open(os.path.join(prev_p, fn), encoding="utf-8") as fh:
                        parties[fn[:-5]] = json.load(fh)
                except (OSError, ValueError):
                    pass
    prev_cases = sum(len(v) for v in parties.values())
    with open(src, encoding="utf-8-sig", newline="") as f:
        rd = csv.reader(f, delimiter="\t", quotechar='"')
        header = next(rd)
        idx = {h.strip(): i for i, h in enumerate(header)}

        def col(row, name):
            i = idx.get(name)
            return row[i].strip() if i is not None and i < len(row) else ""

        for row in rd:
            total += 1
            case = col(row, "case")
            m = CASE_RE.match(case)
            d = DATE_RE.match(col(row, "date"))
            if not m or not d:
                continue
            day = datetime(int(d.group(3)), int(d.group(2)), int(d.group(1))).date()
            key = f"{int(m.group(1))}_{m.group(2)}"
            involved = col(row, "case_involved")
            if involved:
                bucket = parties.setdefault(key, {})
                cur = bucket.get(case)
                iso = day.isoformat()
                if cur is None or iso >= cur[2]:
                    bucket[case] = [involved, col(row, "case_description"), iso]
            if day < keep_from:
                continue
            shards.setdefault(key, []).append([
                col(row, "date"),
                case,
                col(row, "court_name"),
                col(row, "court_room"),
                col(row, "judges"),
                col(row, "case_involved"),
                col(row, "case_description"),
            ])
            kept += 1

    # захист від битого або неповного файлу: краще лишити вчорашні дані
    if kept < 50_000:
        print(f"ERROR: too few rows kept ({kept} of {total}), not publishing")
        sys.exit(1)

    os.makedirs(os.path.join(out, "s"), exist_ok=True)
    sizes = {}
    for key, rows in shards.items():
        rows.sort(key=lambda r: (r[1], r[0]))
        p = os.path.join(out, "s", f"{key}.json")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, ensure_ascii=False, separators=(",", ":"))
        sizes[key] = os.path.getsize(p)

    os.makedirs(os.path.join(out, "p"), exist_ok=True)
    for key, cases in parties.items():
        with open(os.path.join(out, "p", f"{key}.json"), "w", encoding="utf-8") as fh:
            json.dump(cases, fh, ensure_ascii=False, separators=(",", ":"))
    parties_cases = sum(len(v) for v in parties.values())

    meta = {
        "source": "ДСА України, «Список справ призначених до розгляду», data.gov.ua (CC-BY 4.0)",
        "source_modified": source_modified,
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fields": ["date", "case", "court_name", "court_room", "judges", "case_involved", "case_description"],
        "rows_total": total,
        "rows_kept": kept,
        "shards": len(shards),
        "parties_cases": parties_cases,
    }
    with open(os.path.join(out, "meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=1)

    big = sorted(sizes.items(), key=lambda kv: -kv[1])[:5]
    print(f"parties {prev_cases} -> {parties_cases} cases; "
          f"rows {total} kept {kept} shards {len(shards)} "
          f"max {[f'{k}:{v // 1024}KB' for k, v in big]} "
          f"464_26 {sizes.get('464_26', 0) // 1024}KB")


if __name__ == "__main__":
    main()

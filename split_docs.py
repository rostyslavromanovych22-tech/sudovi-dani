#!/usr/bin/env python3
"""
Нарізка ЄДРСР (data.gov.ua, архіви edrsr_data_<рік>.zip) на маленькі файли за кодом суду і роком
з номера справи і залишком середнього числа: 464/3078/26 -> d/464_26_2.json (3078 % 4 = 2). Плюс довідники (суди, форми, категорії).

Рядок: [doc_id, case, judgment_code, adjudication_date YYYY-MM-DD, court_code, judge, category_code, justice_kind]
Текст рішення: https://reyestr.court.gov.ua/Review/<doc_id>

Запуск: python3 split_docs.py <out_dir> <archive.zip> [<archive.zip> ...]
"""
import csv
import io
import json
import os
import re
import sys
import zipfile

csv.field_size_limit(10_000_000)
CASE_RE = re.compile(r"^\s*(\d{1,4})/(\d+)/(\d{2})")
BUCKETS = 4  # великі суди діляться ще на 4 файли за середнім числом номера


def read_table(z: zipfile.ZipFile, name: str):
    with z.open(name) as raw:
        rd = csv.reader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline=""), delimiter="\t", quotechar='"')
        header = next(rd)
        for row in rd:
            yield dict(zip(header, row))


def main():
    out = sys.argv[1]
    archives = sys.argv[2:]
    shards: dict[str, list[str]] = {}
    seen: set[str] = set()
    courts, forms, cats, kinds, instances = {}, {}, {}, {}, {}
    total = 0

    for path in archives:
        with zipfile.ZipFile(path) as z:
            names = {os.path.basename(n): n for n in z.namelist()}
            for r in read_table(z, names["courts.csv"]):
                courts[r["court_code"]] = [r["name"], r.get("instance_code", "")]
            for r in read_table(z, names["judgment_forms.csv"]):
                forms[r["judgment_code"]] = r["name"]
            for r in read_table(z, names["cause_categories.csv"]):
                cats[r["category_code"]] = r["name"]
            for r in read_table(z, names["justice_kinds.csv"]):
                kinds[r["justice_kind"]] = r["name"]
            for r in read_table(z, names["instances.csv"]):
                instances[r["instance_code"]] = r["name"]

            for r in read_table(z, names["documents.csv"]):
                total += 1
                case = (r.get("cause_num") or "").strip()
                m = CASE_RE.match(case)
                doc_id = r.get("doc_id", "")
                if not m or not doc_id or doc_id in seen:
                    continue
                seen.add(doc_id)
                key = f"{int(m.group(1))}_{m.group(3)}_{int(m.group(2)) % BUCKETS}"
                row = [
                    int(doc_id),
                    case,
                    r.get("judgment_code", ""),
                    (r.get("adjudication_date") or "")[:10],
                    r.get("court_code", ""),
                    (r.get("judge") or "").strip(),
                    r.get("category_code", ""),
                    r.get("justice_kind", ""),
                ]
                shards.setdefault(key, []).append(json.dumps(row, ensure_ascii=False, separators=(",", ":")))

    if len(seen) < 100_000:
        print(f"ERROR: too few documents ({len(seen)}), not publishing")
        sys.exit(1)

    os.makedirs(os.path.join(out, "d"), exist_ok=True)
    sizes = {}
    for key, rows in shards.items():
        p = os.path.join(out, "d", f"{key}.json")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("[" + ",".join(rows) + "]")
        sizes[key] = os.path.getsize(p)

    with open(os.path.join(out, "dicts.json"), "w", encoding="utf-8") as fh:
        json.dump({"courts": courts, "forms": forms, "categories": cats, "kinds": kinds, "instances": instances},
                  fh, ensure_ascii=False, separators=(",", ":"))

    big = sorted(sizes.items(), key=lambda kv: -kv[1])[:4]
    print(f"docs rows {total} unique {len(seen)} shards {len(shards)} "
          f"total {sum(sizes.values()) // 1048576}MB max {[f'{k}:{v // 1024}KB' for k, v in big]} "
          f"dicts {os.path.getsize(os.path.join(out, 'dicts.json')) // 1024}KB")


if __name__ == "__main__":
    main()

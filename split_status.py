#!/usr/bin/env python3
"""
Доповнення учасників справ з набору ДСА «Інформація щодо стану розгляду справ»
(data.gov.ua, щоденний ZIP з CSV, роздільник — табуляція).

Колонки: court_name, case_number, case_proc, registration_date, judge, judges, participants,
         stage_date, stage_name, cause_result, cause_dep, type, description

Дописує в out/p/<суд>_<рік>.json, які вже створив split.py:
  { "номер справи": [учасники, суть, "YYYY-MM-DD", "стадія (дд.мм.рррр)"] }
Новіший запис (за датою стадії / реєстрації) замінює старіший; стадія зберігається завжди.

Запуск: python3 split_status.py <out_dir> <archive.zip>
"""
import csv
import io
import json
import os
import re
import sys
import zipfile

csv.field_size_limit(10_000_000)
CASE_RE = re.compile(r"^\s*(\d{1,4})/\d+/(\d{2})(?:-[а-яa-z]+)?\s*$", re.I)
DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")


def iso(d: str) -> str:
    m = DATE_RE.search(d or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else ""


def main():
    out, archive = sys.argv[1], sys.argv[2]
    pdir = os.path.join(out, "p")
    os.makedirs(pdir, exist_ok=True)
    shards: dict[str, dict] = {}
    for fn in os.listdir(pdir):
        if fn.endswith(".json"):
            with open(os.path.join(pdir, fn), encoding="utf-8") as fh:
                shards[fn[:-5]] = json.load(fh)
    before = sum(len(v) for v in shards.values())

    rows = added = updated = staged = 0
    with zipfile.ZipFile(archive) as z:
        for name in sorted(z.namelist()):
            if not name.lower().endswith(".csv"):
                continue
            with z.open(name) as raw:
                rd = csv.reader(io.TextIOWrapper(raw, encoding="utf-8-sig", errors="replace", newline=""),
                                delimiter="\t", quotechar='"')
                header = next(rd, None)
                if not header:
                    continue
                idx = {h.strip(): i for i, h in enumerate(header)}

                def col(row, key):
                    i = idx.get(key)
                    return row[i].strip() if i is not None and i < len(row) else ""

                for row in rd:
                    rows += 1
                    case = col(row, "case_number").replace("№", "").strip()
                    m = CASE_RE.match(case)
                    if not m:
                        continue
                    case = case.split("-")[0] if re.search(r"-[а-яa-z]+$", case, re.I) else case
                    key = f"{int(m.group(1))}_{m.group(2)}"
                    involved = re.sub(r"\s{2,}", " ", col(row, "participants")).strip(" ,")
                    stage_name = col(row, "stage_name")
                    stage_date = col(row, "stage_date")
                    result = col(row, "cause_result")
                    stage = " ".join(x for x in [stage_name or result, f"({stage_date})" if stage_date else ""] if x).strip()
                    when = iso(stage_date) or iso(col(row, "registration_date"))
                    bucket = shards.get(key)
                    cur = bucket.get(case) if bucket else None
                    if bucket is None:
                        if not involved:
                            continue
                        bucket = shards[key] = {}
                    if involved:
                        if cur is None:
                            bucket[case] = [involved, col(row, "description"), when, stage]
                            added += 1
                        elif when >= (cur[2] if len(cur) > 2 else ""):
                            bucket[case] = [involved, col(row, "description") or cur[1], when, stage or (cur[3] if len(cur) > 3 else "")]
                            updated += 1
                        elif stage and len(cur) < 4:
                            bucket[case] = cur[:3] + [stage]
                            staged += 1
                    elif cur is not None and stage:
                        # учасників немає, але є свіжіша стадія
                        bucket[case] = (cur + [""] * 4)[:3] + [stage]
                        staged += 1

    if rows < 100_000:
        print(f"ERROR: too few status rows ({rows}), skipping")
        sys.exit(1)

    for key, cases in shards.items():
        with open(os.path.join(pdir, f"{key}.json"), "w", encoding="utf-8") as fh:
            json.dump(cases, fh, ensure_ascii=False, separators=(",", ":"))
    after = sum(len(v) for v in shards.values())
    print(f"status rows {rows}: parties {before} -> {after} (+{added} new, {updated} updated, {staged} stage-only)")

    meta_p = os.path.join(out, "meta.json")
    if os.path.exists(meta_p):
        with open(meta_p, encoding="utf-8") as fh:
            meta = json.load(fh)
        meta["parties_cases"] = after
        meta["status_rows"] = rows
        with open(meta_p, "w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Нарізка відкритого набору Мін'юсту «Єдиний реєстр боржників» (data.gov.ua, CC BY)
для пошуку виконавчих проваджень за ПІБ у застосунку.

Вхід: ZIP з одним CSV (windows-1251; заголовок через «;», дані через кому):
  DEBTOR_NAME;DEBTOR_BIRTHDATE;DEBTOR_CODE;PUBLISHER;ORG_NAME;ORG_PHONE_NUM;EMP_FULL_FIO;EMP_PHONE_NUM;EMAIL_ADDR;VP_ORDERNUM;VD_CAT

Беремо лише фізичних осіб. Файли названі хешем ключа «прізвище ім'я», тож знайти щось можна
лише знаючи ПІБ; переглядати реєстр «списком» незручно.

Вихід:
  out/b/<fnv1a32(ключ) % 4096 у hex, 3 знаки>.json
      { "прізвище ім'я": [[по батькові, "YYYY-MM-DD"|"", номер ВП, cat, org, emp], ...] }
  out/b/dicts.json
      { "cat": [категорія], "org": [[виконавець, телефон, email]], "emp": [[ПІБ виконавця, телефон]] }
  (поле «хто видав документ» не зберігаємо: ~300 тис. унікальних значень, словник важив би десятки МБ)
  meta.json: erb_rows, erb_people, erb_generated

Ключ і хеш мають збігатися з src/debtors.ts (erbKey, erbBucket).

Запуск: python3 split_erb.py <out_dir> <archive.zip>
"""
import csv
import datetime
import io
import itertools
import json
import os
import re
import sys
import zipfile

BUCKETS = 4096
csv.field_size_limit(10_000_000)

APOS = re.compile(r"[ʼ’`´‘]")
SPACES = re.compile(r"\s+")
PERSON = re.compile(r"^[A-Za-zА-ЯҐЄІЇа-яґєії'\-]+( [A-Za-zА-ЯҐЄІЇа-яґєії'\-]+){1,3}$")
ORG_WORDS = re.compile(r"\b(тов|пп|пат|прат|ат|кп|дп|фоп|спд|банк|управління|відділ|товариство|підприємство)\b", re.I)
DATE_DMY = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
DATE_YMD = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def norm_name(s: str) -> str:
    return SPACES.sub(" ", APOS.sub("'", s or "")).strip()


def erb_key(name: str) -> str:
    parts = norm_name(name).lower().split(" ")
    return " ".join(parts[:2])


def fnv1a32(s: str) -> int:
    h = 0x811C9DC5
    for b in s.encode("utf-8"):
        h ^= b
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def bucket(key: str) -> str:
    return f"{fnv1a32(key) % BUCKETS:03x}"


def iso(d: str) -> str:
    m = DATE_YMD.search(d or "")
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = DATE_DMY.search(d or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else ""


class Dict:
    def __init__(self):
        self.items: list = []
        self.index: dict = {}

    def id(self, value) -> int:
        k = json.dumps(value, ensure_ascii=False)
        i = self.index.get(k)
        if i is None:
            i = self.index[k] = len(self.items)
            self.items.append(value)
        return i


def main():
    out, archive = sys.argv[1], sys.argv[2]
    bdir = os.path.join(out, "b")
    os.makedirs(bdir, exist_ok=True)
    tmp = os.path.join(out, "_erb_tmp")
    os.makedirs(tmp, exist_ok=True)
    cat, org, emp = Dict(), Dict(), Dict()
    # записи накопичуються пачками й дописуються в тимчасові jsonl по кошиках — без мільйонів об'єктів у пам'яті
    pending: dict[str, list] = {}
    pending_n = 0
    rows = people = 0

    def flush():
        nonlocal pending, pending_n
        for b, lines in pending.items():
            with open(os.path.join(tmp, b), "a", encoding="utf-8") as fh:
                fh.write("".join(lines))
        pending, pending_n = {}, 0

    with zipfile.ZipFile(archive) as z:
        for name in z.namelist():
            if not name.lower().endswith(".csv"):
                continue
            with z.open(name) as raw:
                text = io.TextIOWrapper(raw, encoding="cp1251", errors="replace", newline="")
                # заголовок розділено «;», а рядки даних — комою; визначаємо окремо
                first = text.readline()
                if not first:
                    continue
                header = next(csv.reader([first], delimiter=";" if first.count(";") > first.count(",") else ","))
                probe = text.readline()
                delim = "," if probe.count('","') >= probe.count('";"') else ";"
                rd = csv.reader(itertools.chain([probe], text), delimiter=delim, quotechar='"')
                idx = {h.strip().lstrip("﻿"): i for i, h in enumerate(header)}

                def col(row, key):
                    i = idx.get(key)
                    return row[i].strip() if i is not None and i < len(row) else ""

                for row in rd:
                    rows += 1
                    full = norm_name(col(row, "DEBTOR_NAME"))
                    birth = iso(col(row, "DEBTOR_BIRTHDATE"))
                    if not PERSON.match(full) or ORG_WORDS.search(full):
                        continue
                    vp = col(row, "VP_ORDERNUM")
                    if not vp:
                        continue
                    people += 1
                    key = erb_key(full)
                    # прізвище та ім'я вже в ключі — зберігаємо лише решту ПІБ (по батькові)
                    rest = " ".join(full.split(" ")[2:])
                    rec = [
                        rest,
                        birth,
                        vp,
                        cat.id(col(row, "VD_CAT")),
                        org.id([col(row, "ORG_NAME"), col(row, "ORG_PHONE_NUM"), col(row, "EMAIL_ADDR")]),
                        emp.id([col(row, "EMP_FULL_FIO"), col(row, "EMP_PHONE_NUM")]),
                    ]
                    pending.setdefault(bucket(key), []).append(json.dumps([key, rec], ensure_ascii=False, separators=(",", ":")) + "\n")
                    pending_n += 1
                    if pending_n >= 300_000:
                        flush()
    flush()

    if people < 100_000:
        print(f"ERROR: too few debtors ({people} of {rows} rows), skipping")
        sys.exit(1)

    files = 0
    for b in os.listdir(tmp):
        recs: dict[str, list] = {}
        with open(os.path.join(tmp, b), encoding="utf-8") as fh:
            for line in fh:
                key, rec = json.loads(line)
                recs.setdefault(key, []).append(rec)
        with open(os.path.join(bdir, f"{b}.json"), "w", encoding="utf-8") as fh:
            json.dump(recs, fh, ensure_ascii=False, separators=(",", ":"))
        os.remove(os.path.join(tmp, b))
        files += 1
    os.rmdir(tmp)
    with open(os.path.join(bdir, "dicts.json"), "w", encoding="utf-8") as fh:
        json.dump({"cat": cat.items, "org": org.items, "emp": emp.items}, fh, ensure_ascii=False, separators=(",", ":"))

    meta_p = os.path.join(out, "meta.json")
    meta = {}
    if os.path.exists(meta_p):
        with open(meta_p, encoding="utf-8") as fh:
            meta = json.load(fh)
    meta["erb_rows"] = rows
    meta["erb_people"] = people
    meta["erb_generated"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    with open(meta_p, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=1)
    print(f"erb rows {rows}: people {people}, files {files}, dicts cat {len(cat.items)} org {len(org.items)} emp {len(emp.items)}")


if __name__ == "__main__":
    main()

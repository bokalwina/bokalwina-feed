#!/usr/bin/env python3
"""
Генератор YML-фида для Яндекс Директа из штатного CSV-фида Тильды.

Источник: https://bokalwina.ru/feed-fb.csv (Tilda, формат Facebook/Google Merchant).
Результат: docs/bokalwina.yml (YML для Директа) + docs/index.html (статус).

Правила:
- товары без цены или с нулевой ценой выкидываются;
- товары без картинки выкидываются;
- категория и vendor берутся из названия (бренд), а не из первого раздела Тильды;
- каждая строка CSV (вариант товара: 2 шт / 6 шт) становится отдельным offer,
  варианты одного товара связаны через group_id.
"""
import csv
import datetime as dt
import html
import io
import json
import re
import sys
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape

SRC = "https://bokalwina.ru/feed-fb.csv"
OUT_DIR = Path(__file__).resolve().parent / "docs"
SHOP_NAME = "Бокалвина"
SHOP_URL = "https://bokalwina.ru"

# Бренд по префиксу названия -> (категория, vendor)
BRANDS = [
    ("josephine", "Josephine", "Josephine"),
    ("zalto", "Zalto", "Zalto"),
    ("omega gravitas", "Zalto", "Zalto"),
    ("sweet wine", "Zalto", "Zalto"),
    ("digestif", "Zalto", "Zalto"),
    ("lehmann", "Lehmann", "Lehmann"),
    ("markthomas", "Markthomas", "Markthomas"),
    ("sydonios", "Sydonios", "Sydonios"),
    ("spiegelau", "Spiegelau", "Spiegelau"),
    ("nachtmann", "Посуда для крепких напитков", "Nachtmann"),
    ("vista alegre", "Посуда для крепких напитков", "Vista Alegre"),
]
DEFAULT_CATEGORY = "Бокалы и посуда"

PARENT_CATEGORY = "Бокалы и посуда"


def fetch(url: str, attempts: int = 4) -> str:
    import time
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; bokalwina-feed-builder)",
        "Accept": "text/csv,*/*",
    })
    last = None
    for i in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode("utf-8-sig")
        except Exception as e:  # noqa: BLE001
            last = e
            print(f"fetch attempt {i + 1} failed: {e}", file=sys.stderr)
            time.sleep(5 * (i + 1))
    raise last


def parse_price(s: str) -> float:
    # "25,000.00 RUB" -> 25000.0
    s = (s or "").replace("RUB", "").replace(" ", "").replace(" ", "").replace(",", "")
    try:
        return float(s)
    except ValueError:
        return 0.0


def strip_html(s: str) -> str:
    s = re.sub(r"<br\s*/?>", "\n", s or "", flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    return re.sub(r"[ \t]+", " ", s).strip()


def detect_brand(title: str):
    t = (title or "").lower()
    for key, cat, vendor in BRANDS:
        if key in t:
            return cat, vendor
    return DEFAULT_CATEGORY, None


def clean_title(title: str) -> str:
    t = (title or "").replace("﻿", "").strip()
    t = re.sub(r"\s+", " ", t)
    return t


def build(rows):
    categories = {PARENT_CATEGORY: 1}
    offers = []
    skipped = []
    for r in rows:
        title = clean_title(r.get("title"))
        price = parse_price(r.get("price"))
        old = parse_price(r.get("sale_price")) if r.get("sale_price") else 0.0
        link = (r.get("link") or "").strip()
        pic = (r.get("image_link") or "").strip()
        if price <= 0:
            skipped.append((title, "нет цены"))
            continue
        if not pic:
            skipped.append((title, "нет картинки"))
            continue
        if not link:
            skipped.append((title, "нет ссылки"))
            continue
        cat, vendor = detect_brand(title)
        if cat not in categories:
            categories[cat] = len(categories) + 1
        qty = ""
        m = re.search(r"-\s*(\d+\s*шт[^)]*\)?|\d+\s*мл)\s*$", title)
        if m:
            qty = m.group(1).strip()
        offers.append({
            "id": r["id"].strip(),
            "group_id": (r.get("item_group_id") or "").strip(),
            "name": title,
            "url": link,
            "price": price,
            "oldprice": old if old > price else 0.0,
            "picture": pic,
            "vendor": vendor,
            "category_id": categories[cat],
            "description": strip_html(r.get("description")),
            "available": (r.get("availability") or "").strip().lower() == "in stock",
            "qty": qty,
        })
    return categories, offers, skipped


def to_yml(categories, offers) -> str:
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=3))).strftime("%Y-%m-%d %H:%M")
    out = io.StringIO()
    out.write('<?xml version="1.0" encoding="UTF-8"?>\n')
    out.write(f'<yml_catalog date="{now}">\n<shop>\n')
    out.write(f"<name>{escape(SHOP_NAME)}</name>\n")
    out.write(f"<company>{escape(SHOP_NAME)}</company>\n")
    out.write(f"<url>{escape(SHOP_URL)}</url>\n")
    out.write('<currencies><currency id="RUR" rate="1"/></currencies>\n')
    out.write("<categories>\n")
    for name, cid in categories.items():
        if cid == 1:
            out.write(f'<category id="{cid}">{escape(name)}</category>\n')
        else:
            out.write(f'<category id="{cid}" parentId="1">{escape(name)}</category>\n')
    out.write("</categories>\n<offers>\n")
    for o in offers:
        gid = f' group_id="{escape(o["group_id"])}"' if o["group_id"] else ""
        out.write(f'<offer id="{escape(o["id"])}"{gid} available="{"true" if o["available"] else "false"}">\n')
        out.write(f"<url>{escape(o['url'])}</url>\n")
        out.write(f"<price>{o['price']:.0f}</price>\n")
        if o["oldprice"]:
            out.write(f"<oldprice>{o['oldprice']:.0f}</oldprice>\n")
        out.write("<currencyId>RUR</currencyId>\n")
        out.write(f"<categoryId>{o['category_id']}</categoryId>\n")
        out.write(f"<picture>{escape(o['picture'])}</picture>\n")
        out.write(f"<name>{escape(o['name'])}</name>\n")
        if o["vendor"]:
            out.write(f"<vendor>{escape(o['vendor'])}</vendor>\n")
        if o["description"]:
            desc = o["description"][:3000]
            out.write(f"<description><![CDATA[{desc}]]></description>\n")
        if o["qty"]:
            out.write(f'<param name="Количество">{escape(o["qty"])}</param>\n')
        out.write("</offer>\n")
    out.write("</offers>\n</shop>\n</yml_catalog>\n")
    return out.getvalue()


def main():
    raw = fetch(SRC)
    rows = list(csv.DictReader(io.StringIO(raw)))
    categories, offers, skipped = build(rows)
    yml = to_yml(categories, offers)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "bokalwina.yml").write_text(yml, encoding="utf-8")
    (OUT_DIR / "feed-fb.csv").write_text(raw, encoding="utf-8")
    status = {
        "updated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "source_rows": len(rows),
        "offers": len(offers),
        "categories": list(categories.keys()),
        "skipped": skipped,
    }
    (OUT_DIR / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT_DIR / "index.html").write_text(
        "<!doctype html><meta charset=utf-8><title>bokalwina feed</title>"
        f"<p>Фид для Директа: <a href='bokalwina.yml'>bokalwina.yml</a></p>"
        f"<p>Обновлено: {status['updated']} UTC. Товаров в источнике: {len(rows)}, в фиде: {len(offers)}.</p>"
        f"<p>Пропущено: {html.escape(json.dumps(skipped, ensure_ascii=False))}</p>",
        encoding="utf-8")
    print(f"rows={len(rows)} offers={len(offers)} skipped={skipped}")
    if not offers:
        sys.exit("EMPTY FEED — aborting")


if __name__ == "__main__":
    main()

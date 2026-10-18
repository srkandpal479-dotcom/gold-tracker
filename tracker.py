# Gold pendant tracker (Amazon Creators API)
# Is file ko SDK ke "examples" folder mein rakho (jahan sample_get_items.py hai).
#
# Chalane ke tareeke:
#   python tracker.py              -> ek baar check karke ranking dikhao
#   python tracker.py --loop 10    -> har 10 minute mein dobara check karo (band karne ke liye Ctrl+C)

import csv
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from creatorsapi_python_sdk.api_client import ApiClient
from creatorsapi_python_sdk.api.default_api import DefaultApi
from creatorsapi_python_sdk.models.get_items_request_content import GetItemsRequestContent
from creatorsapi_python_sdk.exceptions import ApiException

HERE = os.path.dirname(os.path.abspath(__file__))
SECRETS_FILE = os.path.join(HERE, "secrets.json")
PRODUCTS_FILE = os.path.join(HERE, "products.csv")
OUT_DIR = os.environ.get("OUT_DIR", HERE)
os.makedirs(OUT_DIR, exist_ok=True)
HISTORY_FILE = os.path.join(OUT_DIR, "price_history.csv")
LATEST_JSON = os.path.join(OUT_DIR, "latest.json")
LATEST_CSV = os.path.join(OUT_DIR, "ranking.csv")

BATCH_SIZE = 10          # Amazon ek call mein max 10 ASIN leta hai
PAUSE_BETWEEN_CALLS = 1.5  # seconds, Amazon ki limit ka dhyan rakhne ke liye

RESOURCES = [
    'images.primary.medium',
    'itemInfo.title',
    'offersV2.listings.price',
    'offersV2.listings.availability',
    'offersV2.listings.isBuyBoxWinner',
    'offersV2.listings.merchantInfo',
]


def load_secrets():
    # GitHub Actions: secrets environment variables se aate hain. Laptop par: secrets.json se.
    if os.environ.get("AMAZON_CREDENTIAL_ID"):
        return {
            "credential_id": os.environ["AMAZON_CREDENTIAL_ID"],
            "credential_secret": os.environ["AMAZON_CREDENTIAL_SECRET"],
            "version": os.environ.get("AMAZON_CREDENTIAL_VERSION", "3.2"),
            "marketplace": os.environ.get("AMAZON_MARKETPLACE", "www.amazon.in"),
            "partner_tag": os.environ["AMAZON_PARTNER_TAG"],
        }
    with open(SECRETS_FILE, encoding="utf-8") as f:
        return json.load(f)


def load_products():
    products = []
    with open(PRODUCTS_FILE, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            asin = (row.get("asin") or "").strip()
            if not asin or asin.startswith("#"):
                continue
            try:
                weight = float(row["weight_g"])
                purity = float(row["purity"])  # 999 ya 916 etc.
            except (KeyError, ValueError):
                print(f"[SKIP] {asin}: weight_g ya purity galat/khali hai")
                continue
            products.append({
                "asin": asin,
                "weight_g": weight,
                "purity": purity,
                "commission": (row.get("commission") or "").strip().lower(),
                "name": (row.get("name") or "").strip(),
            })
    return products


def chunks(items, n):
    for i in range(0, len(items), n):
        yield items[i:i + n]


def get(d, *keys):
    """Safe nested lookup: get(d, 'a', 'b') -> d['a']['b'] ya None."""
    for k in keys:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def pick_listing(item):
    listings = get(item, "offersV2", "listings") or []
    if not listings:
        return None
    for l in listings:
        if l.get("isBuyBoxWinner"):
            return l
    return listings[0]


def parse_item(item):
    """Amazon ke ek item se kaam ka data nikalo."""
    listing = pick_listing(item)
    price = get(listing, "price", "money", "amount") if listing else None
    availability = get(listing, "availability", "type") if listing else None
    return {
        "title": get(item, "itemInfo", "title", "displayValue") or "",
        "price": float(price) if price is not None else None,
        "availability": availability or "NO_OFFER",
        "seller": get(listing, "merchantInfo", "name") if listing else "",
        "url": item.get("detailPageURL", ""),
        "image": get(item, "images", "primary", "medium", "url") or "",
    }


def fetch_all(api, secrets, asins):
    """Saare ASIN ke liye data lao. Return: {asin: parsed_item}"""
    found = {}
    for batch in chunks(asins, BATCH_SIZE):
        request = GetItemsRequestContent(
            partner_tag=secrets["partner_tag"],
            item_ids=batch,
            resources=RESOURCES,
        )
        try:
            response = api.get_items(
                x_marketplace=secrets["marketplace"],
                get_items_request_content=request,
            )
        except ApiException as e:
            status = getattr(e, "status", None)
            print(f"[ERROR] Amazon ne mana kar diya ({status}).")
            if status in (401, 403):
                print("Credentials ya eligibility ka masla hai. Aage nahi badh raha.")
                raise
            print(e)
            time.sleep(10)
            continue
        data = response.to_dict() if hasattr(response, "to_dict") else {}
        items = get(data, "itemsResult", "items") or get(data, "items_result", "items") or []
        for item in items:
            found[item.get("asin")] = parse_item(item)
        time.sleep(PAUSE_BETWEEN_CALLS)
    return found


def load_rules():
    try:
        with open(os.path.join(OUT_DIR, "sku_rules.json"), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def build_rows(products, fetched):
    rules = load_rules()
    rows = []
    now = datetime.now(timezone(timedelta(hours=5, minutes=30))).strftime("%Y-%m-%dT%H:%M:%S+05:30")  # India time, har server par sahi
    for p in products:
        info = fetched.get(p["asin"])
        fine_grams = p["weight_g"] * p["purity"] / 999.0
        row = {
            "checked_at": now,
            "asin": p["asin"],
            "name": p["name"] or (info["title"][:60] if info else ""),
            "weight_g": p["weight_g"],
            "purity": p["purity"],
            "commission": p["commission"],
            "price": None,
            "per_fine_gram": None,
            "availability": "NOT_RETURNED",
            "seller": "",
            "url": "",
            "image": "",
            "off": rules.get(p["asin"], {}).get("off", []),
        }
        if info:
            row.update({
                "price": info["price"],
                "availability": info["availability"],
                "seller": info["seller"],
                "url": info["url"],
                "image": info["image"],
            })
            if info["price"] is not None and fine_grams > 0:
                row["per_fine_gram"] = round(info["price"] / fine_grams, 2)
        rows.append(row)
    return rows


def rank(rows):
    """Sirf IN_STOCK wale, sabse sasta per-gram pehle. Baaki neeche."""
    def key(r):
        in_stock = r["availability"] in ("IN_STOCK", "AVAILABLE_DATE") and r["per_fine_gram"] is not None
        return (0 if in_stock else 1, r["per_fine_gram"] if r["per_fine_gram"] is not None else 1e18)
    return sorted(rows, key=key)


def save(rows):
    fields = ["checked_at", "asin", "name", "weight_g", "purity", "commission",
              "price", "per_fine_gram", "availability", "seller", "url", "image"]
    # History: har run ki rows jodte jao
    new_file = not os.path.exists(HISTORY_FILE)
    with open(HISTORY_FILE, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if new_file:
            w.writeheader()
        w.writerows(rows)
    # Latest ranking: har baar naya likho
    ranked = rank(rows)
    with open(LATEST_CSV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(ranked)
    with open(LATEST_JSON, "w", encoding="utf-8") as f:
        json.dump(ranked, f, ensure_ascii=False, indent=2)
    return ranked


def show(ranked):
    print()
    print(f"{'#':>2}  {'Rs/fine gram':>12}  {'Price':>9}  {'Wt':>5}  {'Stock':<12} Name")
    print("-" * 80)
    for i, r in enumerate(ranked, 1):
        pg = f"{r['per_fine_gram']:,.0f}" if r["per_fine_gram"] is not None else "-"
        pr = f"{r['price']:,.0f}" if r["price"] is not None else "-"
        print(f"{i:>2}  {pg:>12}  {pr:>9}  {r['weight_g']:>4g}g  {r['availability']:<12} {r['name'][:40]}")
    print()


def run_once():
    secrets = load_secrets()
    products = load_products()
    if not products:
        print("products.csv mein koi valid product nahi mila.")
        return
    api_client = ApiClient(
        credential_id=secrets["credential_id"],
        credential_secret=secrets["credential_secret"],
        version=str(secrets["version"]),
    )
    api = DefaultApi(api_client)
    asins = [p["asin"] for p in products]
    print(f"{len(asins)} products check ho rahe hain...")
    fetched = fetch_all(api, secrets, asins)
    rows = build_rows(products, fetched)
    ranked = save(rows)
    show(ranked)
    missing = [r["asin"] for r in rows if r["availability"] == "NOT_RETURNED"]
    if missing:
        print("Amazon ne ye ASIN wapas nahi kiye (galat ASIN ya India mein nahi hai):", ", ".join(missing))
    print("Saved: ranking.csv, latest.json, price_history.csv")


def main():
    if "--loop" in sys.argv:
        try:
            minutes = float(sys.argv[sys.argv.index("--loop") + 1])
        except (IndexError, ValueError):
            minutes = 10
        minutes = max(minutes, 2)  # 2 minute se tez nahi
        while True:
            try:
                run_once()
            except ApiException:
                print("Rukna pad raha hai. Credentials/eligibility check karo.")
                break
            except Exception as e:
                print("Unexpected error:", e)
            print(f"{minutes:g} minute baad dobara...\n")
            time.sleep(minutes * 60)
    else:
        run_once()


if __name__ == "__main__":
    main()

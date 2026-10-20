# Google Sheet (3 published CSV links) se market rate, offers aur SKU list padhta hai.
# Output: out/market.json, out/offers.json, out/sku_rules.json aur products.csv (runner ke liye).
# Koi bhi tab kharab ho to us tab ka kaam skip hota hai, purani files/repo ki products.csv kaam karti rehti hain.
import csv, io, json, os, re, urllib.request
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("OUT_DIR", os.path.join(HERE, "out"))
os.makedirs(OUT, exist_ok=True)
FIXED = {"asin", "name", "weight_g", "purity", "commission", "show", "short_link"}
FALSE_WORDS = {"false", "no", "0", "n", "off"}
TRUE_WORDS = {"true", "yes", "1", "y", "on"}


def warn(msg):
    print("[WARN]", msg)


def clean(s):
    s = (s or "").strip().replace("\u00e2\u201a\u00b9", "\u20b9")  # kharab ₹ (a,¹) ko theek karo
    if re.search("[âÃ]", s):  # kharab encoding (â‚¹ jaisa) ko theek karne ki koshish
        try:
            s = s.encode("cp1252").decode("utf-8")
        except Exception:
            pass
    return s


def fetch(env):
    url = os.environ.get(env, "").strip()
    if not url:
        warn(env + " set nahi hai")
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            text = r.read().decode("utf-8-sig")
        rows = []
        for raw in csv.DictReader(io.StringIO(text)):
            rows.append({(k or "").strip().lower(): clean(v) for k, v in raw.items() if k and isinstance(v, str)})
        return rows
    except Exception as e:  # URL print nahi karte (wo secret hai)
        warn("%s download fail: %s" % (env, type(e).__name__))
        return None


def num(s):
    s = re.sub(r"[₹,\s]", "", s or "")
    try:
        return float(s) if s else None
    except ValueError:
        return None


def is_true(s):
    return (s or "").strip().lower() in TRUE_WORDS


def is_false(s):
    return (s or "").strip().lower() in FALSE_WORDS


def to_date(s):
    s = (s or "").strip()
    for f in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d %b %Y"):
        try:
            return datetime.strptime(s, f).date().isoformat()
        except ValueError:
            pass
    if s:
        warn("date samajh nahi aayi: '%s' (YYYY-MM-DD likho)" % s)
    return ""


def now_iso():
    return datetime.now(IST).strftime("%Y-%m-%dT%H:%M:%S+05:30")


def write_json(name, data):
    with open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("Wrote", name)


def read_prev_market():
    url = os.environ.get("MARKET_PREV_URL", "").strip()
    if not url:
        return None
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def do_market(rows):
    kv = {r.get("key", "").strip().lower(): r.get("value", "") for r in rows}
    m24, m22 = num(kv.get("manual_24k")), num(kv.get("manual_22k"))
    manual = bool(m24 or m22)
    m24 = m24 or num(kv.get("gold_24k"))
    m22 = m22 or num(kv.get("gold_22k"))
    prev = read_prev_market()
    ok, reason = True, ""
    if not m24 or not (1000 < m24 < 100000):
        ok, reason = False, "24K rate missing/invalid"
    elif not manual:
        if m22 and abs(m22 / m24 - 0.916) > 0.03:
            ok, reason = False, "22K/24K ratio galat lag raha hai"
        if prev and prev.get("ok") and prev.get("gold_24k") and abs(m24 / prev["gold_24k"] - 1) > 0.05:
            ok, reason = False, "rate pichle se 5%% se zyada kooda"
    if not ok:
        warn("Market rate rok diya: " + reason)
    now = int(datetime.now(IST).timestamp())
    hist = [h for h in (prev or {}).get("hist", []) if now - h[0] < 48 * 3600]
    if ok and (not hist or now - hist[-1][0] >= 3600):
        hist.append([now, m24])
    change = None
    cand = [h for h in hist if 18 * 3600 <= now - h[0] <= 30 * 3600]
    if ok and cand:
        ref = min(cand, key=lambda h: abs((now - h[0]) - 86400))
        change = round(m24 - ref[1])
    write_json("market.json", {
        "ok": ok, "reason": reason, "manual": manual,
        "gold_24k": m24 if ok else None, "gold_22k": m22 if ok else None,
        "source": kv.get("source", ""), "city": kv.get("city", ""), "updated": now_iso(),
        "change_24h": change, "hist": hist,
    })


def parse_extras(s):
    out = []
    for part in (s or "").split(";"):
        part = part.strip()
        if not part:
            continue
        a, _, b = part.partition(":")
        if num(a) and num(b):
            out.append({"min": num(a), "amount": num(b)})
        else:
            warn("extras samajh nahi aaya: '%s' (format 24990:500;39990:1000)" % part)
    return out


def do_offers(rows):
    today = datetime.now(IST).date().isoformat()
    cards, flats, notices, seen = [], [], [], set()
    for r in rows:
        oid = r.get("id", "").strip().lower()
        if not oid or oid in seen:
            continue
        seen.add(oid)
        if not is_true(r.get("active")):
            continue
        vt = to_date(r.get("valid_till"))
        if vt and vt < today:
            continue
        typ, label = r.get("type", "").strip().lower(), r.get("label", "") or oid
        claim = r.get("claim_url", "").strip()
        claim = claim if claim.startswith("https://") else ""
        pct, cap, mn, fee, amt = (num(r.get(k)) or 0 for k in ("pct", "cap", "min", "fee", "amount"))
        if typ == "flat_cashback" and not amt and pct:
            warn("%s: type flat_cashback hai par pct bhara hai, ise card_cashback maan raha hoon" % oid)
            typ = "card_cashback"
        if typ in ("card_discount", "card_cashback"):
            extras = parse_extras(r.get("extras"))
            if not pct and not extras:
                warn("%s: pct ya extras chahiye, skip" % oid)
                continue
            cards.append({"id": oid, "label": label, "kind": "cashback" if typ == "card_cashback" else "discount",
                          "pct": pct, "cap": cap, "min": mn, "fee": fee, "extras": extras,
                          "stack": is_true(r.get("stack")), "extra_cap": num(r.get("extra_cap")) or 0, "claim_url": claim})
        elif typ == "flat_cashback":
            if not amt:
                warn("%s: amount chahiye, skip" % oid)
                continue
            flats.append({"id": oid, "label": label, "amount": amt, "min": mn, "claim_url": claim})
        else:
            warn("%s: type samajh nahi aaya ('%s')" % (oid, typ))
            continue
        nt, nu = r.get("notice", "").strip(), to_date(r.get("notice_until"))
        if nt and (not nu or nu >= today):
            notices.append({"id": oid, "text": nt, "claim_url": claim})
    best = max(flats, key=lambda x: x["amount"]) if flats else None
    write_json("offers.json", {"offers": cards, "cashback": best, "cashbacks": flats, "notices": notices, "updated": now_iso()})


def do_skus(rows):
    prods, rules = [], {}
    for r in rows:
        asin = r.get("asin", "").strip().upper()
        if not asin:
            continue
        w, p = num(r.get("weight_g")), num(r.get("purity"))
        if not re.fullmatch(r"[A-Z0-9]{10}", asin) or not w or not p:
            warn("SKU skip (asin/weight/purity galat): " + asin)
            continue
        if is_false(r.get("show")):
            continue
        prods.append([asin, ("%g" % w), ("%g" % p), r.get("commission", ""), r.get("name", ""),
                      (r.get("short_link", "") if r.get("short_link", "").startswith("https://") else "")])
        rules[asin] = {"off": [k for k, v in r.items() if k not in FIXED and is_false(v)]}
    if not prods:
        warn("SKU tab se koi valid row nahi mili, purani products.csv chalegi")
        return
    with open(os.path.join(HERE, "products.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["asin", "weight_g", "purity", "commission", "name", "short_link"])
        w.writerows(prods)
    write_json("sku_rules.json", rules)
    print("products.csv me %d SKUs" % len(prods))


if __name__ == "__main__":
    m, o, s = fetch("MARKET_CSV_URL"), fetch("OFFERS_CSV_URL"), fetch("SKUS_CSV_URL")
    if m is not None:
        do_market(m)
    if o is not None:
        do_offers(o)
    if s is not None:
        do_skus(s)

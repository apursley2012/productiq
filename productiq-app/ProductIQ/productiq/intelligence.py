from __future__ import annotations

import json
import re
import statistics
from collections import Counter
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import requests
from bs4 import BeautifulSoup

PRICE_RE = re.compile(r"\$\s?([0-9]{1,6}(?:,[0-9]{3})*(?:\.\d{2})?)")
SEARCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Domains that are rarely useful as a direct resale competitor listing.
SKIP_DOMAINS = {
    "google.com", "youtube.com", "facebook.com", "instagram.com", "pinterest.com",
    "tiktok.com", "reddit.com", "x.com", "twitter.com", "linkedin.com",
    "wikipedia.org", "duckduckgo.com", "bing.com",
}

CATEGORY_RULES = [
    ("Electronics", "Computers & Accessories", ("laptop", "computer", "keyboard", "mouse", "monitor", "ssd", "hard drive", "webcam", "router", "usb", "charger", "power bank")),
    ("Electronics", "Audio & Headphones", ("earbud", "headphone", "speaker", "microphone", "soundbar", "bluetooth audio")),
    ("Electronics", "Phones & Accessories", ("iphone", "android", "phone case", "screen protector", "cell phone", "smartphone")),
    ("Electronics", "TV & Home Theater", ("television", "smart tv", "roku", "fire tv", "projector", "hdmi")),
    ("Home & Kitchen", "Bedding & Bath", ("pillow", "pillowcase", "sheet", "comforter", "blanket", "mattress", "towel", "shower curtain")),
    ("Home & Kitchen", "Kitchen & Dining", ("cookware", "pan", "pot", "knife", "utensil", "tumbler", "mug", "bottle", "air fryer", "coffee maker", "storage container")),
    ("Home & Kitchen", "Home Decor", ("curtain", "rug", "lamp", "wall decor", "picture frame", "candle", "vase")),
    ("Home & Kitchen", "Cleaning & Organization", ("organizer", "storage bin", "laundry", "vacuum", "cleaning", "mop", "broom")),
    ("Clothing & Accessories", "Women's Clothing", ("women's", "womens", "dress", "blouse", "leggings", "bra", "skirt")),
    ("Clothing & Accessories", "Men's Clothing", ("men's", "mens", "wallet", "tie", "boxer", "men shirt")),
    ("Clothing & Accessories", "Shoes", ("shoe", "sneaker", "boot", "sandal", "slipper")),
    ("Jewelry & Accessories", "Jewelry", ("earring", "necklace", "bracelet", "ring", "jewelry", "jewellery")),
    ("Jewelry & Accessories", "Bags & Wallets", ("purse", "handbag", "backpack", "wallet", "card holder", "tote")),
    ("Beauty & Personal Care", "Skin Care", ("moisturizer", "serum", "cleanser", "skin care", "skincare", "lotion", "sunscreen")),
    ("Beauty & Personal Care", "Hair Care", ("shampoo", "conditioner", "hair dryer", "hair brush", "hair care", "curling iron", "straightener")),
    ("Beauty & Personal Care", "Makeup & Cosmetics", ("makeup", "mascara", "lipstick", "eyelash", "foundation", "concealer", "eyeshadow")),
    ("Health & Wellness", "Personal Health", ("vitamin", "thermometer", "blood pressure", "heating pad", "first aid", "brace", "massager")),
    ("Toys & Games", "Toys", ("toy", "doll", "action figure", "playset", "building blocks", "plush")),
    ("Toys & Games", "Games & Puzzles", ("board game", "card game", "puzzle", "gaming")),
    ("Baby & Kids", "Baby Gear", ("baby", "infant", "toddler", "stroller", "diaper", "bottle warmer", "pacifier")),
    ("Pet Supplies", "Dog Supplies", ("dog", "puppy", "leash", "dog toy", "dog bed")),
    ("Pet Supplies", "Cat Supplies", ("cat", "kitten", "litter", "cat toy", "scratcher")),
    ("Automotive", "Car Accessories", ("car", "automotive", "vehicle", "dash cam", "car seat cover", "car charger")),
    ("Tools & Home Improvement", "Tools", ("drill", "screwdriver", "wrench", "tool set", "saw", "socket", "hammer")),
    ("Tools & Home Improvement", "Lighting & Electrical", ("led strip", "light bulb", "lighting", "electrical", "extension cord")),
    ("Sports & Outdoors", "Fitness", ("dumbbell", "yoga", "fitness", "exercise", "resistance band", "workout")),
    ("Sports & Outdoors", "Outdoor Recreation", ("camping", "hiking", "fishing", "outdoor", "tent", "cooler")),
    ("Office & School", "Office Supplies", ("pen", "notebook", "printer", "paper", "desk", "office", "stapler", "label maker")),
    ("Arts & Crafts", "Craft Supplies", ("craft", "paint", "canvas", "vinyl", "cricut", "scrapbook", "yarn", "sewing")),
    ("Garden & Outdoor", "Lawn & Garden", ("garden", "plant", "planter", "hose", "patio", "lawn")),
    ("Grocery & Household", "Food & Beverage", ("coffee", "tea", "snack", "candy", "food", "drink", "beverage")),
    ("Grocery & Household", "Household Supplies", ("paper towel", "toilet paper", "trash bag", "detergent", "dish soap")),
]

COMPLEMENTARY = {
    "Computers & Accessories": {"Audio & Headphones", "Phones & Accessories", "Office Supplies"},
    "Audio & Headphones": {"Computers & Accessories", "Phones & Accessories"},
    "Phones & Accessories": {"Audio & Headphones", "Computers & Accessories"},
    "Bedding & Bath": {"Home Decor", "Cleaning & Organization"},
    "Kitchen & Dining": {"Cleaning & Organization", "Food & Beverage"},
    "Home Decor": {"Bedding & Bath", "Lighting & Electrical"},
    "Women's Clothing": {"Jewelry", "Bags & Wallets", "Shoes"},
    "Men's Clothing": {"Bags & Wallets", "Shoes", "Jewelry"},
    "Shoes": {"Women's Clothing", "Men's Clothing", "Bags & Wallets"},
    "Jewelry": {"Women's Clothing", "Bags & Wallets"},
    "Bags & Wallets": {"Jewelry", "Women's Clothing", "Men's Clothing", "Shoes"},
    "Skin Care": {"Makeup & Cosmetics", "Hair Care"},
    "Hair Care": {"Skin Care", "Makeup & Cosmetics"},
    "Makeup & Cosmetics": {"Skin Care", "Hair Care"},
    "Dog Supplies": {"Pet Supplies"},
    "Cat Supplies": {"Pet Supplies"},
    "Fitness": {"Outdoor Recreation", "Personal Health"},
    "Outdoor Recreation": {"Fitness"},
    "Tools": {"Lighting & Electrical", "Car Accessories"},
    "Lighting & Electrical": {"Tools", "Home Decor"},
}


def _num(value):
    if value is None:
        return None
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)", str(value).replace(",", ""))
    return float(m.group(1)) if m else None


def _query(result, source):
    parts = [
        source.get("upc"), source.get("model"), result.get("modelNumber"),
        result.get("partNumber"), source.get("brand"), result.get("brand"),
        result.get("title") or source.get("name"),
    ]
    # Keep exact identifiers first because they dramatically improve retail matching.
    unique = []
    for part in parts:
        value = str(part or "").strip()
        if value and value.lower() not in {x.lower() for x in unique}:
            unique.append(value)
    return " ".join(unique)[:220]


def _unwrap_google_url(href: str) -> str:
    if not href:
        return ""
    if href.startswith("/url?"):
        return unquote(parse_qs(urlparse(href).query).get("q", [""])[0])
    return href


def _domain(url: str) -> str:
    host = urlparse(url).netloc.lower().split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return host


def _store_name(domain: str) -> str:
    if not domain:
        return "Online retailer"
    known = {
        "walmart.com": "Walmart", "ebay.com": "eBay", "target.com": "Target",
        "bestbuy.com": "Best Buy", "amazon.com": "Amazon", "homedepot.com": "The Home Depot",
        "lowes.com": "Lowe's", "macys.com": "Macy's", "kohls.com": "Kohl's",
        "wayfair.com": "Wayfair", "etsy.com": "Etsy", "newegg.com": "Newegg",
        "costco.com": "Costco", "samsclub.com": "Sam's Club", "staples.com": "Staples",
        "officedepot.com": "Office Depot", "walgreens.com": "Walgreens", "cvs.com": "CVS",
        "sephora.com": "Sephora", "ulta.com": "Ulta Beauty", "chewy.com": "Chewy",
        "petsmart.com": "PetSmart", "petco.com": "Petco", "dickssportinggoods.com": "DICK'S Sporting Goods",
        "academy.com": "Academy Sports + Outdoors", "autozone.com": "AutoZone", "oreillyauto.com": "O'Reilly Auto Parts",
        "jcpenney.com": "JCPenney", "nordstrom.com": "Nordstrom", "zappos.com": "Zappos",
    }
    for key, value in known.items():
        if domain == key or domain.endswith("." + key):
            return value
    core = domain.split(".")[0].replace("-", " ")
    return core.title() if core else "Online retailer"


def _is_useful_result(url: str) -> bool:
    domain = _domain(url)
    if not domain:
        return False
    if any(domain == d or domain.endswith("." + d) for d in SKIP_DOMAINS):
        return False
    return url.startswith("http")


def _google_results(query: str, timeout=8, limit=14):
    """Use normal Google web results to discover stores rather than a fixed retailer list."""
    url = f"https://www.google.com/search?num={min(limit + 4, 20)}&q={quote_plus(query)}"
    response = requests.get(url, headers=SEARCH_HEADERS, timeout=timeout)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    results = []
    seen = set()

    # Google changes markup frequently, so support several common result shapes.
    for anchor in soup.select("div.yuRUbf > a, a[jsname='UWckNb'], div.g a"):
        href = _unwrap_google_url(anchor.get("href", ""))
        if not _is_useful_result(href):
            continue
        domain = _domain(href)
        if href in seen:
            continue
        seen.add(href)
        block = anchor.find_parent("div", class_="g") or anchor.parent
        title_el = anchor.select_one("h3") or (block.select_one("h3") if block else None)
        title = title_el.get_text(" ", strip=True) if title_el else anchor.get_text(" ", strip=True)
        snippet_el = block.select_one("div.VwiC3b, div[data-sncf], span.aCOpRe") if block else None
        snippet = snippet_el.get_text(" ", strip=True) if snippet_el else ""
        results.append({"url": href, "domain": domain, "title": title, "snippet": snippet})
        if len(results) >= limit:
            break
    return results


def _duckduckgo_results(query: str, timeout=8, limit=14):
    """Fallback when Google temporarily blocks automated result pages."""
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    response = requests.get(url, headers=SEARCH_HEADERS, timeout=timeout)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    results, seen = [], set()
    for item in soup.select(".result"):
        anchor = item.select_one(".result__a")
        if not anchor:
            continue
        href = anchor.get("href", "")
        # DDG redirect links often carry the destination in uddg.
        if "duckduckgo.com/l/" in href:
            href = unquote(parse_qs(urlparse(href).query).get("uddg", [href])[0])
        if not _is_useful_result(href) or href in seen:
            continue
        seen.add(href)
        snippet = item.select_one(".result__snippet")
        results.append({
            "url": href,
            "domain": _domain(href),
            "title": anchor.get_text(" ", strip=True),
            "snippet": snippet.get_text(" ", strip=True) if snippet else "",
        })
        if len(results) >= limit:
            break
    return results


def _extract_schema_product(soup: BeautifulSoup):
    products = []
    for script in soup.select("script[type='application/ld+json']"):
        try:
            data = json.loads(script.string or script.get_text() or "null")
        except Exception:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                item_type = item.get("@type")
                types = item_type if isinstance(item_type, list) else [item_type]
                if "Product" in types:
                    products.append(item)
                graph = item.get("@graph")
                if isinstance(graph, list):
                    stack.extend(graph)
            elif isinstance(item, list):
                stack.extend(item)
    return products[0] if products else {}


def _page_listing_data(url: str, timeout=7):
    """Read a public product page for structured title/price when the site allows it."""
    try:
        r = requests.get(url, headers=SEARCH_HEADERS, timeout=timeout, allow_redirects=True)
        if r.status_code >= 400 or not r.text:
            return {}
        soup = BeautifulSoup(r.text, "html.parser")
        product = _extract_schema_product(soup)
        title = product.get("name") if isinstance(product, dict) else None
        offers = product.get("offers") if isinstance(product, dict) else None
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        price = _num((offers or {}).get("price")) if isinstance(offers, dict) else None
        if price is None:
            for selector, attr in [
                ("meta[property='product:price:amount']", "content"),
                ("meta[itemprop='price']", "content"),
                ("[itemprop='price']", "content"),
            ]:
                el = soup.select_one(selector)
                if el:
                    price = _num(el.get(attr) or el.get_text(" ", strip=True))
                    if price is not None:
                        break
        if not title:
            title_el = soup.select_one("meta[property='og:title']")
            title = title_el.get("content") if title_el else None
        return {
            "title": title or "",
            "price": price,
            "finalUrl": r.url,
            "text": soup.get_text(" ", strip=True)[:12000],
        }
    except Exception:
        return {}



UNIT_MULTIPLIERS = {
    "oz": 1.0, "ounce": 1.0, "ounces": 1.0,
    "lb": 16.0, "lbs": 16.0, "pound": 16.0, "pounds": 16.0,
    "g": 0.035274, "gram": 0.035274, "grams": 0.035274,
    "kg": 35.274, "kilogram": 35.274, "kilograms": 35.274,
    "ml": 1.0, "milliliter": 1.0, "milliliters": 1.0,
    "l": 1000.0, "liter": 1000.0, "liters": 1000.0,
}

def _norm_text(value):
    value = str(value or "").lower()
    value = re.sub(r"[^a-z0-9.]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()

def _normalized_identifier(value):
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())

def _extract_pack_count(text):
    t = _norm_text(text)
    patterns = [
        r"\bpack of (\d{1,3})\b", r"\b(\d{1,3}) pack\b", r"\b(\d{1,3}) count\b",
        r"\b(\d{1,3}) ct\b", r"\bset of (\d{1,3})\b", r"\b(\d{1,3}) piece\b",
        r"\b(\d{1,3}) pc\b",
    ]
    for pat in patterns:
        m = re.search(pat, t)
        if m:
            return int(m.group(1))
    return None

def _extract_size(text):
    t = _norm_text(text)
    m = re.search(r"\b(\d+(?:\.\d+)?)\s*(oz|ounce|ounces|lb|lbs|pound|pounds|g|gram|grams|kg|kilogram|kilograms|ml|milliliter|milliliters|l|liter|liters)\b", t)
    if not m:
        return None
    amount, unit = float(m.group(1)), m.group(2)
    multiplier = UNIT_MULTIPLIERS.get(unit)
    if multiplier is None:
        return None
    family = "volume" if unit in {"ml","milliliter","milliliters","l","liter","liters"} else "weight"
    return family, round(amount * multiplier, 4)

def _extract_condition(text):
    t = _norm_text(text)
    for condition in ("refurbished", "renewed", "used", "open box", "pre owned"):
        if condition in t:
            return condition
    return "new"

def _variant_conflicts(source_text, listing_text):
    reasons = []
    sp, lp = _extract_pack_count(source_text), _extract_pack_count(listing_text)
    if sp and lp and sp != lp:
        reasons.append(f"pack count differs ({sp} vs {lp})")
    ss, ls = _extract_size(source_text), _extract_size(listing_text)
    if ss and ls and ss[0] == ls[0]:
        delta = abs(ss[1] - ls[1]) / max(ss[1], ls[1])
        if delta > 0.03:
            reasons.append("size/weight differs")
    sc, lc = _extract_condition(source_text), _extract_condition(listing_text)
    if sc != lc:
        reasons.append(f"condition differs ({sc} vs {lc})")
    return reasons

def _match_details(result, source, listing_text, url):
    source_text = " ".join(str(x or "") for x in [
        result.get("title"), source.get("name"), result.get("brand"), source.get("brand"),
        source.get("model"), result.get("modelNumber"), result.get("partNumber"),
        source.get("upc"), result.get("asin")
    ])
    hay = _norm_text(f"{listing_text} {url}")
    identifiers = {
        "UPC/EAN": source.get("upc"),
        "model": source.get("model") or result.get("modelNumber"),
        "part number": result.get("partNumber"),
        "ASIN": result.get("asin"),
    }
    matched_ids = []
    for label, value in identifiers.items():
        nid = _normalized_identifier(value)
        if nid and nid in _normalized_identifier(hay):
            matched_ids.append(label)
    brand = _norm_text(result.get("brand") or source.get("brand"))
    title_words = [w for w in _norm_text(result.get("title") or source.get("name")).split() if len(w) > 3]
    word_hits = sum(1 for w in title_words[:12] if w in hay)
    title_ratio = word_hits / max(1, min(len(title_words), 12))
    score = min(100, len(matched_ids) * 38 + (16 if brand and brand in hay else 0) + round(title_ratio * 38))
    conflicts = _variant_conflicts(source_text, listing_text)
    if conflicts:
        score = min(score, 29)
    if matched_ids:
        reason = "Matched " + ", ".join(matched_ids)
    elif brand and brand in hay:
        reason = "Brand and title terms match"
    else:
        reason = "Title-term similarity"
    if conflicts:
        reason += "; " + "; ".join(conflicts)
    label = "Exact / high confidence" if score >= 80 else "Probable" if score >= 55 else "Possible" if score >= 30 else "Needs review"
    return label, score, reason, conflicts

def _match_confidence(result, source, listing_text: str, url: str) -> tuple[str, int]:
    label, score, _, _ = _match_details(result, source, listing_text, url)
    return label, score


def research_competitors(result, source, timeout=8, max_results=12):
    query = _query(result, source)
    if not query:
        return []

    search_query = f'"{query}" buy price'
    try:
        raw = _google_results(search_query, timeout=timeout, limit=max_results * 2)
        search_engine = "Google"
    except Exception:
        raw = []
        search_engine = "DuckDuckGo fallback"
    if not raw:
        try:
            raw = _duckduckgo_results(query + " buy price", timeout=timeout, limit=max_results * 2)
            search_engine = "DuckDuckGo fallback"
        except Exception:
            return []

    found = []
    seen_domains_urls = set()
    amazon_domain = _domain(result.get("url", ""))

    for item in raw:
        url = item.get("url", "")
        domain = item.get("domain") or _domain(url)
        if not domain or (amazon_domain and domain == amazon_domain and "amazon" in domain):
            # Existing Amazon extraction already supplies the Amazon listing itself.
            continue
        key = (domain, url.split("?")[0])
        if key in seen_domains_urls:
            continue
        seen_domains_urls.add(key)

        text = " ".join([item.get("title", ""), item.get("snippet", "")])
        snippet_prices = [_num(x) for x in PRICE_RE.findall(text)]
        snippet_prices = [x for x in snippet_prices if x is not None]
        page = _page_listing_data(url, timeout=min(timeout, 7))
        page_title = page.get("title") or item.get("title") or ""
        price = page.get("price")
        if price is None and snippet_prices:
            price = min(snippet_prices)
        listing_text = " ".join([text, page_title, page.get("text", "")])
        confidence, score, match_reason, variant_conflicts = _match_details(
            result, source, listing_text, url
        )

        found.append({
            "retailer": _store_name(domain),
            "domain": domain,
            "title": page_title,
            "url": page.get("finalUrl") or url,
            "price": price,
            "snippet": item.get("snippet", ""),
            "matchConfidence": confidence,
            "matchScore": score,
            "matchReason": match_reason,
            "variantConflicts": variant_conflicts,
            "discoveredVia": search_engine,
        })
        if len(found) >= max_results:
            break

    found.sort(key=lambda x: (-int(x.get("matchScore") or 0), x.get("price") is None, x.get("price") or 10**9))
    return found


def _amazon_category_path(result) -> list[str]:
    return [str(x).strip() for x in (result.get("categories") or []) if str(x).strip()]


def categorize_product(result, source=None):
    source = source or result.get("sourceInput") or {}
    explicit_category = str(source.get("category") or "").strip()
    explicit_subcategory = str(source.get("subcategory") or "").strip()
    amazon_path = _amazon_category_path(result)
    if explicit_category:
        return {
            "category": explicit_category,
            "subcategory": explicit_subcategory or (amazon_path[-1] if amazon_path else "General"),
            "amazonPath": amazon_path,
            "source": "Imported catalog category",
        }
    text = " ".join([
        " ".join(amazon_path), result.get("title", ""), result.get("description", ""),
        result.get("brand", ""), source.get("name", ""), source.get("brand", ""),
    ]).lower()

    for category, subcategory, keywords in CATEGORY_RULES:
        if any(keyword in text for keyword in keywords):
            return {
                "category": category,
                "subcategory": subcategory,
                "amazonPath": amazon_path,
                "source": "Amazon path + product data" if amazon_path else "Product data",
            }

    if amazon_path:
        broad = amazon_path[0]
        leaf = amazon_path[-1] if len(amazon_path) > 1 else "General"
        return {"category": broad, "subcategory": leaf, "amazonPath": amazon_path, "source": "Amazon category path"}
    return {"category": "Other", "subcategory": "General Merchandise", "amazonPath": [], "source": "Fallback"}


def _product_price(result):
    pricing = result.get("pricing") or {}
    return _num(pricing.get("suggestedPrice")) or _num(result.get("price")) or _num((result.get("sourceInput") or {}).get("cost"))


def _catalog_identity(result, index):
    source = result.get("sourceInput") or {}
    return str(result.get("asin") or source.get("sku") or source.get("upc") or source.get("model") or f"catalog-{index}")


def _recommendation_payload(candidate, index, reason):
    source = candidate.get("sourceInput") or {}
    return {
        "id": _catalog_identity(candidate, index),
        "title": candidate.get("title") or source.get("name") or source.get("sku") or "Inventory item",
        "asin": candidate.get("asin") or source.get("asin") or "",
        "sku": source.get("sku") or "",
        "price": _product_price(candidate),
        "image": (candidate.get("images") or [""])[0],
        "category": (candidate.get("catalogCategory") or {}).get("category", ""),
        "subcategory": (candidate.get("catalogCategory") or {}).get("subcategory", ""),
        "reason": reason,
    }


def _cross_score(base, candidate):
    bc = base.get("catalogCategory") or {}
    cc = candidate.get("catalogCategory") or {}
    bcat, bsub = bc.get("category"), bc.get("subcategory")
    ccat, csub = cc.get("category"), cc.get("subcategory")
    score, reason = 0, "Related inventory item"
    if csub in COMPLEMENTARY.get(bsub, set()):
        score += 70
        reason = f"Complements {bsub}"
    elif bcat and bcat == ccat and bsub != csub:
        score += 48
        reason = f"Related {bcat} item"
    elif ccat in COMPLEMENTARY.get(bsub, set()):
        score += 42
        reason = f"Useful companion to {bsub}"
    brand_a = (base.get("brand") or "").lower()
    brand_b = (candidate.get("brand") or "").lower()
    if brand_a and brand_a == brand_b:
        score += 10
    qty = _num((candidate.get("sourceInput") or {}).get("quantity"))
    if qty is not None and qty <= 0:
        return -1, reason
    return score, reason


def _upsell_score(base, candidate):
    bc = base.get("catalogCategory") or {}
    cc = candidate.get("catalogCategory") or {}
    if not bc.get("subcategory") or bc.get("subcategory") != cc.get("subcategory"):
        return -1, ""
    base_price, cand_price = _product_price(base), _product_price(candidate)
    if base_price is None or cand_price is None or cand_price <= base_price * 1.05:
        return -1, ""
    ratio = cand_price / base_price if base_price else 10
    if ratio > 3.5:
        return -1, ""
    score = 50
    brand_a = (base.get("brand") or "").lower()
    brand_b = (candidate.get("brand") or "").lower()
    if brand_a and brand_a == brand_b:
        score += 20
    score += max(0, 20 - abs(ratio - 1.4) * 20)
    qty = _num((candidate.get("sourceInput") or {}).get("quantity"))
    if qty is not None and qty <= 0:
        return -1, ""
    return score, f"Higher-value {bc.get('subcategory')} option"


def enrich_catalog(results, max_cross_sells=8, max_upsells=8):
    """Categorize the full catalog and use only catalog inventory for related-item suggestions."""
    for result in results:
        result["catalogCategory"] = categorize_product(result, result.get("sourceInput") or {})

    for i, base in enumerate(results):
        cross, up = [], []
        base_id = _catalog_identity(base, i)
        for j, candidate in enumerate(results):
            if i == j or _catalog_identity(candidate, j) == base_id:
                continue
            cross_score, cross_reason = _cross_score(base, candidate)
            if cross_score > 0:
                cross.append((cross_score, j, cross_reason, candidate))
            up_score, up_reason = _upsell_score(base, candidate)
            if up_score > 0:
                up.append((up_score, j, up_reason, candidate))

        cross.sort(key=lambda x: (-x[0], -(_product_price(x[3]) or 0)))
        up.sort(key=lambda x: (-x[0], _product_price(x[3]) or 10**9))
        base["crossSells"] = [_recommendation_payload(c, j, reason) for _, j, reason, c in cross[:max_cross_sells]]
        base["upsells"] = [_recommendation_payload(c, j, reason) for _, j, reason, c in up[:max_upsells]]

    return results


def catalog_summary(results):
    categories = Counter()
    subcategories = Counter()
    for result in results:
        cat = result.get("catalogCategory") or {}
        if cat.get("category"):
            categories[cat["category"]] += 1
        if cat.get("subcategory"):
            subcategories[cat["subcategory"]] += 1
    prices = [_product_price(r) for r in results]
    prices = [p for p in prices if p is not None]
    costs = [_num((r.get("sourceInput") or {}).get("cost")) for r in results]
    costs = [c for c in costs if c is not None]
    quantities = [_num((r.get("sourceInput") or {}).get("quantity")) for r in results]
    quantities = [q for q in quantities if q is not None]
    margins = [r.get("pricing", {}).get("estimatedMargin") for r in results]
    margins = [m for m in margins if isinstance(m, (int, float))]
    return {
        "categories": dict(categories.most_common()),
        "subcategories": dict(subcategories.most_common()),
        "totalProducts": len(results),
        "totalUnits": int(sum(quantities)) if quantities else None,
        "estimatedCatalogRetailValue": round(sum(prices), 2) if prices else None,
        "knownCatalogCost": round(sum(costs), 2) if costs else None,
        "averageEstimatedMargin": round(statistics.mean(margins), 1) if margins else None,
        "productsWithCompetitors": sum(1 for r in results if r.get("competitors")),
        "productsNeedingReview": sum(1 for r in results if r.get("status") != "Complete"),
        "totalCrossSellSuggestions": sum(len(r.get("crossSells") or []) for r in results),
        "totalUpsellSuggestions": sum(len(r.get("upsells") or []) for r in results),
    }


def add_intelligence(result, source):
    competitors = research_competitors(result, source)
    amazon_price = _num(result.get("price"))
    market_prices = [x["price"] for x in competitors if x.get("price") is not None and (x.get("matchScore") or 0) >= 30]
    if amazon_price:
        market_prices.append(amazon_price)
    cost = _num(source.get("cost"))
    shipping_cost = _num(source.get("shipping_cost") or source.get("shippingCost")) or 0
    fixed_fees = _num(source.get("fees") or source.get("fixed_fees") or source.get("fixedFees")) or 0
    fee_rate = _num(source.get("fee_rate") or source.get("feeRate")) or 0
    avg = round(statistics.mean(market_prices), 2) if market_prices else None
    low = round(min(market_prices), 2) if market_prices else None
    high = round(max(market_prices), 2) if market_prices else None
    suggested = round(avg * 0.98, 2) if avg else amazon_price
    break_even = round(cost + shipping_cost + fixed_fees, 2) if cost is not None else None
    if break_even is not None and fee_rate and 0 <= fee_rate < 100:
        break_even = round(break_even / (1 - fee_rate / 100), 2)
    variable_fees = round((suggested or 0) * fee_rate / 100, 2) if suggested else 0
    profit = round(suggested - cost - shipping_cost - fixed_fees - variable_fees, 2) if suggested is not None and cost is not None else None
    margin = round((profit / suggested) * 100, 1) if profit is not None and suggested else None
    result["competitors"] = competitors
    competitive = round(low * 0.99, 2) if low else suggested
    premium = round(high * 1.05, 2) if high else (round(suggested * 1.10, 2) if suggested else None)
    result["pricing"] = {
        "cost": cost,
        "marketLow": low,
        "marketAverage": avg,
        "marketHigh": high,
        "suggestedPrice": suggested,
        "competitivePrice": competitive,
        "premiumPrice": premium,
        "estimatedProfit": profit,
        "estimatedMargin": margin,
        "breakEven": break_even,
        "shippingCost": shipping_cost,
        "fixedFees": fixed_fees,
        "feeRate": fee_rate,
        "comparableListings": len([x for x in competitors if (x.get("matchScore") or 0) >= 30]),
    }
    result["identification"] = {
        "status": "Exact/identifier match" if (result.get("asin") or source.get("upc") or source.get("model")) else "Name-based match",
        "identifiers": {k: v for k, v in {
            "asin": result.get("asin") or source.get("asin"), "sku": source.get("sku"),
            "upc": source.get("upc"), "model": source.get("model"),
        }.items() if v},
    }
    result["catalogCategory"] = categorize_product(result, source)
    return result

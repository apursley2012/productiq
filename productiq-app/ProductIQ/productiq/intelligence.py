from __future__ import annotations

import json
import re
import statistics
from collections import Counter
from urllib.parse import parse_qs, quote_plus, unquote, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup


PRICE_RE = re.compile(r"(?:US\s*)?\$\s?([0-9]{1,7}(?:,[0-9]{3})*(?:\.\d{2})?)", re.I)
SEARCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

SKIP_DOMAINS = {
    "google.com", "bing.com", "duckduckgo.com", "youtube.com", "facebook.com",
    "instagram.com", "pinterest.com", "tiktok.com", "reddit.com", "x.com",
    "twitter.com", "linkedin.com", "wikipedia.org",
}

# A deliberately broad resale-store taxonomy.  The final fallback also preserves
# Amazon/schema categories, so an item is never dependent on this list alone.
CATEGORY_TAXONOMY = {
    "Electronics": {
        "Computers & Accessories": ("laptop", "notebook computer", "desktop computer", "monitor", "keyboard", "mouse", "webcam", "computer stand", "laptop stand", "usb hub", "docking station", "ssd", "hard drive", "flash drive", "memory card", "ram", "computer cable"),
        "Audio & Headphones": ("headphone", "earbud", "speaker", "soundbar", "microphone", "audio interface", "turntable", "stereo", "bluetooth audio"),
        "TV & Home Theater": ("television", "smart tv", "streaming stick", "roku", "fire tv", "projector", "projector screen", "hdmi", "tv mount", "remote control"),
        "Cameras & Photography": ("camera", "digital camera", "dslr", "mirrorless", "camera lens", "tripod", "camera bag", "action camera", "photo printer"),
        "Wearable Technology": ("smartwatch", "fitness tracker", "smart ring", "wearable"),
        "GPS & Navigation": ("gps", "navigation", "radar detector"),
        "Electronic Accessories": ("charger", "power adapter", "power bank", "surge protector", "extension cable", "usb cable", "battery charger", "electronics case"),
    },
    "Cell Phones & Accessories": {
        "Cell Phones": ("smartphone", "cell phone", "mobile phone", "iphone", "android phone"),
        "Cases & Screen Protection": ("phone case", "iphone case", "screen protector", "tempered glass", "phone cover"),
        "Chargers & Cables": ("phone charger", "wireless charger", "magsafe", "charging cable", "lightning cable", "usb c cable"),
        "Mounts & Holders": ("phone mount", "phone holder", "car phone mount", "phone stand"),
        "Mobile Accessories": ("sim card", "stylus", "phone grip", "selfie stick", "mobile accessory"),
    },
    "Home & Kitchen": {
        "Kitchen & Dining": ("cookware", "frying pan", "saucepan", "pot", "kitchen knife", "cutlery", "flatware", "utensil", "tumbler", "mug", "cup", "food container", "storage container", "cutting board", "bakeware", "mixing bowl"),
        "Small Appliances": ("air fryer", "coffee maker", "blender", "toaster", "slow cooker", "pressure cooker", "rice cooker", "mixer", "electric kettle", "waffle maker", "food processor"),
        "Bedding": ("sheet set", "bedsheet", "pillowcase", "comforter", "duvet", "blanket", "quilt", "mattress pad", "mattress topper", "bed skirt"),
        "Bath": ("bath towel", "hand towel", "washcloth", "shower curtain", "bath mat", "bathroom organizer", "soap dispenser"),
        "Home Decor": ("curtain", "rug", "wall decor", "picture frame", "candle holder", "vase", "decorative pillow", "clock", "mirror", "artificial plant"),
        "Furniture": ("chair", "table", "desk", "shelf", "bookcase", "dresser", "nightstand", "stool", "ottoman", "cabinet"),
        "Furniture Accessories": ("chair leg", "floor protector", "furniture pad", "furniture cover", "slipcover", "felt pad", "caster cup", "table protector"),
        "Storage & Organization": ("organizer", "storage bin", "storage basket", "closet", "hanger", "drawer organizer", "shoe rack", "shelf liner"),
        "Cleaning Supplies": ("vacuum", "mop", "broom", "duster", "cleaning brush", "microfiber cloth", "cleaner", "scrub", "sponges"),
        "Heating Cooling & Air Quality": ("fan", "space heater", "humidifier", "dehumidifier", "air purifier", "thermostat"),
        "Lighting": ("lamp", "light fixture", "night light", "desk lamp", "floor lamp"),
    },
    "Appliances": {
        "Major Appliances": ("refrigerator", "freezer", "dishwasher", "washing machine", "dryer", "range", "oven", "microwave"),
        "Appliance Parts & Accessories": ("water filter", "refrigerator filter", "appliance part", "washer hose", "dryer vent", "replacement filter"),
    },
    "Beauty & Personal Care": {
        "Skin Care": ("moisturizer", "face serum", "cleanser", "facial cleanser", "skin care", "skincare", "sunscreen", "face cream", "toner", "acne"),
        "Hair Care": ("shampoo", "conditioner", "hair mask", "hair oil", "hair spray", "hair brush", "comb", "hair care"),
        "Hair Styling Tools": ("hair dryer", "blow dryer", "curling iron", "flat iron", "straightener", "hot brush"),
        "Makeup": ("mascara", "lipstick", "lip gloss", "foundation", "concealer", "eyeshadow", "eyeliner", "blush", "makeup"),
        "Nail Care": ("nail polish", "gel polish", "manicure", "pedicure", "nail file", "nail lamp"),
        "Fragrance": ("perfume", "cologne", "body spray", "fragrance"),
        "Personal Care": ("razor", "shaver", "toothbrush", "water flosser", "deodorant", "body wash", "soap", "oral care"),
        "Beauty Tools": ("makeup brush", "beauty sponge", "mirror", "eyelash curler", "tweezers"),
    },
    "Health & Household": {
        "Vitamins & Supplements": ("vitamin", "supplement", "mineral", "probiotic", "multivitamin"),
        "Medical Supplies": ("thermometer", "blood pressure", "pulse oximeter", "first aid", "bandage", "brace", "compression", "heating pad", "medical"),
        "Household Supplies": ("paper towel", "toilet paper", "trash bag", "detergent", "dish soap", "laundry pod", "fabric softener", "household cleaner"),
        "Wellness & Relaxation": ("massager", "massage gun", "aromatherapy", "essential oil", "sleep mask"),
    },
    "Clothing, Shoes & Jewelry": {
        "Women's Clothing": ("women's", "womens", "woman dress", "blouse", "women shirt", "leggings", "women pants", "bra", "skirt", "women jacket"),
        "Men's Clothing": ("men's", "mens", "men shirt", "men pants", "men jacket", "boxer", "necktie", "men shorts"),
        "Kids' Clothing": ("girls clothing", "boys clothing", "kids shirt", "kids pants", "school uniform"),
        "Shoes": ("shoe", "sneaker", "boot", "sandal", "slipper", "clog", "loafer", "heel"),
        "Jewelry": ("earring", "necklace", "bracelet", "ring", "anklet", "brooch", "jewelry", "jewellery"),
        "Watches": ("watch", "wristwatch"),
        "Handbags & Wallets": ("purse", "handbag", "wallet", "card holder", "clutch", "crossbody bag", "tote bag"),
        "Accessories": ("belt", "scarf", "hat", "cap", "gloves", "sunglasses", "hair accessory"),
    },
    "Baby": {
        "Diapering": ("diaper", "baby wipe", "changing pad", "diaper bag", "diaper pail"),
        "Feeding": ("baby bottle", "bottle warmer", "breast pump", "sippy cup", "baby feeding", "high chair"),
        "Nursery": ("crib", "bassinet", "baby monitor", "crib sheet", "nursery"),
        "Strollers & Car Seats": ("stroller", "infant car seat", "baby car seat", "travel system"),
        "Baby Care": ("pacifier", "teether", "baby bath", "baby grooming", "swaddle"),
    },
    "Toys & Games": {
        "Action Figures & Dolls": ("action figure", "doll", "dollhouse", "play figure"),
        "Building Toys": ("building blocks", "lego", "building set", "construction toy"),
        "Arts & Crafts for Kids": ("kids craft", "slime kit", "coloring kit", "activity kit"),
        "Pretend Play": ("play kitchen", "dress up", "pretend play", "playset"),
        "Games": ("board game", "card game", "tabletop game", "party game"),
        "Puzzles": ("puzzle", "jigsaw"),
        "Outdoor Toys": ("water toy", "playground", "scooter", "ride on toy", "outdoor toy"),
        "Plush": ("plush", "stuffed animal"),
        "Educational Toys": ("stem toy", "learning toy", "educational toy"),
    },
    "Sports & Outdoors": {
        "Exercise & Fitness": ("dumbbell", "kettlebell", "yoga mat", "resistance band", "exercise", "fitness", "workout", "treadmill", "exercise bike"),
        "Camping & Hiking": ("camping", "tent", "sleeping bag", "hiking", "camp stove", "camp chair", "headlamp"),
        "Fishing": ("fishing", "fishing rod", "reel", "tackle", "fishing lure"),
        "Hunting": ("hunting", "game call", "hunting blind"),
        "Team Sports": ("basketball", "football", "soccer", "baseball", "softball", "volleyball"),
        "Outdoor Recreation": ("cooler", "hammock", "binocular", "outdoor recreation", "beach chair"),
        "Cycling": ("bicycle", "bike helmet", "bike light", "cycling", "bike accessory"),
        "Water Sports": ("kayak", "paddle board", "snorkel", "swim", "life jacket"),
    },
    "Pet Supplies": {
        "Dog Supplies": ("dog", "puppy", "dog leash", "dog collar", "dog toy", "dog bed", "dog bowl", "dog treat"),
        "Cat Supplies": ("cat", "kitten", "cat litter", "cat toy", "cat tree", "scratcher", "cat bowl"),
        "Aquarium Supplies": ("aquarium", "fish tank", "fish food", "aquarium filter"),
        "Bird Supplies": ("bird cage", "bird food", "bird toy", "parrot"),
        "Small Animal Supplies": ("hamster", "guinea pig", "rabbit cage", "small animal"),
        "Pet Grooming": ("pet grooming", "pet brush", "pet shampoo", "nail grinder"),
    },
    "Automotive": {
        "Interior Accessories": ("car seat cover", "floor mat", "steering wheel cover", "car organizer", "sun shade"),
        "Exterior Accessories": ("car cover", "license plate frame", "mud flap", "truck accessory"),
        "Electronics": ("dash cam", "car charger", "car stereo", "carplay", "backup camera"),
        "Tools & Equipment": ("jump starter", "tire inflator", "diagnostic scanner", "obd", "car jack"),
        "Replacement Parts": ("brake pad", "spark plug", "air filter", "oil filter", "wiper blade", "automotive part"),
        "Car Care": ("car wash", "car wax", "detailing", "tire shine", "car cleaner"),
    },
    "Tools & Home Improvement": {
        "Power Tools": ("power drill", "impact driver", "circular saw", "jigsaw", "sander", "power tool", "grinder"),
        "Hand Tools": ("screwdriver", "wrench", "socket set", "hammer", "pliers", "hand tool", "ratchet"),
        "Hardware": ("screw", "bolt", "nut", "fastener", "door hardware", "cabinet hardware", "bracket"),
        "Electrical": ("extension cord", "outlet", "switch", "electrical wire", "breaker", "electrical"),
        "Plumbing": ("faucet", "shower head", "pipe fitting", "plumbing", "drain"),
        "Paint & Supplies": ("paint roller", "paint brush", "drop cloth", "paint sprayer", "painting supplies"),
        "Safety & Security": ("smoke detector", "carbon monoxide", "safe", "lock", "security camera", "doorbell camera"),
        "Home Improvement": ("weather stripping", "caulk", "sealant", "wall repair", "home improvement"),
    },
    "Patio, Lawn & Garden": {
        "Gardening": ("garden", "planter", "plant pot", "potting soil", "garden tool", "watering can"),
        "Lawn Care": ("lawn", "grass seed", "weed", "sprinkler", "garden hose", "lawn mower"),
        "Patio Furniture": ("patio chair", "patio table", "outdoor furniture", "patio umbrella"),
        "Grills & Outdoor Cooking": ("grill", "smoker", "bbq", "grilling tool"),
        "Outdoor Decor": ("outdoor light", "garden decor", "wind chime", "bird feeder"),
    },
    "Office Products": {
        "Writing Supplies": ("pen", "pencil", "marker", "highlighter", "eraser"),
        "Paper & Notebooks": ("notebook", "journal", "printer paper", "index card", "sticky note"),
        "Desk Accessories": ("desk organizer", "stapler", "tape dispenser", "paper clip", "desk mat"),
        "Office Electronics": ("printer", "scanner", "label maker", "calculator", "shredder"),
        "Mailing & Shipping": ("shipping label", "mailer", "packing tape", "envelope"),
        "School Supplies": ("school supply", "binder", "folder", "pencil case", "backpack school"),
    },
    "Arts, Crafts & Sewing": {
        "Painting & Drawing": ("acrylic paint", "watercolor", "paint brush", "canvas", "drawing pencil", "sketchbook"),
        "Craft Supplies": ("craft", "glue gun", "pom pom", "craft paper", "vinyl", "cricut", "scrapbook"),
        "Sewing": ("sewing", "thread", "fabric", "needle", "sewing machine", "zipper"),
        "Knitting & Crochet": ("yarn", "knitting", "crochet", "crochet hook"),
        "Jewelry Making": ("jewelry making", "bead", "jewelry findings", "resin mold"),
    },
    "Grocery & Gourmet Food": {
        "Coffee & Tea": ("coffee", "tea", "coffee pod", "k cup"),
        "Snacks": ("snack", "chips", "cracker", "popcorn", "pretzel"),
        "Candy & Chocolate": ("candy", "chocolate", "gummy"),
        "Beverages": ("drink", "beverage", "soda", "juice", "energy drink", "water"),
        "Pantry Staples": ("pasta", "rice", "sauce", "seasoning", "spice", "flour", "cereal"),
        "Baking": ("baking mix", "cake mix", "frosting", "baking ingredient"),
    },
    "Industrial & Scientific": {
        "Lab & Scientific": ("laboratory", "lab equipment", "microscope", "pipette", "scientific"),
        "Industrial Supplies": ("industrial", "shop supply", "abrasive", "adhesive tape", "industrial fastener"),
        "Material Handling": ("safety cone", "hand truck", "caster", "warehouse", "material handling"),
        "Occupational Safety": ("safety glasses", "hard hat", "work gloves", "respirator", "ppe"),
    },
    "Musical Instruments": {
        "Guitars & Accessories": ("guitar", "guitar string", "guitar strap", "guitar pedal"),
        "Keyboards & Pianos": ("keyboard piano", "digital piano", "midi keyboard"),
        "Drums & Percussion": ("drum", "drumstick", "percussion"),
        "Microphones & Pro Audio": ("studio microphone", "audio mixer", "pa speaker", "microphone stand"),
        "Instrument Accessories": ("music stand", "instrument case", "tuner", "metronome"),
    },
    "Video Games": {
        "Consoles": ("playstation", "xbox console", "nintendo switch", "game console"),
        "Games": ("video game", "ps5 game", "xbox game", "switch game"),
        "Controllers & Accessories": ("game controller", "gaming headset", "controller charger", "console case"),
    },
    "Books, Movies & Music": {
        "Books": ("paperback", "hardcover", "book", "novel", "workbook"),
        "Movies & TV": ("dvd", "blu ray", "movie disc"),
        "Music": ("vinyl record", "music cd", "audio cd"),
    },
    "Travel & Luggage": {
        "Luggage": ("suitcase", "carry on", "luggage"),
        "Travel Accessories": ("packing cube", "travel pillow", "luggage tag", "passport holder", "travel adapter"),
        "Backpacks": ("backpack", "daypack"),
    },
}

TOP_CATEGORY_ALIASES = {
    "electronics": "Electronics",
    "computer": "Electronics",
    "cell phone": "Cell Phones & Accessories",
    "mobile": "Cell Phones & Accessories",
    "home": "Home & Kitchen",
    "kitchen": "Home & Kitchen",
    "appliance": "Appliances",
    "beauty": "Beauty & Personal Care",
    "health": "Health & Household",
    "household": "Health & Household",
    "clothing": "Clothing, Shoes & Jewelry",
    "shoe": "Clothing, Shoes & Jewelry",
    "jewelry": "Clothing, Shoes & Jewelry",
    "baby": "Baby",
    "toy": "Toys & Games",
    "game": "Toys & Games",
    "sport": "Sports & Outdoors",
    "outdoor": "Sports & Outdoors",
    "pet": "Pet Supplies",
    "automotive": "Automotive",
    "car": "Automotive",
    "tool": "Tools & Home Improvement",
    "hardware": "Tools & Home Improvement",
    "garden": "Patio, Lawn & Garden",
    "patio": "Patio, Lawn & Garden",
    "office": "Office Products",
    "school": "Office Products",
    "craft": "Arts, Crafts & Sewing",
    "grocery": "Grocery & Gourmet Food",
    "food": "Grocery & Gourmet Food",
    "industrial": "Industrial & Scientific",
    "music": "Musical Instruments",
    "instrument": "Musical Instruments",
    "video game": "Video Games",
    "book": "Books, Movies & Music",
    "travel": "Travel & Luggage",
    "luggage": "Travel & Luggage",
}

COMPLEMENTARY = {
    "Computers & Accessories": {"Electronic Accessories", "Audio & Headphones", "Office Electronics", "Desk Accessories"},
    "Audio & Headphones": {"Electronic Accessories", "Computers & Accessories"},
    "TV & Home Theater": {"Electronic Accessories", "Audio & Headphones"},
    "Cell Phones": {"Cases & Screen Protection", "Chargers & Cables", "Mounts & Holders", "Mobile Accessories"},
    "Cases & Screen Protection": {"Chargers & Cables", "Mounts & Holders", "Mobile Accessories"},
    "Kitchen & Dining": {"Small Appliances", "Storage & Organization", "Cleaning Supplies"},
    "Small Appliances": {"Kitchen & Dining", "Cleaning Supplies"},
    "Bedding": {"Bath", "Home Decor", "Storage & Organization"},
    "Furniture": {"Furniture Accessories", "Home Decor", "Lighting"},
    "Furniture Accessories": {"Furniture", "Home Decor"},
    "Skin Care": {"Makeup", "Beauty Tools", "Personal Care"},
    "Hair Care": {"Hair Styling Tools", "Beauty Tools"},
    "Makeup": {"Skin Care", "Beauty Tools"},
    "Women's Clothing": {"Shoes", "Jewelry", "Handbags & Wallets", "Accessories"},
    "Men's Clothing": {"Shoes", "Watches", "Accessories", "Handbags & Wallets"},
    "Shoes": {"Accessories", "Handbags & Wallets"},
    "Diapering": {"Baby Care", "Feeding", "Nursery"},
    "Feeding": {"Baby Care", "Nursery"},
    "Dog Supplies": {"Pet Grooming"},
    "Cat Supplies": {"Pet Grooming"},
    "Exercise & Fitness": {"Wellness & Relaxation", "Medical Supplies", "Outdoor Recreation"},
    "Camping & Hiking": {"Outdoor Recreation", "Lighting", "Travel Accessories"},
    "Power Tools": {"Hand Tools", "Hardware", "Occupational Safety"},
    "Hand Tools": {"Hardware", "Occupational Safety"},
    "Painting & Drawing": {"Craft Supplies"},
    "Sewing": {"Craft Supplies"},
    "Luggage": {"Travel Accessories", "Backpacks"},
    "Consoles": {"Games", "Controllers & Accessories"},
}


def _num(value):
    if value is None or value == "":
        return None
    match = re.search(r"(-?[0-9]+(?:\.[0-9]+)?)", str(value).replace(",", ""))
    return float(match.group(1)) if match else None


def _norm_text(value):
    value = str(value or "").lower()
    value = re.sub(r"[^a-z0-9.]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _normalized_identifier(value):
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _domain(url: str) -> str:
    host = urlparse(url or "").netloc.lower().split(":")[0]
    return host[4:] if host.startswith("www.") else host


def _store_name(domain: str) -> str:
    known = {
        "walmart.com": "Walmart", "ebay.com": "eBay", "target.com": "Target",
        "bestbuy.com": "Best Buy", "amazon.com": "Amazon", "homedepot.com": "The Home Depot",
        "lowes.com": "Lowe's", "macys.com": "Macy's", "kohls.com": "Kohl's",
        "wayfair.com": "Wayfair", "etsy.com": "Etsy", "newegg.com": "Newegg",
        "costco.com": "Costco", "samsclub.com": "Sam's Club", "staples.com": "Staples",
        "officedepot.com": "Office Depot", "walgreens.com": "Walgreens", "cvs.com": "CVS",
        "sephora.com": "Sephora", "ulta.com": "Ulta Beauty", "chewy.com": "Chewy",
        "petsmart.com": "PetSmart", "petco.com": "Petco", "academy.com": "Academy Sports + Outdoors",
        "autozone.com": "AutoZone", "oreillyauto.com": "O'Reilly Auto Parts",
        "jcpenney.com": "JCPenney", "nordstrom.com": "Nordstrom", "zappos.com": "Zappos",
        "dickssportinggoods.com": "DICK'S Sporting Goods", "harborfreight.com": "Harbor Freight",
        "tractorsupply.com": "Tractor Supply", "acehardware.com": "Ace Hardware",
    }
    for key, value in known.items():
        if domain == key or domain.endswith("." + key):
            return value
    core = domain.split(".")[0].replace("-", " ")
    return core.title() if core else "Online retailer"


def _is_useful_result(url: str) -> bool:
    domain = _domain(url)
    if not domain or not url.startswith("http"):
        return False
    return not any(domain == d or domain.endswith("." + d) for d in SKIP_DOMAINS)


def _unwrap_google_url(href: str) -> str:
    if href.startswith("/url?"):
        return unquote(parse_qs(urlparse(href).query).get("q", [""])[0])
    return href


def _google_results(query: str, timeout=5, limit=18):
    response = requests.get(
        f"https://www.google.com/search?num={min(limit + 4, 30)}&q={quote_plus(query)}",
        headers=SEARCH_HEADERS, timeout=timeout,
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    results, seen = [], set()
    for anchor in soup.select("div.yuRUbf > a, a[jsname='UWckNb'], div.g a"):
        href = _unwrap_google_url(anchor.get("href", ""))
        if not _is_useful_result(href) or href in seen:
            continue
        seen.add(href)
        block = anchor.find_parent("div", class_="g") or anchor.parent
        title_el = anchor.select_one("h3") or (block.select_one("h3") if block else None)
        snippet_el = block.select_one("div.VwiC3b, div[data-sncf], span.aCOpRe") if block else None
        results.append({
            "url": href,
            "domain": _domain(href),
            "title": title_el.get_text(" ", strip=True) if title_el else anchor.get_text(" ", strip=True),
            "snippet": snippet_el.get_text(" ", strip=True) if snippet_el else "",
            "provider": "Google",
        })
        if len(results) >= limit:
            break
    return results


def _bing_results(query: str, timeout=5, limit=18):
    response = requests.get(
        f"https://www.bing.com/search?q={quote_plus(query)}&count={min(limit + 5, 30)}",
        headers=SEARCH_HEADERS, timeout=timeout,
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    results, seen = [], set()
    for item in soup.select("li.b_algo"):
        anchor = item.select_one("h2 a[href]")
        if not anchor:
            continue
        href = anchor.get("href", "")
        if not _is_useful_result(href) or href in seen:
            continue
        seen.add(href)
        snippet = item.select_one(".b_caption p, .b_snippet")
        results.append({
            "url": href,
            "domain": _domain(href),
            "title": anchor.get_text(" ", strip=True),
            "snippet": snippet.get_text(" ", strip=True) if snippet else "",
            "provider": "Bing",
        })
        if len(results) >= limit:
            break
    return results


def _duckduckgo_results(query: str, timeout=5, limit=18):
    response = requests.get(
        f"https://html.duckduckgo.com/html/?q={quote_plus(query)}",
        headers=SEARCH_HEADERS, timeout=timeout,
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    results, seen = [], set()
    for item in soup.select(".result"):
        anchor = item.select_one(".result__a")
        if not anchor:
            continue
        href = anchor.get("href", "")
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
            "provider": "DuckDuckGo",
        })
        if len(results) >= limit:
            break
    return results


def _extract_schema_product(soup: BeautifulSoup):
    queue = []
    for script in soup.select("script[type='application/ld+json']"):
        try:
            queue.append(json.loads(script.string or script.get_text() or "null"))
        except Exception:
            pass
    while queue:
        item = queue.pop()
        if isinstance(item, list):
            queue.extend(item)
            continue
        if not isinstance(item, dict):
            continue
        item_type = item.get("@type")
        types = item_type if isinstance(item_type, list) else [item_type]
        if "Product" in types:
            return item
        graph = item.get("@graph")
        if isinstance(graph, list):
            queue.extend(graph)
    return {}


def _brand_value(value):
    if isinstance(value, dict):
        return value.get("name") or ""
    return value or ""


def _offer_price(offers):
    if isinstance(offers, list):
        for offer in offers:
            price = _offer_price(offer)
            if price is not None:
                return price
        return None
    if not isinstance(offers, dict):
        return None
    return _num(offers.get("price") or offers.get("lowPrice") or offers.get("highPrice"))


def _validate_url(url: str) -> str:
    try:
        if "/../" in url or re.search(r"/%2e%2e/", url, re.IGNORECASE):
            raise ValueError("Invalid path")
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError("Invalid protocol")
        if not parsed.hostname:
            raise ValueError("Invalid host")
        return url
    except Exception:
        raise ValueError("Invalid URL")


def _page_listing_data(url: str, timeout=4.5):
    try:
        validated_url = _validate_url(url)
        response = requests.get(validated_url, headers=SEARCH_HEADERS, timeout=timeout, allow_redirects=True)
        if response.status_code >= 400 or not response.text:
            return {}
        soup = BeautifulSoup(response.text, "html.parser")
        product = _extract_schema_product(soup)
        offers = product.get("offers") if isinstance(product, dict) else None
        price = _offer_price(offers)
        if price is None:
            for selector, attr in [
                ("meta[property='product:price:amount']", "content"),
                ("meta[itemprop='price']", "content"),
                ("[itemprop='price']", "content"),
            ]:
                node = soup.select_one(selector)
                if node:
                    price = _num(node.get(attr) or node.get_text(" ", strip=True))
                    if price is not None:
                        break
        if price is None:
            visible_prices = [_num(x) for x in PRICE_RE.findall(soup.get_text(" ", strip=True)[:9000])]
            visible_prices = [x for x in visible_prices if x is not None]
            if visible_prices:
                price = min(visible_prices)

        title = product.get("name") if isinstance(product, dict) else ""
        if not title:
            node = soup.select_one("meta[property='og:title'], title")
            title = node.get("content") if node and node.has_attr("content") else (node.get_text(" ", strip=True) if node else "")

        categories = []
        schema_category = product.get("category") if isinstance(product, dict) else None
        if isinstance(schema_category, str) and schema_category.strip():
            categories.append(schema_category.strip())
        for node in soup.select("[itemprop='itemListElement'] [itemprop='name'], nav[aria-label*='breadcrumb' i] a, .breadcrumb a"):
            value = node.get("content") or node.get_text(" ", strip=True)
            if value and value not in categories:
                categories.append(value)

        identifiers = {}
        for key in ("sku", "mpn", "gtin", "gtin8", "gtin12", "gtin13", "gtin14", "productID"):
            value = product.get(key) if isinstance(product, dict) else None
            if value:
                identifiers[key] = str(value)

        return {
            "title": str(title or ""),
            "price": price,
            "finalUrl": response.url,
            "text": soup.get_text(" ", strip=True)[:14000],
            "brand": _brand_value(product.get("brand")) if isinstance(product, dict) else "",
            "categories": categories,
            "identifiers": identifiers,
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


def _extract_pack_count(text):
    text = _norm_text(text)
    patterns = (
        r"\bpack of (\d{1,3})\b", r"\b(\d{1,3}) pack\b", r"\b(\d{1,3}) count\b",
        r"\b(\d{1,3}) ct\b", r"\bset of (\d{1,3})\b", r"\b(\d{1,3}) piece\b",
        r"\b(\d{1,3}) pc\b", r"\b(\d{1,3})pcs\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return int(match.group(1))
    return None


def _extract_size(text):
    text = _norm_text(text)
    match = re.search(
        r"\b(\d+(?:\.\d+)?)\s*(oz|ounce|ounces|lb|lbs|pound|pounds|g|gram|grams|kg|kilogram|kilograms|ml|milliliter|milliliters|l|liter|liters)\b",
        text,
    )
    if not match:
        return None
    amount, unit = float(match.group(1)), match.group(2)
    family = "volume" if unit in {"ml", "milliliter", "milliliters", "l", "liter", "liters"} else "weight"
    return family, round(amount * UNIT_MULTIPLIERS[unit], 4)


def _extract_condition(text):
    text = _norm_text(text)
    for condition in ("refurbished", "renewed", "used", "open box", "pre owned"):
        if condition in text:
            return condition
    return "new"


def _variant_conflicts(source_text, listing_text):
    conflicts = []
    source_pack, listing_pack = _extract_pack_count(source_text), _extract_pack_count(listing_text)
    if source_pack and listing_pack and source_pack != listing_pack:
        conflicts.append(f"pack count differs ({source_pack} vs {listing_pack})")
    source_size, listing_size = _extract_size(source_text), _extract_size(listing_text)
    if source_size and listing_size and source_size[0] == listing_size[0]:
        delta = abs(source_size[1] - listing_size[1]) / max(source_size[1], listing_size[1])
        if delta > 0.03:
            conflicts.append("size/weight differs")
    source_condition, listing_condition = _extract_condition(source_text), _extract_condition(listing_text)
    if source_condition != listing_condition:
        conflicts.append(f"condition differs ({source_condition} vs {listing_condition})")
    return conflicts


def _identity_values(result, source):
    values = []
    for label, value in (
        ("UPC/EAN", source.get("upc")),
        ("model", source.get("model") or result.get("modelNumber")),
        ("part number", result.get("partNumber")),
        ("ASIN", result.get("asin") or source.get("asin")),
    ):
        normalized = _normalized_identifier(value)
        if normalized:
            values.append((label, str(value), normalized))
    return values


def _title_tokens(value):
    stop = {"with", "from", "that", "this", "your", "for", "and", "the", "pack", "set", "new"}
    return [token for token in _norm_text(value).split() if len(token) >= 3 and token not in stop and not token.isdigit()]


def _match_details(result, source, listing_text, url):
    source_title = result.get("title") or source.get("name") or ""
    source_brand = result.get("brand") or source.get("brand") or ""
    source_text = " ".join(str(x or "") for x in [
        source_title, source_brand, source.get("model"), result.get("modelNumber"),
        result.get("partNumber"), source.get("upc"), result.get("asin"),
        source.get("condition"), source.get("pack_count"),
    ])
    hay = _norm_text(f"{listing_text} {url}")
    normalized_hay = _normalized_identifier(hay)

    matched_ids = []
    for label, _raw, normalized in _identity_values(result, source):
        if len(normalized) >= 5 and normalized in normalized_hay:
            matched_ids.append(label)

    brand = _norm_text(source_brand)
    brand_match = bool(brand and brand in hay)
    tokens = _title_tokens(source_title)
    hits = sum(1 for token in tokens[:16] if token in hay)
    coverage = hits / max(1, min(len(tokens), 16))

    model = _normalized_identifier(source.get("model") or result.get("modelNumber"))
    model_match = bool(model and len(model) >= 4 and model in normalized_hay)

    score = 0
    if "UPC/EAN" in matched_ids:
        score += 62
    if "model" in matched_ids or model_match:
        score += 48
    if "part number" in matched_ids:
        score += 48
    if "ASIN" in matched_ids:
        score += 60
    if brand_match:
        score += 14
    score += round(coverage * 42)
    score = min(score, 100)

    conflicts = _variant_conflicts(source_text, listing_text)
    if conflicts:
        score = min(score, 29)

    if matched_ids:
        reason = "Matched " + ", ".join(dict.fromkeys(matched_ids))
    elif model_match:
        reason = "Model number matches"
    elif brand_match and coverage >= 0.45:
        reason = "Brand and product-title terms match"
    elif coverage >= 0.45:
        reason = "Product-title terms match"
    elif coverage:
        reason = "Some product-title terms match"
    else:
        reason = "Search candidate needs manual review"

    if conflicts:
        reason += "; " + "; ".join(conflicts)

    label = (
        "Exact / high confidence" if score >= 80 else
        "Probable" if score >= 55 else
        "Possible" if score >= 30 else
        "Needs review"
    )
    return label, score, reason, conflicts


def _query_variants(result, source):
    upc = str(source.get("upc") or "").strip()
    model = str(source.get("model") or result.get("modelNumber") or "").strip()
    brand = str(source.get("brand") or result.get("brand") or "").strip()
    title = str(result.get("title") or source.get("name") or "").strip()
    asin = str(result.get("asin") or source.get("asin") or "").strip()

    queries = []
    if upc:
        queries.extend([f'"{upc}"', f'"{upc}" buy'])
    if model and brand:
        queries.extend([f'"{model}" "{brand}"', f'{brand} {model} price'])
    elif model:
        queries.extend([f'"{model}"', f'{model} price'])
    if asin:
        queries.append(f'"{asin}" -amazon')
    if title and brand:
        queries.append(f'{brand} "{title[:110]}"')
    if title:
        queries.append(f'"{title[:120]}"')
        queries.append(f'{title[:150]} buy')

    seen, clean = set(), []
    for query in queries:
        key = query.lower().strip()
        if key and key not in seen:
            seen.add(key)
            clean.append(query)
    return clean[:7]


def _collect_search_results(queries, timeout=5, limit=36):
    providers = (
        ("Google", _google_results),
        ("Bing", _bing_results),
        ("DuckDuckGo", _duckduckgo_results),
    )
    found, seen = [], set()
    provider_status = {}
    for query in queries:
        for name, provider in providers:
            try:
                rows = provider(query, timeout=timeout, limit=14)
                provider_status[name] = f"{len(rows)} results"
            except Exception as exc:
                provider_status[name] = f"unavailable: {type(exc).__name__}"
                rows = []
            for row in rows:
                url = row.get("url", "")
                key = url.split("#")[0].split("?")[0].rstrip("/")
                if not key or key in seen:
                    continue
                seen.add(key)
                row["query"] = query
                found.append(row)
                if len(found) >= limit:
                    return found, provider_status
        if len(found) >= limit:
            break
    return found, provider_status


def research_competitors(result, source, timeout=5, max_results=15):
    queries = _query_variants(result, source)
    if not queries:
        result["competitorResearch"] = {"queriesTried": [], "providers": {}, "message": "No usable search identifiers."}
        return []

    raw, providers = _collect_search_results(queries, timeout=timeout)
    found = []
    amazon_domain = _domain(result.get("url", ""))
    page_fetches = 0

    for item in raw:
        url = item.get("url", "")
        domain = item.get("domain") or _domain(url)
        if not domain:
            continue
        if amazon_domain and "amazon." in domain and "amazon." in amazon_domain:
            continue

        initial_text = " ".join([item.get("title", ""), item.get("snippet", ""), item.get("query", "")])
        pre_label, pre_score, _, _ = _match_details(result, source, initial_text, url)

        page = {}
        # Fetch a bounded number of likely product pages. Search-result data still
        # remains usable when a retailer blocks the page fetch.
        if page_fetches < 7 and (pre_score >= 18 or not PRICE_RE.search(initial_text)):
            page = _page_listing_data(url, timeout=min(timeout, 4.5))
            page_fetches += 1

        page_title = page.get("title") or item.get("title") or ""
        listing_text = " ".join([
            initial_text, page_title, page.get("text", ""),
            page.get("brand", ""), " ".join(page.get("categories") or []),
            " ".join((page.get("identifiers") or {}).values()),
        ])
        confidence, score, reason, conflicts = _match_details(result, source, listing_text, url)

        price = page.get("price")
        if price is None:
            snippet_prices = [_num(value) for value in PRICE_RE.findall(initial_text)]
            snippet_prices = [value for value in snippet_prices if value is not None]
            if snippet_prices:
                price = min(snippet_prices)

        found.append({
            "retailer": _store_name(domain),
            "domain": domain,
            "title": page_title,
            "url": page.get("finalUrl") or url,
            "price": price,
            "snippet": item.get("snippet", ""),
            "matchConfidence": confidence,
            "matchScore": score,
            "matchReason": reason,
            "variantConflicts": conflicts,
            "discoveredVia": item.get("provider", ""),
            "searchQuery": item.get("query", ""),
            "categorySignals": page.get("categories") or [],
        })

    # Keep strong matches first, but preserve review candidates rather than turning
    # a non-perfect search into a misleading "nothing found" result.
    found.sort(key=lambda row: (
        -int(row.get("matchScore") or 0),
        row.get("price") is None,
        row.get("price") or 10**12,
    ))
    found = found[:max_results]

    result["competitorResearch"] = {
        "queriesTried": queries,
        "providers": providers,
        "candidatesFound": len(raw),
        "listingsReturned": len(found),
        "message": "No public search candidates were returned." if not raw else "",
    }
    return found


def _amazon_category_path(result):
    return [str(value).strip() for value in (result.get("categories") or []) if str(value).strip()]


def _schema_category_signals(result):
    values = []
    for competitor in result.get("competitors") or []:
        for value in competitor.get("categorySignals") or []:
            value = str(value).strip()
            if value and value not in values:
                values.append(value)
    return values


def _taxonomy_score(text, keywords):
    score = 0.0
    normalized = f" {_norm_text(text)} "
    for keyword in keywords:
        k = _norm_text(keyword)
        if not k:
            continue
        if f" {k} " in normalized:
            score += 5 + min(len(k.split()), 3)
        elif k in normalized:
            score += 2
    return score


def _broad_from_path(path):
    joined = " ".join(path).lower()
    for alias, category in TOP_CATEGORY_ALIASES.items():
        if alias in joined:
            return category
    return ""


def _derived_subcategory(title):
    text = _norm_text(title)
    if not text:
        return "General Merchandise"
    stop = {
        "the", "and", "with", "for", "from", "your", "new", "pack", "set", "pcs",
        "piece", "pieces", "black", "white", "blue", "red", "green", "small", "medium",
        "large", "size", "inch", "inches", "compatible", "replacement",
    }
    tokens = [t for t in text.split() if len(t) >= 3 and t not in stop and not t.isdigit()]
    if not tokens:
        return "General Merchandise"
    phrase = " ".join(tokens[:4]).title()
    return phrase[:60]


def categorize_product(result, source=None):
    source = source or result.get("sourceInput") or {}
    explicit_category = str(source.get("category") or "").strip()
    explicit_subcategory = str(source.get("subcategory") or "").strip()
    amazon_path = _amazon_category_path(result)
    schema_signals = _schema_category_signals(result)

    if explicit_category:
        return {
            "category": explicit_category,
            "subcategory": explicit_subcategory or (amazon_path[-1] if amazon_path else _derived_subcategory(result.get("title") or source.get("name"))),
            "amazonPath": amazon_path,
            "source": "Imported catalog category",
            "confidence": 100,
        }

    text_parts = [
        " ".join(amazon_path),
        " ".join(schema_signals),
        result.get("title", ""),
        result.get("description", ""),
        result.get("brand", ""),
        source.get("name", ""),
        source.get("brand", ""),
        source.get("model", ""),
    ]
    details = result.get("details") or {}
    text_parts.extend(f"{k} {v}" for k, v in list(details.items())[:30])
    text = " ".join(str(value or "") for value in text_parts)

    best = None
    for category, subcategories in CATEGORY_TAXONOMY.items():
        for subcategory, keywords in subcategories.items():
            score = _taxonomy_score(text, keywords)
            # Category/path names themselves are strong signals.
            path_text = " ".join(amazon_path + schema_signals).lower()
            if category.lower() in path_text:
                score += 7
            if subcategory.lower() in path_text:
                score += 12
            if best is None or score > best[0]:
                best = (score, category, subcategory)

    if best and best[0] > 0:
        confidence = min(99, round(45 + best[0] * 4))
        return {
            "category": best[1],
            "subcategory": best[2],
            "amazonPath": amazon_path,
            "source": "Amazon/schema path + product data" if (amazon_path or schema_signals) else "Product data",
            "confidence": confidence,
        }

    # Preserve an Amazon/schema classification even when it is not represented in
    # ProductIQ's own taxonomy. This prevents legitimate niche items from becoming
    # uncategorized just because a keyword list did not anticipate them.
    all_paths = amazon_path or schema_signals
    if all_paths:
        broad = _broad_from_path(all_paths) or str(all_paths[0]).strip() or "General Merchandise"
        leaf = str(all_paths[-1]).strip() if len(all_paths) > 1 else _derived_subcategory(result.get("title") or source.get("name"))
        return {
            "category": broad,
            "subcategory": leaf or "General Merchandise",
            "amazonPath": amazon_path,
            "source": "Marketplace category path",
            "confidence": 72,
        }

    # Every remaining item still receives a usable catalog bucket.  The derived
    # product type stays visible so a niche item is not silently dumped into an
    # opaque "Other" row.
    title = result.get("title") or source.get("name") or ""
    broad = _broad_from_path([title]) or "General Merchandise"
    return {
        "category": broad,
        "subcategory": _derived_subcategory(title),
        "amazonPath": [],
        "source": "Product-type fallback",
        "confidence": 35,
    }


def _product_price(result):
    pricing = result.get("pricing") or {}
    return (
        _num(pricing.get("suggestedPrice"))
        or _num(result.get("price"))
        or _num((result.get("sourceInput") or {}).get("cost"))
    )


def _catalog_identity(result, index=0):
    source = result.get("sourceInput") or {}
    return str(
        result.get("asin") or source.get("asin") or source.get("sku")
        or source.get("upc") or source.get("model")
        or result.get("url") or f"catalog-{index}"
    )


def _available(candidate):
    source = candidate.get("sourceInput") or {}
    qty = _num(source.get("quantity"))
    if qty is not None and qty <= 0:
        return False
    availability = _norm_text(candidate.get("availability"))
    return not any(term in availability for term in ("out of stock", "unavailable", "currently unavailable"))


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
    if not _available(candidate):
        return -1, ""
    bc = base.get("catalogCategory") or {}
    cc = candidate.get("catalogCategory") or {}
    bcat, bsub = bc.get("category"), bc.get("subcategory")
    ccat, csub = cc.get("category"), cc.get("subcategory")
    score, reason = 0, "Related inventory item"

    if csub in COMPLEMENTARY.get(bsub, set()):
        score, reason = 82, f"Complements {bsub}"
    elif bcat and bcat == ccat and bsub and csub and bsub != csub:
        score, reason = 50, f"Related {bcat} item"
    else:
        base_tokens = set(_title_tokens(base.get("title") or (base.get("sourceInput") or {}).get("name")))
        cand_tokens = set(_title_tokens(candidate.get("title") or (candidate.get("sourceInput") or {}).get("name")))
        overlap = len(base_tokens & cand_tokens)
        if overlap:
            score = min(36, overlap * 9)
            reason = "Related product terms"

    brand_a = _norm_text(base.get("brand") or (base.get("sourceInput") or {}).get("brand"))
    brand_b = _norm_text(candidate.get("brand") or (candidate.get("sourceInput") or {}).get("brand"))
    if brand_a and brand_a == brand_b:
        score += 8
    return score, reason


def _upsell_score(base, candidate):
    if not _available(candidate):
        return -1, ""
    bc = base.get("catalogCategory") or {}
    cc = candidate.get("catalogCategory") or {}
    if not bc.get("subcategory") or bc.get("subcategory") != cc.get("subcategory"):
        return -1, ""
    base_price, candidate_price = _product_price(base), _product_price(candidate)
    if base_price is None or candidate_price is None or candidate_price <= base_price * 1.05:
        return -1, ""
    ratio = candidate_price / base_price if base_price else 99
    if ratio > 3.5:
        return -1, ""
    score = 55 + max(0, 24 - abs(ratio - 1.35) * 22)
    brand_a = _norm_text(base.get("brand") or (base.get("sourceInput") or {}).get("brand"))
    brand_b = _norm_text(candidate.get("brand") or (candidate.get("sourceInput") or {}).get("brand"))
    if brand_a and brand_a == brand_b:
        score += 15
    return score, f"Higher-value {bc.get('subcategory')} option"


def enrich_catalog(results, max_cross_sells=8, max_upsells=8):
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

        cross.sort(key=lambda row: (-row[0], -(_product_price(row[3]) or 0)))
        up.sort(key=lambda row: (-row[0], _product_price(row[3]) or 10**12))
        base["crossSells"] = [
            _recommendation_payload(candidate, index, reason)
            for _, index, reason, candidate in cross[:max_cross_sells]
        ]
        base["upsells"] = [
            _recommendation_payload(candidate, index, reason)
            for _, index, reason, candidate in up[:max_upsells]
        ]
    return results


def catalog_summary(results):
    categories, subcategories = Counter(), Counter()
    for result in results:
        category = result.get("catalogCategory") or {}
        if category.get("category"):
            categories[category["category"]] += 1
        if category.get("subcategory"):
            subcategories[category["subcategory"]] += 1

    prices = [_product_price(result) for result in results]
    prices = [value for value in prices if value is not None]
    costs = [_num((result.get("sourceInput") or {}).get("cost")) for result in results]
    costs = [value for value in costs if value is not None]
    quantities = [_num((result.get("sourceInput") or {}).get("quantity")) for result in results]
    quantities = [value for value in quantities if value is not None]
    margins = [
        result.get("pricing", {}).get("estimatedMargin")
        for result in results
        if isinstance(result.get("pricing", {}).get("estimatedMargin"), (int, float))
    ]
    return {
        "categories": dict(categories.most_common()),
        "subcategories": dict(subcategories.most_common()),
        "totalProducts": len(results),
        "totalUnits": int(sum(quantities)) if quantities else None,
        "estimatedCatalogRetailValue": round(sum(prices), 2) if prices else None,
        "knownCatalogCost": round(sum(costs), 2) if costs else None,
        "averageEstimatedMargin": round(statistics.mean(margins), 1) if margins else None,
        "productsWithCompetitors": sum(1 for result in results if result.get("competitors")),
        "productsNeedingReview": sum(1 for result in results if result.get("status") != "Complete"),
        "totalCrossSellSuggestions": sum(len(result.get("crossSells") or []) for result in results),
        "totalUpsellSuggestions": sum(len(result.get("upsells") or []) for result in results),
    }


def _pricing_from_competitors(result, source, competitors):
    amazon_price = _num(result.get("price"))
    comparable = [
        row["price"] for row in competitors
        if row.get("price") is not None and (row.get("matchScore") or 0) >= 30
    ]
    if amazon_price is not None:
        comparable.append(amazon_price)

    cost = _num(source.get("cost"))
    shipping_cost = _num(source.get("shipping_cost") or source.get("shippingCost")) or 0
    fixed_fees = _num(source.get("fees") or source.get("fixed_fees") or source.get("fixedFees")) or 0
    fee_rate = _num(source.get("fee_rate") or source.get("feeRate")) or 0

    avg = round(statistics.mean(comparable), 2) if comparable else None
    low = round(min(comparable), 2) if comparable else None
    high = round(max(comparable), 2) if comparable else None
    suggested = round(avg * 0.98, 2) if avg is not None else amazon_price

    break_even = round(cost + shipping_cost + fixed_fees, 2) if cost is not None else None
    if break_even is not None and 0 < fee_rate < 100:
        break_even = round(break_even / (1 - fee_rate / 100), 2)

    variable_fees = round((suggested or 0) * fee_rate / 100, 2) if suggested is not None else 0
    profit = (
        round(suggested - cost - shipping_cost - fixed_fees - variable_fees, 2)
        if suggested is not None and cost is not None else None
    )
    margin = round((profit / suggested) * 100, 1) if profit is not None and suggested else None

    return {
        "cost": cost,
        "marketLow": low,
        "marketAverage": avg,
        "marketHigh": high,
        "suggestedPrice": suggested,
        "competitivePrice": round(low * 0.99, 2) if low is not None else suggested,
        "premiumPrice": round(high * 1.05, 2) if high is not None else (round(suggested * 1.10, 2) if suggested else None),
        "estimatedProfit": profit,
        "estimatedMargin": margin,
        "breakEven": break_even,
        "shippingCost": shipping_cost,
        "fixedFees": fixed_fees,
        "feeRate": fee_rate,
        "comparableListings": len(comparable) - (1 if amazon_price is not None else 0),
    }


def add_intelligence(result, source, *, research_market=True):
    result.setdefault("sourceInput", source)
    if not result.get("title"):
        result["title"] = source.get("name") or "Inventory product"
    if not result.get("brand"):
        result["brand"] = source.get("brand") or ""
    if not result.get("asin"):
        result["asin"] = source.get("asin") or ""
    if not result.get("url"):
        result["url"] = source.get("url") or ""

    competitors = research_competitors(result, source) if research_market else (result.get("competitors") or [])
    result["competitors"] = competitors
    result["pricing"] = _pricing_from_competitors(result, source, competitors)
    result["catalogCategory"] = categorize_product(result, source)

    identifiers = {
        "asin": result.get("asin") or source.get("asin"),
        "sku": source.get("sku"),
        "upc": source.get("upc"),
        "model": source.get("model") or result.get("modelNumber"),
    }
    identifiers = {key: value for key, value in identifiers.items() if value}
    result["identification"] = {
        "status": (
            "Identifier-backed product" if any(identifiers.get(key) for key in ("asin", "upc", "model"))
            else "Name-based product"
        ),
        "identifiers": identifiers,
    }
    return result

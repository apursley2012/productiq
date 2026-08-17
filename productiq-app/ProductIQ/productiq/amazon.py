from __future__ import annotations

import base64
import json
import random
import re
import time
from html import unescape
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


class AmazonResearchError(RuntimeError):
    pass


class AmazonCaptchaRequired(AmazonResearchError):
    def __init__(self, message: str, challenge: dict[str, Any]):
        super().__init__(message)
        self.challenge = challenge


USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]
ASIN_RE = re.compile(r"(?<![A-Z0-9])([A-Z0-9]{10})(?![A-Z0-9])", re.I)
SEARCH_HEADERS = {
    "User-Agent": USER_AGENTS[0],
    "Accept-Language": "en-US,en;q=0.9",
}


def _text(node) -> str:
    return " ".join(node.get_text(" ", strip=True).split()) if node else ""


def _first_text(soup: BeautifulSoup, selectors: list[str]) -> str:
    for selector in selectors:
        value = _text(soup.select_one(selector))
        if value:
            return value
    return ""


def _clean_price(value: str) -> str:
    value = " ".join(str(value or "").split())
    match = re.search(r"(?:US\$|\$)\s?([0-9][0-9,]*(?:\.\d{2})?)", value)
    return f"${match.group(1)}" if match else value


def _extract_asin(value: str) -> str:
    match = ASIN_RE.search(value or "")
    return match.group(1).upper() if match else ""


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", str(value or "").lower())).strip()


def _browser_headers(user_agent: str | None = None) -> dict[str, str]:
    return {
        "User-Agent": user_agent or random.choice(USER_AGENTS),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Upgrade-Insecure-Requests": "1",
    }


def create_amazon_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(_browser_headers())
    return session


def _ensure_session(session: requests.Session | None) -> requests.Session:
    if session is None:
        return create_amazon_session()
    if not session.headers.get("User-Agent") or session.headers.get("User-Agent", "").startswith("python-requests"):
        session.headers.update(_browser_headers())
    return session


def _get(url: str, retries: int = 2, session: requests.Session | None = None) -> requests.Response:
    client = _ensure_session(session)
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = client.get(url, timeout=(10, 28), allow_redirects=True)
            if response.status_code == 200:
                return response
            last_error = AmazonResearchError(f"Amazon returned HTTP {response.status_code}.")
        except requests.RequestException as exc:
            last_error = exc
        if attempt < retries:
            time.sleep(1.4 + attempt * 1.3)
    raise AmazonResearchError(f"Could not retrieve the Amazon page: {last_error}")


def _is_blocked(soup: BeautifulSoup, html: str) -> bool:
    lowered = (html or "").lower()
    markers = (
        "enter the characters you see below",
        "sorry, we just need to make sure you're not a robot",
        "validatecaptcha",
        "robot check",
        "api-services-support@amazon.com",
    )
    return any(marker in lowered for marker in markers) or bool(
        soup.select_one("form[action*='validateCaptcha']")
    )


def _capture_image(session: requests.Session, image_url: str, page_url: str) -> tuple[str, str]:
    """Capture the challenge image immediately while the challenge is fresh.

    The previous implementation waited until the browser opened the modal and then
    asked Amazon for the image again. Amazon frequently invalidates or refuses that
    second fetch. Storing the bytes now keeps the exact image tied to this session.
    """
    if not image_url:
        return "", ""
    headers = {
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        "Referer": page_url,
        "Sec-Fetch-Dest": "image",
        "Sec-Fetch-Mode": "no-cors",
        "Sec-Fetch-Site": "same-origin",
    }
    try:
        response = session.get(
            image_url, headers=headers, timeout=(10, 20), allow_redirects=True
        )
        response.raise_for_status()
        content_type = (response.headers.get("Content-Type") or "image/jpeg").split(";", 1)[0].strip()
        if not response.content or not content_type.lower().startswith("image/"):
            return "", ""
        return base64.b64encode(response.content).decode("ascii"), content_type
    except Exception:
        return "", ""


def _captcha_challenge(
    soup: BeautifulSoup,
    page_url: str,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    form = soup.select_one("form[action*='validateCaptcha']")
    image = soup.select_one("form[action*='validateCaptcha'] img[src], img[src*='captcha']")
    fields: dict[str, str] = {}
    if form:
        for node in form.select("input[name]"):
            name = node.get("name")
            if name and name != "field-keywords":
                fields[name] = node.get("value", "")

    image_url = urljoin(page_url, image.get("src")) if image else ""
    image_data, image_mime = ("", "")
    if session is not None and image_url:
        image_data, image_mime = _capture_image(_ensure_session(session), image_url, page_url)

    return {
        "action": urljoin(page_url, form.get("action") if form else "/errors/validateCaptcha"),
        "method": (form.get("method") if form else "get").lower(),
        "imageUrl": image_url,
        "imageData": image_data,
        "imageMime": image_mime,
        "fields": fields,
        "pageUrl": page_url,
    }


def fetch_captcha_image(
    session: requests.Session,
    challenge: dict[str, Any],
) -> tuple[bytes, str]:
    stored = str(challenge.get("imageData") or "")
    if stored:
        return base64.b64decode(stored), str(challenge.get("imageMime") or "image/jpeg")

    image_url = str(challenge.get("imageUrl") or "").strip()
    if not image_url:
        raise AmazonResearchError("Amazon did not provide a CAPTCHA image URL.")

    page_url = str(challenge.get("pageUrl") or "https://www.amazon.com/")
    image_data, image_mime = _capture_image(_ensure_session(session), image_url, page_url)
    if not image_data:
        raise AmazonResearchError(
            "Amazon did not return the CAPTCHA image. Reload the verification page to request a fresh challenge."
        )
    challenge["imageData"] = image_data
    challenge["imageMime"] = image_mime
    return base64.b64decode(image_data), image_mime


def submit_captcha(
    session: requests.Session,
    challenge: dict[str, Any],
    answer: str,
) -> requests.Response:
    answer = (answer or "").strip()
    if not answer:
        raise AmazonResearchError("Enter the characters shown in the CAPTCHA image.")

    values = dict(challenge.get("fields") or {})
    values["field-keywords"] = answer
    action = challenge.get("action") or "https://www.amazon.com/errors/validateCaptcha"
    method = challenge.get("method", "get")
    client = _ensure_session(session)
    headers = {
        "Referer": str(challenge.get("pageUrl") or "https://www.amazon.com/"),
        "Origin": "https://www.amazon.com",
    }

    if method == "post":
        response = client.post(
            action, data=values, headers=headers, timeout=(10, 28), allow_redirects=True
        )
    else:
        response = client.get(
            action, params=values, headers=headers, timeout=(10, 28), allow_redirects=True
        )

    soup = BeautifulSoup(response.text, "lxml")
    if _is_blocked(soup, response.text):
        raise AmazonCaptchaRequired(
            "Amazon did not accept that answer. A fresh challenge is ready.",
            _captcha_challenge(soup, response.url, client),
        )
    return response


def _canonical_product_url(asin: str) -> str:
    return f"https://www.amazon.com/dp/{asin}"


def _search_terms(*, name: str = "", upc: str = "", model: str = "", brand: str = "") -> list[str]:
    terms = []
    if upc:
        terms.append(str(upc).strip())
    if model and brand:
        terms.append(f"{brand} {model}".strip())
    if model:
        terms.append(str(model).strip())
    if name and brand and brand.lower() not in name.lower():
        terms.append(f"{brand} {name}".strip())
    if name:
        terms.append(str(name).strip())

    seen, clean = set(), []
    for value in terms:
        key = value.lower()
        if value and key not in seen:
            seen.add(key)
            clean.append(value)
    return clean


def _candidate_score(
    candidate_title: str,
    *,
    name: str = "",
    upc: str = "",
    model: str = "",
    brand: str = "",
) -> int:
    hay = _norm(candidate_title)
    normalized = re.sub(r"[^a-z0-9]", "", hay)
    score = 0
    if upc and re.sub(r"[^a-z0-9]", "", upc.lower()) in normalized:
        score += 70
    if model and re.sub(r"[^a-z0-9]", "", model.lower()) in normalized:
        score += 55
    if brand and _norm(brand) in hay:
        score += 18

    source_tokens = [
        token for token in _norm(name).split()
        if len(token) >= 3 and token not in {"the", "and", "for", "with", "pack", "set"}
    ]
    if source_tokens:
        hits = sum(1 for token in source_tokens[:14] if token in hay)
        score += round((hits / min(len(source_tokens), 14)) * 42)
    return min(score, 100)


def _amazon_search_results(
    query: str,
    session: requests.Session,
) -> list[dict[str, str]]:
    response = _get(
        f"https://www.amazon.com/s?k={quote_plus(query)}",
        retries=1,
        session=session,
    )
    soup = BeautifulSoup(response.text, "lxml")
    if _is_blocked(soup, response.text):
        raise AmazonCaptchaRequired(
            "Amazon requires verification before product search can continue.",
            _captcha_challenge(soup, response.url, session),
        )

    results = []
    for node in soup.select("div[data-component-type='s-search-result'][data-asin]"):
        asin = (node.get("data-asin") or "").strip().upper()
        if not asin or not ASIN_RE.fullmatch(asin):
            continue
        link = node.select_one("h2 a[href], a.a-link-normal.s-no-outline[href]")
        title_node = node.select_one("h2 span, h2, .a-size-medium.a-color-base.a-text-normal")
        title = _text(title_node)
        if link:
            results.append({
                "asin": asin,
                "url": _canonical_product_url(asin),
                "title": title,
            })
    return results


def _external_amazon_candidates(query: str, timeout=6) -> list[dict[str, str]]:
    """Fallback discovery when Amazon search markup returns no usable cards."""
    candidates, seen = [], set()
    urls = [
        f"https://www.bing.com/search?q={quote_plus('site:amazon.com/dp ' + query)}",
        f"https://html.duckduckgo.com/html/?q={quote_plus('site:amazon.com/dp ' + query)}",
    ]
    for search_url in urls:
        try:
            response = requests.get(search_url, headers=SEARCH_HEADERS, timeout=timeout)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            anchors = soup.select("li.b_algo h2 a[href], .result__a[href]")
            for anchor in anchors:
                href = anchor.get("href", "")
                if "duckduckgo.com/l/" in href:
                    href = unquote(parse_qs(urlparse(href).query).get("uddg", [href])[0])
                asin = _extract_asin(href)
                if not asin:
                    asin = _extract_asin(anchor.get_text(" ", strip=True))
                if not asin or asin in seen:
                    continue
                seen.add(asin)
                candidates.append({
                    "asin": asin,
                    "url": _canonical_product_url(asin),
                    "title": anchor.get_text(" ", strip=True),
                })
        except Exception:
            continue
    return candidates


def _search_for_product(
    *,
    name: str = "",
    upc: str = "",
    model: str = "",
    brand: str = "",
    session: requests.Session | None = None,
) -> tuple[str, str]:
    client = _ensure_session(session)
    candidates: dict[str, dict[str, Any]] = {}

    terms = _search_terms(name=name, upc=upc, model=model, brand=brand)
    if not terms:
        raise AmazonResearchError(
            "No searchable product name, UPC/EAN, model number, ASIN, or Amazon URL was supplied."
        )

    for query in terms:
        try:
            rows = _amazon_search_results(query, client)
        except AmazonCaptchaRequired:
            raise
        except AmazonResearchError:
            rows = []
        for row in rows:
            score = _candidate_score(
                row.get("title", ""), name=name, upc=upc, model=model, brand=brand
            )
            current = candidates.get(row["asin"])
            if current is None or score > current["score"]:
                candidates[row["asin"]] = {**row, "score": score, "query": query}
        if candidates and max(row["score"] for row in candidates.values()) >= 70:
            break

    if not candidates:
        for query in terms[:3]:
            for row in _external_amazon_candidates(query):
                score = _candidate_score(
                    row.get("title", ""), name=name, upc=upc, model=model, brand=brand
                )
                current = candidates.get(row["asin"])
                if current is None or score > current["score"]:
                    candidates[row["asin"]] = {**row, "score": score, "query": query}

    if not candidates:
        raise AmazonResearchError(
            "Amazon search returned no usable listing candidates for the identifiers supplied."
        )

    best = sorted(
        candidates.values(),
        key=lambda row: (-row["score"], row["asin"]),
    )[0]
    return best["asin"], best["url"]


def _json_ld(soup: BeautifulSoup) -> dict[str, Any]:
    queue = []
    for script in soup.select("script[type='application/ld+json']"):
        try:
            queue.append(json.loads(script.string or script.get_text() or "null"))
        except Exception:
            continue
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
        if isinstance(item.get("@graph"), list):
            queue.extend(item["@graph"])
    return {}


def _image_urls(soup: BeautifulSoup, html: str, structured: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    image_data = structured.get("image")
    if isinstance(image_data, str):
        urls.append(image_data)
    elif isinstance(image_data, list):
        urls.extend(str(value) for value in image_data)

    for node in soup.select("#altImages img[src], #imageBlock img[src], #landingImage[src]"):
        src = node.get("data-old-hires") or node.get("src")
        if src:
            urls.append(src)

    for pattern in (
        r'"hiRes"\s*:\s*"(https:[^"]+)"',
        r'"large"\s*:\s*"(https:[^"]+)"',
    ):
        for match in re.finditer(pattern, html):
            urls.append(match.group(1).replace("\\u0026", "&").replace("\\/", "/"))

    clean = []
    for url in urls:
        url = unescape(url).replace("\\/", "/")
        if url.startswith("http") and url not in clean:
            clean.append(url)
    return clean[:12]


def _details(soup: BeautifulSoup) -> dict[str, str]:
    details: dict[str, str] = {}
    selectors = (
        "#productDetails_techSpec_section_1 tr",
        "#productDetails_detailBullets_sections1 tr",
        "#technicalSpecifications_section_1 tr",
        "table.prodDetTable tr",
    )
    for selector in selectors:
        for row in soup.select(selector):
            key = _text(row.select_one("th")) or _text(row.select_one("td.label"))
            cells = row.select("td")
            value = _text(cells[-1]) if cells else ""
            if key and value:
                details[key.strip(" ‎\n\t:")] = value

    for item in soup.select("#detailBullets_feature_div li"):
        bold = item.select_one("span.a-text-bold")
        if bold:
            key = _text(bold).strip(" ‎\n\t:")
            value = _text(item).replace(_text(bold), "", 1).strip(" ‎\n\t:")
            if key and value:
                details[key] = value
    return details


def _detail_value(details: dict[str, str], *needles: str) -> str:
    for key, value in details.items():
        lowered = key.lower()
        if any(needle in lowered for needle in needles):
            return value
    return ""


def _categories(soup: BeautifulSoup, structured: dict[str, Any]) -> list[str]:
    values = []
    schema_category = structured.get("category")
    if isinstance(schema_category, str) and schema_category.strip():
        values.extend(
            part.strip() for part in re.split(r"\s*[>/|]\s*", schema_category)
            if part.strip()
        )

    for node in soup.select(
        "#wayfinding-breadcrumbs_feature_div a, "
        "#wayfinding-breadcrumbs_container a, "
        "ul.a-unordered-list.a-horizontal.a-size-small a"
    ):
        value = _text(node)
        if value and value not in values:
            values.append(value)
    return values


def research_product(
    *,
    asin: str = "",
    url: str = "",
    name: str = "",
    upc: str = "",
    model: str = "",
    brand: str = "",
    session: requests.Session | None = None,
) -> dict[str, Any]:
    client = _ensure_session(session)
    asin = _extract_asin(asin) or _extract_asin(url)

    if not asin:
        asin, url = _search_for_product(
            name=name,
            upc=upc,
            model=model,
            brand=brand,
            session=client,
        )

    product_url = _canonical_product_url(asin)
    response = _get(product_url, session=client)
    soup = BeautifulSoup(response.text, "lxml")

    if _is_blocked(soup, response.text):
        raise AmazonCaptchaRequired(
            "Amazon requires human verification before this product can continue.",
            _captcha_challenge(soup, response.url, client),
        )

    structured = _json_ld(soup)
    title = (
        _first_text(soup, ["#productTitle", "h1#title", "h1.a-size-large"])
        or str(structured.get("name") or "")
    )
    if not title:
        raise AmazonResearchError(
            "Amazon loaded a page, but ProductIQ could not verify a product title on it."
        )

    bullets = []
    for node in soup.select("#feature-bullets li span.a-list-item"):
        value = _text(node)
        if value and value not in bullets and not value.lower().startswith("make sure this fits"):
            bullets.append(value)

    description = (
        _first_text(
            soup,
            [
                "#productDescription",
                "#aplus_feature_div",
                "#bookDescription_feature_div",
                "#productDescription_feature_div",
            ],
        )
        or str(structured.get("description") or "")
    )

    price = _first_text(
        soup,
        [
            "#corePrice_feature_div .a-price .a-offscreen",
            "#corePriceDisplay_desktop_feature_div .a-price .a-offscreen",
            "#priceblock_ourprice",
            "#priceblock_dealprice",
            "#price_inside_buybox",
            ".apexPriceToPay .a-offscreen",
        ],
    )
    offers = structured.get("offers")
    if not price and isinstance(offers, dict) and offers.get("price"):
        currency = offers.get("priceCurrency") or "$"
        price = f"{currency} {offers['price']}"
    price = _clean_price(price)

    rating = _first_text(
        soup, ["#acrPopover .a-icon-alt", "span[data-hook='rating-out-of-text']"]
    )
    review_count = _first_text(
        soup, ["#acrCustomerReviewText", "span[data-hook='total-review-count']"]
    )
    availability = _first_text(
        soup, ["#availability", "#outOfStock", "#availabilityInsideBuyBox_feature_div"]
    )
    byline = _first_text(soup, ["#bylineInfo"])
    brand = brand or byline.replace("Visit the ", "").replace(" Store", "").strip()
    if not brand:
        structured_brand = structured.get("brand")
        if isinstance(structured_brand, dict):
            brand = str(structured_brand.get("name") or "")
        elif structured_brand:
            brand = str(structured_brand)

    seller = _first_text(
        soup,
        [
            "#sellerProfileTriggerId",
            "#merchant-info",
            "#tabular-buybox-truncate-1 .a-truncate-full",
        ],
    )

    details = _details(soup)
    categories = _categories(soup, structured)
    images = _image_urls(soup, response.text, structured)

    return {
        "asin": asin,
        "url": response.url or product_url,
        "title": title,
        "brand": brand,
        "price": price,
        "availability": availability,
        "rating": rating,
        "reviewCount": review_count,
        "seller": seller,
        "bullets": bullets,
        "description": description,
        "categories": categories,
        "details": details,
        "dimensions": _detail_value(details, "product dimensions", "item dimensions"),
        "weight": _detail_value(details, "item weight", "product weight"),
        "manufacturer": _detail_value(details, "manufacturer"),
        "modelNumber": _detail_value(details, "item model number", "model number"),
        "partNumber": _detail_value(details, "part number"),
        "images": images,
    }

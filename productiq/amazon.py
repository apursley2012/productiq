from __future__ import annotations

import json
import os
import random
import re
import time
from html import unescape
from typing import Any
from urllib.parse import quote_plus, urljoin

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
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]
ASIN_RE = re.compile(r"(?<![A-Z0-9])([A-Z0-9]{10})(?![A-Z0-9])", re.I)


def _text(node) -> str:
    return " ".join(node.get_text(" ", strip=True).split()) if node else ""


def _first_text(soup: BeautifulSoup, selectors: list[str]) -> str:
    for selector in selectors:
        value = _text(soup.select_one(selector))
        if value:
            return value
    return ""


def _clean_price(value: str) -> str:
    value = " ".join(value.split())
    match = re.search(r"(?:US\$|\$)\s?([0-9][0-9,]*(?:\.\d{2})?)", value)
    return f"${match.group(1)}" if match else value


def _extract_asin(value: str) -> str:
    match = ASIN_RE.search(value or "")
    return match.group(1).upper() if match else ""


def _headers() -> dict[str, str]:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Upgrade-Insecure-Requests": "1",
    }


def _get(url: str, retries: int = 2, session: requests.Session | None = None) -> requests.Response:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            client = session or requests
            response = client.get(url, headers=_headers(), timeout=(12, 30), allow_redirects=True)
            if response.status_code == 200:
                # CAPTCHA pages can be much smaller than normal product pages. Return
                # them so the caller can preserve the session and request manual input.
                if len(response.text) > 5000 or "validateCaptcha" in response.text or "Robot Check" in response.text:
                    return response
            last_error = AmazonResearchError(f"Amazon returned HTTP {response.status_code}.")
        except requests.RequestException as exc:
            last_error = exc
        if attempt < retries:
            time.sleep(1.5 + attempt * 1.5)
    raise AmazonResearchError(f"Could not retrieve the Amazon page: {last_error}")


def _is_blocked(soup: BeautifulSoup, html: str) -> bool:
    lowered = html.lower()
    return any(marker in lowered for marker in [
        "enter the characters you see below", "sorry, we just need to make sure you're not a robot",
        "api-services-support@amazon.com", "validatecaptcha", "robot check"
    ]) or bool(soup.select_one("form[action*='validateCaptcha']"))



def _captcha_challenge(soup: BeautifulSoup, page_url: str) -> dict[str, Any]:
    form = soup.select_one("form[action*='validateCaptcha']")
    image = soup.select_one("form[action*='validateCaptcha'] img[src], img[src*='captcha']")
    fields: dict[str, str] = {}
    if form:
        for node in form.select("input[name]"):
            name = node.get("name")
            if name and name != "field-keywords":
                fields[name] = node.get("value", "")
    return {
        "action": urljoin(page_url, form.get("action") if form else "/errors/validateCaptcha"),
        "method": (form.get("method") if form else "get").lower(),
        "imageUrl": urljoin(page_url, image.get("src")) if image else "",
        "fields": fields,
        "pageUrl": page_url,
    }


def submit_captcha(session: requests.Session, challenge: dict[str, Any], answer: str) -> requests.Response:
    answer = (answer or "").strip()
    if not answer:
        raise AmazonResearchError("Enter the characters shown in the CAPTCHA image.")
    values = dict(challenge.get("fields") or {})
    values["field-keywords"] = answer
    action = challenge.get("action") or "https://www.amazon.com/errors/validateCaptcha"
    method = challenge.get("method", "get")
    if method == "post":
        response = session.post(action, data=values, headers=_headers(), timeout=(12, 30), allow_redirects=True)
    else:
        response = session.get(action, params=values, headers=_headers(), timeout=(12, 30), allow_redirects=True)
    soup = BeautifulSoup(response.text, "lxml")
    if _is_blocked(soup, response.text):
        raise AmazonCaptchaRequired(
            "Amazon did not accept that CAPTCHA answer. Try the new challenge.",
            _captcha_challenge(soup, response.url),
        )
    return response

def _canonical_product_url(asin: str) -> str:
    return f"https://www.amazon.com/dp/{asin}"


def _search_for_product(name: str, session: requests.Session | None = None) -> tuple[str, str]:
    response = _get(f"https://www.amazon.com/s?k={quote_plus(name)}", session=session)
    soup = BeautifulSoup(response.text, "lxml")
    if _is_blocked(soup, response.text):
        raise AmazonCaptchaRequired("Amazon requires a CAPTCHA before search can continue.", _captcha_challenge(soup, response.url))
    for result in soup.select("div[data-component-type='s-search-result'][data-asin]"):
        asin = (result.get("data-asin") or "").strip().upper()
        link = result.select_one("h2 a[href], a.a-link-normal.s-no-outline[href]")
        if asin and link:
            return asin, _canonical_product_url(asin)
    raise AmazonResearchError("No Amazon product result was found for that product name.")


def _json_ld(soup: BeautifulSoup) -> dict[str, Any]:
    for script in soup.select("script[type='application/ld+json']"):
        try:
            data = json.loads(script.string or script.get_text())
        except (json.JSONDecodeError, TypeError):
            continue
        objects = data if isinstance(data, list) else [data]
        for obj in objects:
            if isinstance(obj, dict) and obj.get("@type") in {"Product", ["Product"]}:
                return obj
            if isinstance(obj, dict) and isinstance(obj.get("@graph"), list):
                for item in obj["@graph"]:
                    if isinstance(item, dict) and item.get("@type") == "Product":
                        return item
    return {}


def _image_urls(soup: BeautifulSoup, html: str, structured: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    image_data = structured.get("image")
    if isinstance(image_data, str):
        urls.append(image_data)
    elif isinstance(image_data, list):
        urls.extend(str(v) for v in image_data)
    for node in soup.select("#altImages img[src], #imageBlock img[src], #landingImage[src]"):
        src = node.get("data-old-hires") or node.get("src")
        if src:
            urls.append(src)
    for match in re.finditer(r'"hiRes"\s*:\s*"(https:[^"]+)"', html):
        urls.append(match.group(1).replace("\\u0026", "&").replace("\\/", "/"))
    for match in re.finditer(r'"large"\s*:\s*"(https:[^"]+)"', html):
        urls.append(match.group(1).replace("\\u0026", "&").replace("\\/", "/"))
    cleaned: list[str] = []
    for url in urls:
        url = unescape(url).replace("\\/", "/")
        if url.startswith("http") and url not in cleaned:
            cleaned.append(url)
    return cleaned[:12]


def _details(soup: BeautifulSoup) -> dict[str, str]:
    details: dict[str, str] = {}
    selectors = [
        "#productDetails_techSpec_section_1 tr", "#productDetails_detailBullets_sections1 tr",
        "#technicalSpecifications_section_1 tr", "table.prodDetTable tr"
    ]
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
            full = _text(item)
            value = full.replace(_text(bold), "", 1).strip(" ‎\n\t:")
            if key and value:
                details[key] = value
    return details


def _detail_value(details: dict[str, str], *needles: str) -> str:
    for key, value in details.items():
        normalized = key.lower()
        if any(needle in normalized for needle in needles):
            return value
    return ""


def research_product(*, asin: str = "", url: str = "", name: str = "", session: requests.Session | None = None) -> dict[str, Any]:
    asin = _extract_asin(asin) or _extract_asin(url)
    if not asin:
        if not name:
            raise AmazonResearchError("An ASIN, Amazon URL, or product name is required.")
        asin, url = _search_for_product(name, session=session)
    product_url = _canonical_product_url(asin)
    response = _get(product_url, session=session)
    soup = BeautifulSoup(response.text, "lxml")
    if _is_blocked(soup, response.text):
        raise AmazonCaptchaRequired("Amazon requires a CAPTCHA before this product can continue.", _captcha_challenge(soup, response.url))

    structured = _json_ld(soup)
    title = _first_text(soup, ["#productTitle", "h1#title", "h1.a-size-large"]) or str(structured.get("name") or "")
    if not title:
        raise AmazonResearchError("The page loaded, but no product title was found. The listing may be unavailable or the page layout changed.")

    bullets = []
    for node in soup.select("#feature-bullets li span.a-list-item"):
        value = _text(node)
        if value and value not in bullets and not value.lower().startswith("make sure this fits"):
            bullets.append(value)

    description = _first_text(soup, [
        "#productDescription", "#aplus_feature_div", "#bookDescription_feature_div",
        "#productDescription_feature_div"
    ]) or str(structured.get("description") or "")

    price = _first_text(soup, [
        "#corePrice_feature_div .a-price .a-offscreen", "#corePriceDisplay_desktop_feature_div .a-price .a-offscreen",
        "#priceblock_ourprice", "#priceblock_dealprice", "#price_inside_buybox", ".apexPriceToPay .a-offscreen"
    ])
    if not price and isinstance(structured.get("offers"), dict):
        offer = structured["offers"]
        if offer.get("price"):
            price = f"{offer.get('priceCurrency', '$')} {offer['price']}"
    price = _clean_price(price)

    rating = _first_text(soup, ["#acrPopover .a-icon-alt", "span[data-hook='rating-out-of-text']"])
    review_count = _first_text(soup, ["#acrCustomerReviewText", "span[data-hook='total-review-count']"])
    availability = _first_text(soup, ["#availability", "#outOfStock", "#availabilityInsideBuyBox_feature_div"])
    brand = _first_text(soup, ["#bylineInfo", "#productOverview_feature_div tr:first-child td:last-child"])
    brand = re.sub(r"^(Visit the |Brand:\s*)", "", brand).replace(" Store", "").strip()
    seller = _first_text(soup, ["#sellerProfileTriggerId", "#merchant-info a", "#merchant-info"])
    categories = [_text(node) for node in soup.select("#wayfinding-breadcrumbs_feature_div li a") if _text(node)]
    details = _details(soup)
    images = _image_urls(soup, response.text, structured)

    return {
        "asin": asin,
        "url": product_url,
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
        "modelNumber": _detail_value(details, "item model number", "model number"),
        "partNumber": _detail_value(details, "part number"),
        "dimensions": _detail_value(details, "product dimensions", "package dimensions"),
        "weight": _detail_value(details, "item weight", "package weight"),
        "manufacturer": _detail_value(details, "manufacturer"),
        "images": images,
        "researchedAt": int(time.time()),
    }

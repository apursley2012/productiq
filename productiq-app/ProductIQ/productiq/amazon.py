from __future__ import annotations

import contextlib
import json
import os
import random
import re
import shutil
import socket
import subprocess
import tempfile
import time
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


class AmazonResearchError(RuntimeError):
    pass


class AmazonCaptchaRequired(AmazonResearchError):
    def __init__(self, message: str, challenge: dict[str, Any]):
        super().__init__(message)
        self.challenge = challenge


USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]
ASIN_RE = re.compile(r"(?<![A-Z0-9])([A-Z0-9]{10})(?![A-Z0-9])", re.I)
SEARCH_HEADERS = {
    "User-Agent": USER_AGENTS[0],
    "Accept-Language": "en-US,en;q=0.9",
}
_CHROMIUM_PATH: str | None = None


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


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _chromium_executable() -> str:
    global _CHROMIUM_PATH
    if _CHROMIUM_PATH and Path(_CHROMIUM_PATH).exists():
        return _CHROMIUM_PATH
    with sync_playwright() as pw:
        candidate = pw.chromium.executable_path
    if not candidate or not Path(candidate).exists():
        raise AmazonResearchError(
            "Chromium is not installed. Render must run `playwright install chromium` during the build."
        )
    _CHROMIUM_PATH = candidate
    return candidate


class BrowserAmazonSession:
    """Persistent Chromium process for one ProductIQ research job.

    The Chromium process lives independently of Flask request threads. Each request
    reconnects to it over Chrome DevTools Protocol, so the same Amazon cookies,
    storage, page, and CAPTCHA challenge survive between requests.
    """

    def __init__(self):
        self.port = _free_port()
        self.user_data_dir = tempfile.mkdtemp(prefix="productiq-amazon-")
        self.user_agent = random.choice(USER_AGENTS)
        self.process: subprocess.Popen | None = None
        self.created_at = time.time()
        self._launch()

    def _launch(self):
        executable = _chromium_executable()
        args = [
            executable,
            "--headless=new",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-background-networking",
            "--disable-default-apps",
            "--disable-extensions",
            "--disable-sync",
            "--metrics-recording-only",
            "--no-first-run",
            "--mute-audio",
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={self.user_data_dir}",
            "--window-size=1280,1000",
            "--lang=en-US",
            f"--user-agent={self.user_agent}",
            "about:blank",
        ]
        self.process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.time() + 18
        endpoint = f"http://127.0.0.1:{self.port}/json/version"
        last_error = None
        while time.time() < deadline:
            if self.process.poll() is not None:
                raise AmazonResearchError("Chromium exited before the Amazon browser session could start.")
            try:
                response = requests.get(endpoint, timeout=0.8)
                if response.ok:
                    return
            except Exception as exc:
                last_error = exc
            time.sleep(0.2)
        self.close()
        raise AmazonResearchError(f"Timed out starting Chromium for Amazon research: {last_error}")

    @contextlib.contextmanager
    def page(self):
        if not self.process or self.process.poll() is not None:
            raise AmazonResearchError("The Amazon browser session is no longer running.")
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{self.port}")
            try:
                contexts = browser.contexts
                context = contexts[0] if contexts else browser.new_context(user_agent=self.user_agent)
                pages = context.pages
                page = pages[0] if pages else context.new_page()
                page.set_default_timeout(18000)
                page.set_default_navigation_timeout(45000)
                yield page
            finally:
                # Do not call browser.close() here. This Chromium process is the
                # persistent Amazon session for the entire ProductIQ job. Leaving
                # the Playwright connection disconnects while Chromium keeps the
                # exact page/cookies/challenge alive for the next request.
                pass

    def close(self):
        if self.process and self.process.poll() is None:
            try:
                self.process.terminate()
                self.process.wait(timeout=3)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
        shutil.rmtree(self.user_data_dir, ignore_errors=True)


def create_amazon_session() -> BrowserAmazonSession:
    return BrowserAmazonSession()


def close_amazon_session(session: BrowserAmazonSession | None):
    if session is not None:
        session.close()


def _blocked_from_html(html: str) -> bool:
    lower = (html or "").lower()
    return any(marker in lower for marker in (
        "enter the characters you see below",
        "sorry, we just need to make sure you're not a robot",
        "validatecaptcha",
        "robot check",
        "api-services-support@amazon.com",
    ))


def _browser_challenge(page) -> dict[str, Any]:
    return {
        "browserSession": True,
        "pageUrl": page.url,
        "title": page.title(),
        "capturedAt": time.time(),
    }


def _ensure_not_blocked(page):
    html = page.content()
    if _blocked_from_html(html):
        raise AmazonCaptchaRequired(
            "Amazon requires human verification before product research can continue.",
            _browser_challenge(page),
        )
    return html


def _navigate(page, url: str):
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
    except PlaywrightTimeoutError:
        # A CAPTCHA page can finish enough to be interactive while long-lived
        # resources keep the navigation timer open.
        pass
    except Exception as exc:
        raise AmazonResearchError(f"Could not open Amazon in the browser session: {exc}")
    return _ensure_not_blocked(page)


def fetch_captcha_image(
    session: BrowserAmazonSession,
    challenge: dict[str, Any],
) -> tuple[bytes, str]:
    """Return a live screenshot of the exact Amazon page that is blocked.

    This is not a separately downloaded CAPTCHA image. It is the current viewport
    of the same Chromium page/session Amazon challenged.
    """
    with session.page() as page:
        if challenge.get("pageUrl") and page.url == "about:blank":
            try:
                page.goto(str(challenge["pageUrl"]), wait_until="domcontentloaded", timeout=45000)
            except Exception:
                pass
        try:
            image = page.screenshot(type="png", full_page=True)
        except Exception as exc:
            raise AmazonResearchError(f"Could not capture the live Amazon verification page: {exc}")
        if not image:
            raise AmazonResearchError("The live Amazon verification page returned an empty screenshot.")
        return image, "image/png"


def _captcha_input(page):
    selectors = [
        "input[name='field-keywords']",
        "input#captchacharacters",
        "input[name*='captcha' i]",
        "input[autocomplete='off'][type='text']",
        "form input[type='text']",
    ]
    for selector in selectors:
        locator = page.locator(selector)
        try:
            if locator.count() and locator.first.is_visible():
                return locator.first
        except Exception:
            continue
    return None


def _captcha_submit(page):
    selectors = [
        "button[type='submit']",
        "input[type='submit']",
        "form button",
        "button:has-text('Continue')",
        "button:has-text('Submit')",
    ]
    for selector in selectors:
        locator = page.locator(selector)
        try:
            if locator.count() and locator.first.is_visible():
                return locator.first
        except Exception:
            continue
    return None


def submit_captcha(
    session: BrowserAmazonSession,
    challenge: dict[str, Any],
    answer: str,
):
    """Type the answer into Amazon's actual blocked Chromium page and submit it."""
    answer = (answer or "").strip()
    if not answer:
        raise AmazonResearchError("Enter the characters shown on the Amazon verification page.")

    with session.page() as page:
        field = _captcha_input(page)
        if field is None:
            raise AmazonResearchError(
                "The live Amazon verification page does not currently have a CAPTCHA text field."
            )
        try:
            field.fill(answer)
        except Exception as exc:
            raise AmazonResearchError(f"Could not type into Amazon's CAPTCHA field: {exc}")

        submit = _captcha_submit(page)
        if submit is None:
            raise AmazonResearchError(
                "The live Amazon verification page does not currently have a submit button."
            )

        old_url = page.url
        try:
            submit.click()
            try:
                page.wait_for_load_state("domcontentloaded", timeout=30000)
            except PlaywrightTimeoutError:
                pass
            page.wait_for_timeout(900)
        except Exception as exc:
            raise AmazonResearchError(f"Could not submit Amazon's verification form: {exc}")

        html = page.content()
        if _blocked_from_html(html):
            raise AmazonCaptchaRequired(
                "Amazon did not accept that answer. The live verification page is still open.",
                _browser_challenge(page),
            )
        return {"accepted": True, "url": page.url, "previousUrl": old_url}


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


def _candidate_score(candidate_title: str, *, name="", upc="", model="", brand="") -> int:
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


def _canonical_product_url(asin: str) -> str:
    return f"https://www.amazon.com/dp/{asin}"


def _external_amazon_candidates(query: str, timeout=6) -> list[dict[str, str]]:
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
            for anchor in soup.select("li.b_algo h2 a[href], .result__a[href]"):
                href = anchor.get("href", "")
                if "duckduckgo.com/l/" in href:
                    href = unquote(parse_qs(urlparse(href).query).get("uddg", [href])[0])
                asin = _extract_asin(href) or _extract_asin(anchor.get_text(" ", strip=True))
                if asin and asin not in seen:
                    seen.add(asin)
                    candidates.append({
                        "asin": asin,
                        "url": _canonical_product_url(asin),
                        "title": anchor.get_text(" ", strip=True),
                    })
        except Exception:
            continue
    return candidates


def _search_for_product_browser(
    page,
    *,
    name: str = "",
    upc: str = "",
    model: str = "",
    brand: str = "",
) -> tuple[str, str]:
    candidates: dict[str, dict[str, Any]] = {}
    terms = _search_terms(name=name, upc=upc, model=model, brand=brand)
    if not terms:
        raise AmazonResearchError(
            "No searchable product name, UPC/EAN, model number, ASIN, or Amazon URL was supplied."
        )

    for query in terms:
        html = _navigate(page, f"https://www.amazon.com/s?k={quote_plus(query)}")
        soup = BeautifulSoup(html, "lxml")
        for node in soup.select("div[data-component-type='s-search-result'][data-asin]"):
            asin = (node.get("data-asin") or "").strip().upper()
            if not asin or not ASIN_RE.fullmatch(asin):
                continue
            title = _text(node.select_one("h2 span, h2, .a-size-medium.a-color-base.a-text-normal"))
            score = _candidate_score(title, name=name, upc=upc, model=model, brand=brand)
            current = candidates.get(asin)
            if current is None or score > current["score"]:
                candidates[asin] = {
                    "asin": asin,
                    "url": _canonical_product_url(asin),
                    "title": title,
                    "score": score,
                }
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
                    candidates[row["asin"]] = {**row, "score": score}

    if not candidates:
        raise AmazonResearchError(
            "Amazon search returned no usable listing candidates for the identifiers supplied."
        )

    best = sorted(candidates.values(), key=lambda row: (-row["score"], row["asin"]))[0]
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
    for pattern in (r'"hiRes"\s*:\s*"(https:[^"]+)"', r'"large"\s*:\s*"(https:[^"]+)"'):
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
    for selector in (
        "#productDetails_techSpec_section_1 tr",
        "#productDetails_detailBullets_sections1 tr",
        "#technicalSpecifications_section_1 tr",
        "table.prodDetTable tr",
    ):
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
        lower = key.lower()
        if any(needle in lower for needle in needles):
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
    session: BrowserAmazonSession | None = None,
) -> dict[str, Any]:
    if session is None:
        raise AmazonResearchError("ProductIQ did not receive an Amazon browser session.")

    asin = _extract_asin(asin) or _extract_asin(url)

    with session.page() as page:
        if not asin:
            asin, _ = _search_for_product_browser(
                page, name=name, upc=upc, model=model, brand=brand
            )

        product_url = _canonical_product_url(asin)
        html = _navigate(page, product_url)
        soup = BeautifulSoup(html, "lxml")
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

        rating = _first_text(soup, ["#acrPopover .a-icon-alt", "span[data-hook='rating-out-of-text']"])
        review_count = _first_text(soup, ["#acrCustomerReviewText", "span[data-hook='total-review-count']"])
        availability = _first_text(soup, ["#availability", "#outOfStock", "#availabilityInsideBuyBox_feature_div"])
        byline = _first_text(soup, ["#bylineInfo"])
        result_brand = brand or byline.replace("Visit the ", "").replace(" Store", "").strip()
        if not result_brand:
            structured_brand = structured.get("brand")
            if isinstance(structured_brand, dict):
                result_brand = str(structured_brand.get("name") or "")
            elif structured_brand:
                result_brand = str(structured_brand)

        seller = _first_text(
            soup,
            ["#sellerProfileTriggerId", "#merchant-info", "#tabular-buybox-truncate-1 .a-truncate-full"],
        )
        details = _details(soup)
        categories = _categories(soup, structured)
        images = _image_urls(soup, html, structured)

        return {
            "asin": asin,
            "url": page.url or product_url,
            "title": title,
            "brand": result_brand,
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

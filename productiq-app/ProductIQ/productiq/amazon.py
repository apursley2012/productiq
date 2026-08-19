from __future__ import annotations

import contextlib
import json
import os
import random
import queue
import threading
import re
import shutil
import socket
import subprocess
import tempfile
import time
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlparse, urljoin, urlencode

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

_TRACE_LOCAL = threading.local()


def _trace(page, event: str, detail: str = "", *, screenshot: bool = True):
    """Record what the Amazon browser is doing for the ProductIQ UI."""
    session = getattr(_TRACE_LOCAL, "session", None)
    if session is None:
        return
    try:
        url = page.url
    except Exception:
        url = ""
    title = ""
    try:
        title = page.title()
    except Exception:
        pass
    image = None
    if screenshot:
        try:
            image = page.screenshot(type="jpeg", quality=55, full_page=False)
        except Exception:
            image = None
    session._record_trace(event, detail, url=url, title=title, screenshot=image)


def _browser_challenge(page) -> dict[str, Any]:
    """Describe the exact live Amazon page that requires human verification."""
    _trace(page, "Verification required", "Amazon stopped the browser for human verification.")
    return {
        "browserSession": True,
        "pageUrl": page.url,
        "title": page.title(),
        "capturedAt": time.time(),
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
    """Own one Playwright browser/page on one dedicated worker thread.

    Playwright objects are thread-affine. Keeping Chromium, its browser context,
    cookies, and the Amazon page on this worker avoids reconnecting through CDP
    between Flask requests. Every ProductIQ request sends work to this same thread.
    """

    def __init__(self):
        self.user_agent = random.choice(USER_AGENTS)
        self.created_at = time.time()
        self._tasks: queue.Queue = queue.Queue()
        self._ready = threading.Event()
        self._startup_error: Exception | None = None
        self._closed = False
        self._trace_lock = threading.Lock()
        self._trace_events: list[dict[str, Any]] = []
        self._latest_screenshot: bytes | None = None
        self._latest_url = ""
        self._latest_title = ""
        self._thread = threading.Thread(
            target=self._run,
            name=f"productiq-amazon-{id(self)}",
            daemon=True,
        )
        self._thread.start()
        if not self._ready.wait(timeout=30):
            self._closed = True
            raise AmazonResearchError("Timed out starting the Amazon browser session.")
        if self._startup_error:
            self._closed = True
            raise AmazonResearchError(f"Could not start Chromium: {self._startup_error}")

    def _run(self):
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                        "--disable-background-networking",
                        "--disable-default-apps",
                        "--disable-extensions",
                        "--disable-sync",
                        "--disable-blink-features=AutomationControlled",
                        "--no-first-run",
                        "--mute-audio",
                    ],
                )
                context = browser.new_context(
                    user_agent=self.user_agent,
                    locale="en-US",
                    viewport={"width": 1280, "height": 1000},
                )
                context.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
                    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                """)
                page = context.new_page()
                page.set_default_timeout(18000)
                page.set_default_navigation_timeout(45000)
                _TRACE_LOCAL.session = self
                self._record_trace("Browser ready", "Chromium started and is ready for Amazon research.", url=page.url, title="")
                self._ready.set()

                while True:
                    task = self._tasks.get()
                    if task is None:
                        break
                    fn, args, kwargs, reply = task
                    try:
                        value = fn(page, *args, **kwargs)
                        reply.put(("ok", value))
                    except Exception as exc:
                        reply.put(("error", exc))

                try:
                    context.close()
                finally:
                    browser.close()
        except Exception as exc:
            self._startup_error = exc
            self._ready.set()

    def call(self, fn, *args, timeout=330, **kwargs):
        if self._closed:
            raise AmazonResearchError("The Amazon browser session is already closed.")
        if self._startup_error:
            raise AmazonResearchError(f"Amazon browser startup failed: {self._startup_error}")
        reply: queue.Queue = queue.Queue(maxsize=1)
        self._tasks.put((fn, args, kwargs, reply))
        try:
            status, value = reply.get(timeout=timeout)
        except queue.Empty:
            raise AmazonResearchError("The Amazon browser session timed out.")
        if status == "error":
            raise value
        return value

    def _record_trace(self, event: str, detail: str = "", *, url: str = "", title: str = "", screenshot: bytes | None = None):
        entry = {
            "time": time.time(),
            "event": str(event or ""),
            "detail": str(detail or ""),
            "url": str(url or ""),
            "title": str(title or ""),
        }
        with self._trace_lock:
            self._trace_events.append(entry)
            self._trace_events = self._trace_events[-60:]
            if screenshot:
                self._latest_screenshot = screenshot
            if url:
                self._latest_url = url
            if title:
                self._latest_title = title

    def debug_state(self) -> dict[str, Any]:
        with self._trace_lock:
            return {
                "events": list(self._trace_events),
                "url": self._latest_url,
                "title": self._latest_title,
                "hasScreenshot": bool(self._latest_screenshot),
                "closed": self._closed,
            }

    def latest_screenshot(self) -> bytes | None:
        with self._trace_lock:
            return self._latest_screenshot

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._tasks.put(None)
        self._thread.join(timeout=5)

def create_amazon_session() -> BrowserAmazonSession:
    return BrowserAmazonSession()


def close_amazon_session(session: BrowserAmazonSession | None):
    if session is not None:
        session.close()


def _blocked_from_html(html: str) -> bool:
    """Detect a real Amazon CAPTCHA page from strong CAPTCHA-specific markers."""
    lower = (html or "").lower()
    return any(marker in lower for marker in (
        "enter the characters you see below",
        "sorry, we just need to make sure you're not a robot",
        "validatecaptcha",
        "robot check",
    ))


def _visible_captcha_field(page) -> bool:
    selectors = [
        "input#captchacharacters",
        "input[name*='captcha' i]:not([type='hidden'])",
        "form[action*='validateCaptcha' i] input[type='text']",
        "form[action*='validateCaptcha' i] input:not([type='hidden'])[name='field-keywords']",
    ]
    for selector in selectors:
        try:
            locator = page.locator(selector)
            if locator.count() and locator.first.is_visible():
                return True
        except Exception:
            continue
    return False


def _continue_shopping_form(page) -> dict[str, Any] | None:
    """Read Amazon's no-input Continue shopping form and its hidden validation values."""
    try:
        html = page.content()
    except Exception:
        return None
    soup = BeautifulSoup(html, "lxml")
    phrase = soup.find(
        lambda tag: tag.name in {"h1", "h2", "h3", "h4", "p", "div", "span"}
        and "click the button below to continue shopping" in tag.get_text(" ", strip=True).lower()
    )
    button = soup.find(
        lambda tag: tag.name in {"button", "input", "a"}
        and "continue shopping" in (
            (tag.get_text(" ", strip=True) if hasattr(tag, "get_text") else "")
            + " " + str(tag.get("value") or "")
            + " " + str(tag.get("alt") or "")
        ).lower()
    )
    if not phrase and not button:
        return None

    form = button.find_parent("form") if button and getattr(button, "find_parent", None) else None
    if form is None:
        form = soup.find("form", action=re.compile("validateCaptcha", re.I))
    if form is None:
        return {"action": "", "method": "get", "fields": {}}

    fields: dict[str, str] = {}
    for node in form.find_all(["input", "button"]):
        name = str(node.get("name") or "").strip()
        if name:
            fields[name] = str(node.get("value") or "")

    return {
        "action": str(form.get("action") or ""),
        "method": str(form.get("method") or "get").lower(),
        "fields": fields,
    }


def _is_continue_shopping_page(page) -> bool:
    return _continue_shopping_form(page) is not None


def _direct_submit_continue_form(page, form_info: dict[str, Any]) -> bool:
    action = str(form_info.get("action") or "").strip()
    fields = dict(form_info.get("fields") or {})
    if not action:
        return False

    destination = urljoin(page.url, action)
    method = str(form_info.get("method") or "get").lower()
    _trace(page, "Amazon interstitial", f"Submitting Amazon continue form with {method.upper()} {destination}", screenshot=False)

    try:
        if method == "get":
            query = urlencode(fields, doseq=True)
            url = destination + (("&" if "?" in destination else "?") + query if query else "")
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
        else:
            # Submit the exact existing Amazon form in-page so cookies and hidden
            # challenge fields stay tied to this browser session.
            form = page.locator("form").filter(has=page.get_by_text("Continue shopping", exact=False)).first
            if form.count():
                form.evaluate("(f) => { if (f.requestSubmit) f.requestSubmit(); else f.submit(); }")
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=25000)
                except PlaywrightTimeoutError:
                    pass
            else:
                return False
        page.wait_for_timeout(900)
        return True
    except PlaywrightTimeoutError:
        return True
    except Exception as exc:
        _trace(page, "Interstitial form error", str(exc))
        return False


def _click_continue_control(page) -> bool:
    selectors = [
        "button:has-text('Continue shopping')",
        "a:has-text('Continue shopping')",
        "input[type='submit'][value*='Continue shopping' i]",
        "input[type='button'][value*='Continue shopping' i]",
        "button[alt*='Continue shopping' i]",
    ]
    for selector in selectors:
        try:
            locator = page.locator(selector)
            if not locator.count() or not locator.first.is_visible():
                continue
            _trace(page, "Amazon interstitial", "Clicking Continue shopping.")
            locator.first.click(force=True)
            try:
                page.wait_for_load_state("domcontentloaded", timeout=20000)
            except PlaywrightTimeoutError:
                pass
            page.wait_for_timeout(900)
            return True
        except Exception as exc:
            _trace(page, "Interstitial click error", str(exc))
    return False


def _clear_continue_shopping(page, target_url: str) -> bool:
    """Clear Amazon's Continue shopping challenge without treating it as a CAPTCHA."""
    if not _is_continue_shopping_page(page):
        return True

    # Attempt 1: normal browser click.
    _click_continue_control(page)
    if not _is_continue_shopping_page(page):
        _trace(page, "Amazon interstitial cleared", page.url)
        return True

    # Attempt 2: submit Amazon's exact hidden validation values directly.
    info = _continue_shopping_form(page) or {}
    _direct_submit_continue_form(page, info)
    if not _is_continue_shopping_page(page):
        _trace(page, "Amazon interstitial cleared", page.url)
        return True

    # Attempt 3: validation may have set a cookie even if Amazon redisplayed the
    # challenge. Re-open the page ProductIQ originally wanted.
    try:
        _trace(page, "Retrying target page", target_url, screenshot=False)
        page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
    except PlaywrightTimeoutError:
        pass
    except Exception as exc:
        _trace(page, "Target retry error", str(exc))
    page.wait_for_timeout(900)

    if not _is_continue_shopping_page(page):
        _trace(page, "Amazon interstitial cleared", page.url)
        return True

    # One last exact form submission using Amazon's refreshed token.
    info = _continue_shopping_form(page) or {}
    _direct_submit_continue_form(page, info)
    if not _is_continue_shopping_page(page):
        _trace(page, "Amazon interstitial cleared", page.url)
        return True

    _trace(
        page,
        "Amazon interstitial still active",
        "Amazon returned the Continue shopping anti-bot page again after click, form submission, and target retry.",
    )
    return False


def _ensure_not_blocked(page, target_url: str):
    if _is_continue_shopping_page(page):
        if not _clear_continue_shopping(page, target_url):
            raise AmazonResearchError(
                "Amazon kept returning its Continue shopping anti-bot page after ProductIQ clicked and submitted it. "
                "This is not a CAPTCHA, and ProductIQ did not pretend it extracted a product from that page."
            )

    html = page.content()
    if _visible_captcha_field(page) or _blocked_from_html(html):
        raise AmazonCaptchaRequired(
            "Amazon requires human verification before product research can continue.",
            _browser_challenge(page),
        )
    return html


def _navigate(page, url: str):
    _trace(page, "Opening page", url, screenshot=False)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
    except PlaywrightTimeoutError:
        pass
    except Exception as exc:
        _trace(page, "Navigation error", str(exc))
        raise AmazonResearchError(f"Could not open Amazon in the browser session: {exc}")

    _trace(page, "Page loaded", page.url)
    return _ensure_not_blocked(page, url)


def _verification_screenshot(page, challenge: dict[str, Any]) -> tuple[bytes, str]:
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


def fetch_captcha_image(
    session: BrowserAmazonSession,
    challenge: dict[str, Any],
) -> tuple[bytes, str]:
    return session.call(_verification_screenshot, challenge, timeout=90)


def _captcha_input(page):
    selectors = [
        "input#captchacharacters",
        "input[name*='captcha' i]:not([type='hidden'])",
        "form[action*='validateCaptcha' i] input[type='text']",
        "form[action*='validateCaptcha' i] input:not([type='hidden'])[name='field-keywords']",
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
        "form[action*='validateCaptcha' i] button[type='submit']",
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


def _submit_captcha_on_page(page, challenge: dict[str, Any], answer: str):
    answer = (answer or "").strip()
    if not answer:
        raise AmazonResearchError("Enter the characters shown on the Amazon verification page.")

    field = _captcha_input(page)
    if field is None:
        if _is_continue_shopping_page(page):
            raise AmazonResearchError(
                "Amazon is showing its Continue shopping page, not a CAPTCHA. Return to ProductIQ and retry the product."
            )
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
        submit.click(force=True)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=30000)
        except PlaywrightTimeoutError:
            pass
        page.wait_for_timeout(900)
    except Exception as exc:
        raise AmazonResearchError(f"Could not submit Amazon's verification form: {exc}")

    if _is_continue_shopping_page(page):
        _clear_continue_shopping(page, str(challenge.get("pageUrl") or old_url))

    html = page.content()
    if _visible_captcha_field(page) or _blocked_from_html(html):
        raise AmazonCaptchaRequired(
            "Amazon did not accept that answer. The live verification page is still open.",
            _browser_challenge(page),
        )
    return {"accepted": True, "url": page.url, "previousUrl": old_url}


def submit_captcha(
    session: BrowserAmazonSession,
    challenge: dict[str, Any],
    answer: str,
):
    return session.call(_submit_captcha_on_page, challenge, answer, timeout=90)



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
        _trace(page, "Searching Amazon", query, screenshot=False)
        html = _navigate(page, f"https://www.amazon.com/s?k={quote_plus(query)}")
        soup = BeautifulSoup(html, "lxml")
        query_count = 0
        for node in soup.select("div[data-component-type='s-search-result'][data-asin]"):
            asin = (node.get("data-asin") or "").strip().upper()
            if not asin or not ASIN_RE.fullmatch(asin):
                continue
            title = _text(node.select_one("h2 span, h2, .a-size-medium.a-color-base.a-text-normal"))
            score = _candidate_score(title, name=name, upc=upc, model=model, brand=brand)
            current = candidates.get(asin)
            query_count += 1
            if current is None or score > current["score"]:
                candidates[asin] = {
                    "asin": asin,
                    "url": _canonical_product_url(asin),
                    "title": title,
                    "score": score,
                }
        _trace(page, "Amazon search results", f"{query_count} listing cards found for: {query}")
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
    _trace(page, "Selected Amazon match", f"{best['asin']} | score {best['score']} | {best.get('title', '')}", screenshot=False)
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
                details[key.strip(" â\n\t:")] = value
    for item in soup.select("#detailBullets_feature_div li"):
        bold = item.select_one("span.a-text-bold")
        if bold:
            key = _text(bold).strip(" â\n\t:")
            value = _text(item).replace(_text(bold), "", 1).strip(" â\n\t:")
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


def _research_product_on_page(
    page,
    *,
    asin: str = "",
    url: str = "",
    name: str = "",
    upc: str = "",
    model: str = "",
    brand: str = "",
) -> dict[str, Any]:
    asin = _extract_asin(asin) or _extract_asin(url)
    if not asin:
        asin, _ = _search_for_product_browser(
            page, name=name, upc=upc, model=model, brand=brand
        )

    product_urls = [
        _canonical_product_url(asin),
        f"https://www.amazon.com/gp/product/{asin}?psc=1",
        f"https://www.amazon.com/gp/aw/d/{asin}",
    ]
    html = ""
    soup = None
    structured = {}
    title = ""
    product_url = product_urls[0]
    failures = []

    for candidate_url in product_urls:
        product_url = candidate_url
        _trace(page, "Opening product", f"{asin} | {candidate_url}", screenshot=False)
        try:
            candidate_html = _navigate(page, candidate_url)
        except AmazonCaptchaRequired:
            raise
        except AmazonResearchError as exc:
            failures.append(str(exc))
            _trace(page, "Product URL failed", str(exc))
            continue

        candidate_soup = BeautifulSoup(candidate_html, "lxml")
        candidate_structured = _json_ld(candidate_soup)
        candidate_title = (
            _first_text(candidate_soup, ["#productTitle", "h1#title", "h1.a-size-large"])
            or str(candidate_structured.get("name") or "")
        )

        if candidate_title:
            html = candidate_html
            soup = candidate_soup
            structured = candidate_structured
            title = candidate_title
            break

        failures.append(f"No product title found at {candidate_url}")
        _trace(page, "No product data on page", candidate_url)

    if not title or soup is None:
        detail = " | ".join(dict.fromkeys(failures))[-1400:]
        raise AmazonResearchError(
            "Amazon did not return an extractable product page for this ASIN."
            + (f" {detail}" if detail else "")
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

    _trace(
        page,
        "Product extracted",
        f"{title} | price={price or 'none'} | images={len(images)} | bullets={len(bullets)} | details={len(details)}",
    )

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
    return session.call(
        _research_product_on_page,
        asin=asin,
        url=url,
        name=name,
        upc=upc,
        model=model,
        brand=brand,
        timeout=300,
    )

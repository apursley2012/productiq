from __future__ import annotations

import csv
import io
import os
import time
import uuid
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request, send_file
from openpyxl import Workbook

from productiq.amazon import (
    AmazonCaptchaRequired,
    AmazonResearchError,
    create_amazon_session,
    close_amazon_session,
    fetch_captcha_image,
    research_product,
    submit_captcha,
)
from productiq.content import ARTICLES
from productiq.files import normalize_input_row, parse_upload
from productiq.intelligence import (
    add_intelligence,
    catalog_summary,
    enrich_catalog,
)


app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "productiq-development-key-change-me")
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

MAX_BATCH = max(1, int(os.getenv("PRODUCTIQ_MAX_BATCH", "25")))
REQUEST_DELAY = max(0.0, float(os.getenv("PRODUCTIQ_REQUEST_DELAY", "2.5")))
JOBS: dict[str, dict] = {}

PRODUCTIQ_BUILD = "2026-08-18-productiq-v8-live-browser-captcha"
PRODUCTIQ_FEATURES = [
    "ASIN, Amazon URL, product-name, UPC/EAN/GTIN, model, brand, and SKU-aware input",
    "Amazon product discovery that actually uses UPC/model/brand search identifiers",
    "same-session CAPTCHA challenge capture with a separate verification tab",
    "multi-query Google, Bing, and DuckDuckGo competitor discovery",
    "identifier, title, brand, variant, pack-count, size, and condition match scoring",
    "broad hierarchical categorization with marketplace-path and product-type fallbacks",
    "market low/average/high, break-even, fee, profit, margin, competitive, and premium pricing",
    "catalog-only cross-sells and upsells with known out-of-stock items excluded",
    "CSV/XLSX/XLS import and CSV/XLSX export",
    "Product Library, Competitor Research, Pricing, and Catalog Intelligence workspaces",
]


def _get_job(job_id: str) -> dict:
    job = JOBS.get(job_id)
    if not job:
        raise KeyError(job_id)
    return job


@app.after_request
def allow_embedding(response):
    response.headers.pop("X-Frame-Options", None)
    response.headers["Content-Security-Policy"] = (
        "frame-ancestors 'self' https://*.github.io https://github.com"
    )
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


def _load_sample_items() -> list[dict[str, str]]:
    sample_path = Path(app.root_path) / "sample-data" / "sample-products.csv"
    rows, _columns = parse_upload(sample_path.name, sample_path.read_bytes())
    items = [normalize_input_row(row) for row in rows]
    return [
        item for item in items
        if item.get("asin") or item.get("url") or item.get("name")
        or item.get("upc") or item.get("model")
    ][:MAX_BATCH]


def _base_result(item: dict, *, status="Needs review", error="") -> dict:
    result = {
        "status": status,
        "error": error,
        "asin": item.get("asin", ""),
        "url": item.get("url", ""),
        "title": item.get("name", "") or item.get("model", "") or item.get("upc", "") or "Inventory product",
        "brand": item.get("brand", ""),
        "price": "",
        "availability": "",
        "rating": "",
        "reviewCount": "",
        "seller": "",
        "bullets": [],
        "description": "",
        "categories": [],
        "details": {},
        "dimensions": "",
        "weight": "",
        "manufacturer": "",
        "modelNumber": item.get("model", ""),
        "partNumber": "",
        "images": [],
        "sourceInput": item,
    }
    try:
        result = add_intelligence(result, item, research_market=True)
    except Exception as exc:
        # Categorization should still be available even when public search providers
        # are temporarily inaccessible.
        result["intelligenceError"] = str(exc)
        try:
            result = add_intelligence(result, item, research_market=False)
        except Exception:
            pass
    return result


def _merge_amazon_result(amazon_result: dict, item: dict) -> dict:
    result = dict(amazon_result)
    result["sourceInput"] = item
    result["status"] = "Complete"
    result["error"] = ""
    try:
        return add_intelligence(result, item, research_market=True)
    except Exception as exc:
        result["intelligenceError"] = str(exc)
        return add_intelligence(result, item, research_market=False)


def _result_identity(result: dict) -> str:
    source = result.get("sourceInput") or {}
    return str(
        result.get("asin") or source.get("asin") or source.get("sku")
        or source.get("upc") or source.get("model")
        or source.get("url") or source.get("name") or result.get("title") or ""
    )


@app.get("/")
def index():
    try:
        sample_items = _load_sample_items()
    except (OSError, ValueError):
        sample_items = []
    return render_template(
        "index.html",
        max_batch=MAX_BATCH,
        sample_items=sample_items,
    )


@app.get("/case-study")
def case_study():
    return render_template("case_study.html", max_batch=MAX_BATCH)


@app.get("/articles")
def articles():
    return render_template("articles.html", articles=ARTICLES)


@app.get("/articles/<slug>")
def article(slug: str):
    article_data = ARTICLES.get(slug)
    if not article_data:
        return render_template("404.html"), 404
    return render_template("article.html", article=article_data, slug=slug)


@app.get("/library")
def library():
    return render_template("library.html")


@app.get("/market")
def market():
    return render_template("market.html")


@app.get("/catalog")
def catalog():
    return render_template("catalog.html")


@app.get("/pricing")
def pricing():
    return render_template("pricing.html")


@app.get("/health")
def health():
    return jsonify({
        "ok": True,
        "service": "ProductIQ",
        "build": PRODUCTIQ_BUILD,
        "maxBatch": MAX_BATCH,
    })


@app.get("/api/features")
def feature_manifest():
    return jsonify({
        "ok": True,
        "service": "ProductIQ",
        "build": PRODUCTIQ_BUILD,
        "features": PRODUCTIQ_FEATURES,
        "maxBatch": MAX_BATCH,
    })


@app.get("/api/catalog")
def get_catalog():
    return jsonify({"results": [], "storage": "browser-local"})


@app.get("/api/sample")
def load_sample_products():
    try:
        items = _load_sample_items()
    except (OSError, ValueError) as exc:
        return jsonify({"error": f"Could not load the included sample data: {exc}"}), 500
    return jsonify({"items": items, "count": len(items)})


@app.post("/api/import")
def import_products():
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"error": "Choose a CSV, XLSX, or XLS file."}), 400
    try:
        rows, columns = parse_upload(file.filename, file.read())
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"rows": rows[:500], "columns": columns, "count": len(rows)})


@app.post("/api/competitors/research")
def research_competitor_endpoint():
    payload = request.get_json(silent=True) or {}
    result = payload.get("result") or {}
    source = result.get("sourceInput") or payload.get("source") or {}
    if not result:
        return jsonify({"error": "A product result is required."}), 400

    try:
        updated = add_intelligence(dict(result), source, research_market=True)
        return jsonify({
            "competitors": updated.get("competitors") or [],
            "pricing": updated.get("pricing") or {},
            "catalogCategory": updated.get("catalogCategory") or {},
            "competitorResearch": updated.get("competitorResearch") or {},
        })
    except Exception as exc:
        return jsonify({"error": f"Competitor research failed: {exc}"}), 500


@app.post("/api/catalog/enrich")
def enrich_saved_catalog():
    payload = request.get_json(silent=True) or {}
    results = payload.get("results") or []
    if not isinstance(results, list):
        return jsonify({"error": "Catalog results must be a list."}), 400
    enriched = enrich_catalog(results)
    return jsonify({"results": enriched, "summary": catalog_summary(enriched)})


@app.post("/api/jobs")
def create_job():
    payload = request.get_json(silent=True) or {}
    raw_items = payload.get("items") or []
    if not isinstance(raw_items, list) or not raw_items:
        return jsonify({
            "error": "Add at least one ASIN, Amazon URL, product name, UPC/EAN, or model number."
        }), 400
    if len(raw_items) > MAX_BATCH:
        return jsonify({
            "error": f"The hosted version processes up to {MAX_BATCH} products per batch."
        }), 400

    items = [normalize_input_row(item) for item in raw_items]
    items = [
        item for item in items
        if item.get("asin") or item.get("url") or item.get("name")
        or item.get("upc") or item.get("model")
    ]
    if not items:
        return jsonify({"error": "No usable product identifiers were found."}), 400

    job_id = uuid.uuid4().hex
    JOBS[job_id] = {
        "id": job_id,
        "status": "ready",
        "items": items,
        "results": [],
        "nextIndex": 0,
        "createdAt": time.time(),
        "_httpSession": create_amazon_session(),
        "captcha": None,
        "pendingPartial": None,
    }
    return jsonify({"jobId": job_id, "count": len(items)})


@app.post("/api/jobs/<job_id>/next")
def process_next(job_id: str):
    try:
        job = _get_job(job_id)
    except KeyError:
        return jsonify({"error": "This job expired. Start the batch again."}), 404

    if job.get("status") == "captcha_required":
        return jsonify({
            "done": False,
            "captchaRequired": True,
            "processed": job["nextIndex"],
            "total": len(job["items"]),
            "message": "Amazon is still waiting for verification.",
            "verificationUrl": f"/verify/{job_id}",
            "partialResult": job.get("pendingPartial"),
        })

    index = job["nextIndex"]
    if index >= len(job["items"]):
        job["status"] = "complete"
        return jsonify({"done": True, "processed": index, "total": len(job["items"])})

    item = job["items"][index]
    job["status"] = "processing"
    started = time.time()

    try:
        amazon_result = research_product(
            asin=item.get("asin", ""),
            url=item.get("url", ""),
            name=item.get("name", ""),
            upc=item.get("upc", ""),
            model=item.get("model", ""),
            brand=item.get("brand", ""),
            session=job["_httpSession"],
        )
        result = _merge_amazon_result(amazon_result, item)

    except AmazonCaptchaRequired as exc:
        partial = job.get("pendingPartial")
        if not partial:
            partial = _base_result(
                item,
                status="Needs review",
                error="Amazon paused for human verification. Other catalog intelligence can still be reviewed.",
            )
        partial["processingSeconds"] = round(time.time() - started, 2)
        job["status"] = "captcha_required"
        job["captcha"] = exc.challenge
        job["pendingPartial"] = partial
        return jsonify({
            "done": False,
            "captchaRequired": True,
            "processed": job["nextIndex"],
            "total": len(job["items"]),
            "message": str(exc),
            "verificationUrl": f"/verify/{job_id}",
            "partialResult": partial,
        })

    except AmazonResearchError as exc:
        result = _base_result(item, status="Needs review", error=str(exc))

    except Exception as exc:
        result = _base_result(
            item,
            status="Error",
            error=f"Unexpected product research error: {exc}",
        )

    result["processingSeconds"] = round(time.time() - started, 2)
    job["pendingPartial"] = None
    job["results"].append(result)
    job["nextIndex"] += 1
    done = job["nextIndex"] >= len(job["items"])
    job["status"] = "complete" if done else "ready"

    if done:
        close_amazon_session(job.get("_httpSession"))
        job["_httpSession"] = None
    elif REQUEST_DELAY:
        time.sleep(REQUEST_DELAY)

    return jsonify({
        "done": done,
        "index": index,
        "processed": job["nextIndex"],
        "total": len(job["items"]),
        "result": result,
        "identity": _result_identity(result),
    })


@app.get("/api/jobs/<job_id>")
def get_job(job_id: str):
    try:
        job = _get_job(job_id)
    except KeyError:
        return jsonify({"error": "This job expired."}), 404

    safe = {
        "id": job["id"],
        "status": job["status"],
        "nextIndex": job["nextIndex"],
        "total": len(job["items"]),
        "createdAt": job["createdAt"],
    }
    if job.get("captcha"):
        challenge = job["captcha"]
        safe["captcha"] = {
            "pageUrl": challenge.get("pageUrl", ""),
            "hasCapturedImage": bool(challenge.get("imageData")),
        }
    return jsonify(safe)


@app.get("/verify/<job_id>")
def verify_amazon(job_id: str):
    try:
        job = _get_job(job_id)
    except KeyError:
        return render_template(
            "captcha_verify.html",
            job_id=job_id,
            expired=True,
            has_image=False,
        ), 404

    challenge = job.get("captcha") or {}
    return render_template(
        "captcha_verify.html",
        job_id=job_id,
        expired=False,
        has_image=bool(challenge.get("imageData") or challenge.get("imageUrl")),
        page_url=str(challenge.get("pageUrl") or ""),
    )


@app.get("/api/jobs/<job_id>/captcha-image")
def captcha_image(job_id: str):
    try:
        job = _get_job(job_id)
    except KeyError:
        return jsonify({"error": "This job expired."}), 404

    challenge = job.get("captcha") or {}
    try:
        image_bytes, content_type = fetch_captcha_image(
            job["_httpSession"], challenge
        )
    except AmazonResearchError as exc:
        return jsonify({"error": str(exc)}), 502

    return Response(
        image_bytes,
        content_type=content_type,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.post("/api/jobs/<job_id>/captcha")
def solve_captcha(job_id: str):
    try:
        job = _get_job(job_id)
    except KeyError:
        return jsonify({"error": "This job expired. Start the batch again."}), 404

    challenge = job.get("captcha")
    if not challenge:
        return jsonify({"error": "This job is not waiting for a CAPTCHA."}), 409

    answer = (request.get_json(silent=True) or {}).get("answer", "")
    try:
        submit_captcha(job["_httpSession"], challenge, answer)
    except AmazonCaptchaRequired as exc:
        job["captcha"] = exc.challenge
        job["status"] = "captcha_required"
        return jsonify({
            "accepted": False,
            "message": str(exc),
            "verificationUrl": f"/verify/{job_id}",
            "hasCapturedImage": bool(exc.challenge.get("imageData")),
        }), 400
    except AmazonResearchError as exc:
        return jsonify({"accepted": False, "message": str(exc)}), 400

    job["captcha"] = None
    job["status"] = "ready"
    return jsonify({
        "accepted": True,
        "message": "Amazon accepted the verification. Return to ProductIQ and the same product will continue.",
    })


CSV_HEADERS = [
    "Status", "ASIN", "Title", "Brand", "Price", "Availability", "Rating",
    "Review Count", "Seller", "Amazon URL", "Amazon Category", "Bullet Points",
    "Description", "Model Number", "Part Number", "Dimensions", "Weight",
    "Manufacturer", "Image 1", "Image 2", "Image 3", "Image 4", "Image 5",
    "SKU", "UPC/EAN", "Store Category", "Store Subcategory", "Category Confidence",
    "Input Cost", "Market Low", "Market Average", "Market High", "Suggested Price",
    "Competitive Price", "Premium Price", "Break Even", "Estimated Profit",
    "Estimated Margin %", "Competitors", "Cross-Sells", "Upsells", "Error",
]


def _export_row(result):
    images = result.get("images") or []
    pricing = result.get("pricing") or {}
    category = result.get("catalogCategory") or {}
    source = result.get("sourceInput") or {}
    return [
        result.get("status", ""), result.get("asin", ""), result.get("title", ""),
        result.get("brand", ""), result.get("price", ""), result.get("availability", ""),
        result.get("rating", ""), result.get("reviewCount", ""), result.get("seller", ""),
        result.get("url", ""), " > ".join(result.get("categories") or []),
        " | ".join(result.get("bullets") or []), result.get("description", ""),
        result.get("modelNumber", ""), result.get("partNumber", ""),
        result.get("dimensions", ""), result.get("weight", ""), result.get("manufacturer", ""),
        *(images + [""] * 5)[:5],
        source.get("sku", ""), source.get("upc", ""),
        category.get("category", ""), category.get("subcategory", ""),
        category.get("confidence", ""),
        pricing.get("cost", ""), pricing.get("marketLow", ""),
        pricing.get("marketAverage", ""), pricing.get("marketHigh", ""),
        pricing.get("suggestedPrice", ""), pricing.get("competitivePrice", ""),
        pricing.get("premiumPrice", ""), pricing.get("breakEven", ""),
        pricing.get("estimatedProfit", ""), pricing.get("estimatedMargin", ""),
        " | ".join(
            f"{row.get('retailer', '')}: "
            f"{'$' + str(row.get('price')) if row.get('price') is not None else 'price unavailable'} "
            f"[{row.get('matchScore', 0)}%] {row.get('url', '')}"
            for row in result.get("competitors", [])
        ),
        " | ".join(
            f"{row.get('title', '')} ({row.get('reason', '')})"
            for row in result.get("crossSells", [])
        ),
        " | ".join(
            f"{row.get('title', '')} ({row.get('reason', '')})"
            for row in result.get("upsells", [])
        ),
        result.get("error", ""),
    ]


@app.post("/api/export/csv")
def export_csv():
    results = (request.get_json(silent=True) or {}).get("results") or []
    if not results:
        return jsonify({"error": "There are no results to export."}), 400

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(CSV_HEADERS)
    for result in results:
        writer.writerow(_export_row(result))

    return send_file(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),
        mimetype="text/csv; charset=utf-8",
        as_attachment=True,
        download_name="productiq-research.csv",
    )


@app.post("/api/export/xlsx")
def export_xlsx():
    results = (request.get_json(silent=True) or {}).get("results") or []
    if not results:
        return jsonify({"error": "There are no results to export."}), 400

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "ProductIQ Results"
    sheet.append(CSV_HEADERS)
    for result in results:
        sheet.append(_export_row(result))
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions

    output = io.BytesIO()
    workbook.save(output)
    output.seek(0)
    return send_file(
        output,
        as_attachment=True,
        download_name="productiq-research.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.errorhandler(413)
def too_large(_error):
    return jsonify({"error": "That file is larger than the 16 MB upload limit."}), 413


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "7860")),
        debug=True,
    )

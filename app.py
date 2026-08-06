from __future__ import annotations

import io
import json
import os
import time
import uuid
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file, Response
from openpyxl import Workbook, load_workbook

import requests

from productiq.amazon import (
    AmazonCaptchaRequired,
    AmazonResearchError,
    create_amazon_session,
    fetch_captcha_image,
    research_product,
    submit_captcha,
)
from productiq.files import parse_upload, normalize_input_row

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "productiq-development-key-change-me")
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

MAX_BATCH = max(1, int(os.getenv("PRODUCTIQ_MAX_BATCH", "25")))
REQUEST_DELAY = max(0.0, float(os.getenv("PRODUCTIQ_REQUEST_DELAY", "2.5")))

# In-memory job storage is intentional for the free-hosted portfolio version.
# Results are also returned to the browser immediately and stored in localStorage.
JOBS: dict[str, dict] = {}


def _get_job(job_id: str) -> dict:
    job = JOBS.get(job_id)
    if not job:
        raise KeyError(job_id)
    return job


@app.after_request
def allow_portfolio_embedding(response):
    response.headers.pop("X-Frame-Options", None)
    response.headers["Content-Security-Policy"] = "frame-ancestors 'self' https://*.github.io https://github.com"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


@app.get("/")
def index():
    return render_template("index.html", max_batch=MAX_BATCH)


@app.get("/health")
def health():
    return jsonify({"ok": True, "service": "ProductIQ", "maxBatch": MAX_BATCH})


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


@app.post("/api/jobs")
def create_job():
    payload = request.get_json(silent=True) or {}
    raw_items = payload.get("items") or []
    if not isinstance(raw_items, list) or not raw_items:
        return jsonify({"error": "Add at least one ASIN, Amazon URL, or product name."}), 400
    if len(raw_items) > MAX_BATCH:
        return jsonify({"error": f"The free-hosted version processes up to {MAX_BATCH} products per batch."}), 400

    items = [normalize_input_row(item) for item in raw_items]
    items = [item for item in items if item.get("asin") or item.get("url") or item.get("name")]
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
    }
    return jsonify({"jobId": job_id, "count": len(items)})


@app.post("/api/jobs/<job_id>/next")
def process_next(job_id: str):
    try:
        job = _get_job(job_id)
    except KeyError:
        return jsonify({"error": "This job expired. Start the batch again."}), 404

    index = job["nextIndex"]
    if index >= len(job["items"]):
        job["status"] = "complete"
        return jsonify({"done": True, "job": job})

    item = job["items"][index]
    job["status"] = "processing"
    started = time.time()
    try:
        result = research_product(
            asin=item.get("asin", ""),
            url=item.get("url", ""),
            name=item.get("name", ""),
            session=job["_httpSession"],
        )
        result["status"] = "Complete"
        result["sourceInput"] = item
    except AmazonCaptchaRequired as exc:
        job["status"] = "captcha_required"
        job["captcha"] = exc.challenge
        return jsonify({
            "done": False,
            "captchaRequired": True,
            "processed": job["nextIndex"],
            "total": len(job["items"]),
            "message": str(exc),
            "captchaImage": f"/api/jobs/{job_id}/captcha-image?ts={int(time.time())}",
        })
    except AmazonResearchError as exc:
        result = {
            "status": "Needs review",
            "error": str(exc),
            "asin": item.get("asin", ""),
            "url": item.get("url", ""),
            "title": item.get("name", ""),
            "sourceInput": item,
        }
    except Exception as exc:  # Defensive per-row isolation
        result = {
            "status": "Error",
            "error": f"Unexpected extraction error: {exc}",
            "asin": item.get("asin", ""),
            "url": item.get("url", ""),
            "title": item.get("name", ""),
            "sourceInput": item,
        }

    result["processingSeconds"] = round(time.time() - started, 2)
    job["results"].append(result)
    job["nextIndex"] += 1
    done = job["nextIndex"] >= len(job["items"])
    job["status"] = "complete" if done else "ready"

    if not done and REQUEST_DELAY:
        time.sleep(REQUEST_DELAY)

    return jsonify({
        "done": done,
        "index": index,
        "processed": job["nextIndex"],
        "total": len(job["items"]),
        "result": result,
    })


@app.get("/api/jobs/<job_id>")
def get_job(job_id: str):
    try:
        job = _get_job(job_id)
        return jsonify({k: v for k, v in job.items() if not k.startswith("_")})
    except KeyError:
        return jsonify({"error": "This job expired."}), 404


@app.get("/api/jobs/<job_id>/captcha-image")
def captcha_image(job_id: str):
    try:
        job = _get_job(job_id)
    except KeyError:
        return jsonify({"error": "This job expired."}), 404
    challenge = job.get("captcha") or {}
    image_url = challenge.get("imageUrl")
    if not image_url:
        return jsonify({"error": "Amazon did not provide a CAPTCHA image."}), 404
    try:
        image_bytes, content_type = fetch_captcha_image(job["_httpSession"], challenge)
    except (requests.RequestException, AmazonResearchError) as exc:
        return jsonify({"error": f"Could not load the CAPTCHA image: {exc}"}), 502
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
        return jsonify({
            "accepted": False,
            "message": str(exc),
            "captchaImage": f"/api/jobs/{job_id}/captcha-image?ts={int(time.time())}",
        }), 400
    except AmazonResearchError as exc:
        return jsonify({"accepted": False, "message": str(exc)}), 400
    job["captcha"] = None
    job["status"] = "ready"
    return jsonify({"accepted": True, "message": "CAPTCHA accepted. Product research can continue."})


@app.post("/api/export/xlsx")
def export_xlsx():
    payload = request.get_json(silent=True) or {}
    results = payload.get("results") or []
    if not results:
        return jsonify({"error": "There are no results to export."}), 400

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "ProductIQ Results"
    headers = [
        "Status", "ASIN", "Title", "Brand", "Price", "Availability", "Rating",
        "Review Count", "Seller", "Amazon URL", "Category", "Bullet Points",
        "Description", "Model Number", "Part Number", "Dimensions", "Weight",
        "Manufacturer", "Image 1", "Image 2", "Image 3", "Image 4", "Image 5", "Error"
    ]
    sheet.append(headers)
    for result in results:
        images = result.get("images") or []
        sheet.append([
            result.get("status", ""), result.get("asin", ""), result.get("title", ""),
            result.get("brand", ""), result.get("price", ""), result.get("availability", ""),
            result.get("rating", ""), result.get("reviewCount", ""), result.get("seller", ""),
            result.get("url", ""), " > ".join(result.get("categories") or []),
            "\n".join(result.get("bullets") or []), result.get("description", ""),
            result.get("modelNumber", ""), result.get("partNumber", ""),
            result.get("dimensions", ""), result.get("weight", ""),
            result.get("manufacturer", ""), *(images + [""] * 5)[:5], result.get("error", "")
        ])
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    widths = {"A": 16, "B": 14, "C": 52, "D": 22, "E": 14, "F": 24, "G": 12, "H": 14,
              "I": 22, "J": 42, "K": 38, "L": 60, "M": 70, "N": 18, "O": 18, "P": 24,
              "Q": 18, "R": 22, "S": 42, "T": 42, "U": 42, "V": 42, "W": 42, "X": 50}
    for col, width in widths.items():
        sheet.column_dimensions[col].width = width
    output = io.BytesIO()
    workbook.save(output)
    output.seek(0)
    return send_file(output, as_attachment=True, download_name="productiq-amazon-research.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.errorhandler(413)
def too_large(_error):
    return jsonify({"error": "That file is larger than the 16 MB upload limit."}), 413


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "7860")), debug=True)

from __future__ import annotations

import io
import csv
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
from productiq.intelligence import add_intelligence, enrich_catalog, catalog_summary

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "productiq-development-key-change-me")
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

MAX_BATCH = max(1, int(os.getenv("PRODUCTIQ_MAX_BATCH", "25")))
REQUEST_DELAY = max(0.0, float(os.getenv("PRODUCTIQ_REQUEST_DELAY", "2.5")))

# In-memory job storage is intentional for the free-hosted version.
# Results are also returned to the browser immediately and stored in localStorage.
JOBS: dict[str, dict] = {}


def _get_job(job_id: str) -> dict:
    job = JOBS.get(job_id)
    if not job:
        raise KeyError(job_id)
    return job


@app.after_request
def allow_embedding(response):
    response.headers.pop("X-Frame-Options", None)
    response.headers["Content-Security-Policy"] = "frame-ancestors 'self' https://*.github.io https://github.com"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


ARTICLES = {
    "why-i-built-productiq": {
        "title": "Why I Made ProductIQ",
        "dek": "I made ProductIQ because I already had code that could research products on Amazon, but actually using all of those separate scripts was still more work than it needed to be.",
        "read_time": "12 min read",
        "sections": [
            ("Why I started making it", [
                "ProductIQ came from a pretty ordinary problem. I would have a list of products I needed information for, usually in a spreadsheet, and I would end up doing the same thing for every one of them. Open Amazon. Find the right listing. Make sure it is actually the right product and variation. Copy the title, price, description, bullet points, images, dimensions, seller information, ratings, or whatever else I needed. Put it back into the spreadsheet. Then do it again for the next product.",
                "Doing that for one or two products is not a big deal. Doing it for twenty, fifty, or a few hundred gets old fast. It is also exactly the kind of work that starts creating mistakes because the job is repetitive. A field gets pasted into the wrong row. A price comes from the wrong variation. An image URL gets missed. A product is researched twice while another one never gets touched. None of those problems are especially complicated. They are just the result of making a person repeat the same boring process too many times.",
                "I already had Python code that could pull a lot of this information from Amazon. That is what matters here. ProductIQ did not begin as a design where I hoped I could eventually figure out the useful part later. The useful part already existed. I had working scripts. What I did not have was a good way to use them." 
            ]),
            ("The code worked, but the process still sucked", [
                "My original scripts went through a lot of versions because I kept adding the things I actually needed. One version handled product descriptions better. Another dealt with images. Some worked from ASINs. Some searched by product name. I added spreadsheet processing, retries, checkpoints, and CAPTCHA handling as I ran into those problems in real use.",
                "That is normal while I am building something, but eventually I had a folder full of code that I understood and could run, while anyone else would have had to ask which file was the right one, where the spreadsheet needed to go, what the column names needed to be, what ChromeDriver path to change, and what to do when the browser stopped on a CAPTCHA. Even for me, I did not want to keep thinking about all of that every time I needed product information.",
                "The whole point of ProductIQ became taking the parts that already worked and putting an actual workflow around them. I wanted to open one application, give it the products I already had, let it research them, see what happened while it was working, and get usable results back out. I did not want to turn the scraper into a fake demo. I wanted to make the scraper easier to use." 
            ]),
            ("I wanted to use the product lists I already had", [
                "I do not always start with the same identifier. Sometimes I have an ASIN. Sometimes I copied the Amazon URL. Sometimes a supplier file only gives me a product name or model. Most of the time, if there are a lot of products, I already have a CSV or Excel file with at least one of those things in it.",
                "So I did not want ProductIQ to act like there was one perfect input format. Manual entry is there when I only have a few products. Spreadsheet upload is there when the list already exists. The column mapping lets the file tell ProductIQ where the useful identifiers are instead of making me rebuild the spreadsheet around the app.",
                "That sounds like a small design decision, but it changes whether the app actually saves time. If I have a spreadsheet with fifty products and the first thing ProductIQ makes me do is copy those fifty products into another form one at a time, then I have not really automated much of anything." 
            ]),
            ("I needed more than a title and price", [
                "The original research kept growing because the information I needed kept growing. A product title and price are useful, but they are not enough if I am trying to understand a listing or prepare the information for another system. I also want things like the brand, seller, availability, bullet points, description, ratings, review count, categories, images, dimensions, weight, model number, manufacturer, part number, and technical details when Amazon exposes them.",
                "ProductIQ tries to collect those fields from the actual listing. It does not make up a value just because a blank field looks bad on a results card. I would rather have a result that says a field was not available than a result that looks complete but cannot be trusted.",
                "That is also why the result status matters. Complete, needs review, and error are not just different colors. They tell me whether I can probably use the row as-is, whether I should look at it before exporting, or whether the listing needs another attempt." 
            ]),
            ("One bad product should not ruin the whole batch", [
                "This was one of the biggest practical changes from using a script directly. If I research twenty-five products and product fourteen fails, I do not want that to turn into twenty-five products I have to do again. ProductIQ treats the batch as individual pieces of work. A completed product stays completed. A failed product can be retried. A partial result can stay visible instead of disappearing because the next request had a problem.",
                "The current hosted version keeps the batch size at twenty-five. That is not because ProductIQ could never work with a larger list. It is because the free hosted version has limited resources and Amazon can start challenging a session if it gets too aggressive. I would rather make a smaller batch dependable than put an unlimited button on the page and pretend the outside system will cooperate forever.",
                "The queue also makes progress obvious. I can see what I asked the app to research, what it is working on, what finished, and what still needs attention. That is a lot better than staring at a console and trying to remember which row the script was on when something happened." 
            ]),
            ("I needed the CAPTCHA handling to work the way it did before", [
                "Amazon sometimes asks for human verification. My original code already handled that by detecting the CAPTCHA, stopping, letting me solve it, and continuing after I was done. It did not pretend there was some magic free CAPTCHA bypass, because there was not.",
                "When I moved the project into a web application, I wanted the same basic behavior. The research job should pause instead of throwing away the batch. The current Amazon session should be kept. The challenge should be shown to the user. After the answer is submitted, the app should continue from the product it was already working on.",
                "That part has been more annoying than the basic parsing because Amazon ties the challenge to the session that received it. It is not enough to grab an image URL and treat it like a random picture. Cookies, headers, the current page, and the challenge fields matter. That is exactly the kind of detail that is easy to miss when something works locally in a visible browser and then gets moved into a hosted app." 
            ]),
            ("What ProductIQ changed for me", [
                "I still think of the Amazon research as the main ProductIQ feature. The dashboard, queue, saved results, sample data, filters, retry controls, and exports all exist to make that research easier to use. They are not the reason the project exists by themselves.",
                "I have a much bigger version of ProductIQ in mind. I have planned competitor research, pricing tools, SEO and listing content, audience ideas, supplier comparisons, related-product discovery, and more platform-specific exports. I still want those things. I just do not want to pile them on top of a weak version of the original feature and call that progress.",
                "For me, the finished foundation is simple: I give ProductIQ products I need researched, it does as much of the repetitive Amazon work as it can, it tells me clearly when something went wrong, and it gives me the information back in a form I can actually use." 
            ])
        ]
    },
    "when-amazon-doesnt-cooperate": {
        "title": "Getting ProductIQ to Work With Amazon",
        "dek": "Getting information from Amazon was the main point of ProductIQ, but it was also the part that caused the most problems. Pages change, information is missing, and sometimes Amazon stops the process with a CAPTCHA.",
        "read_time": "13 min read",
        "sections": [
            ("Getting one product to work was not the hard part", [
                "The first time a scraper successfully pulls a title, price, and image from Amazon, it feels like the hard part is done. It is not. That proves the code can read one page in one condition. It does not prove it can handle the next listing, a different category, a different seller, a missing description, a variation page, or whatever Amazon decides to return tomorrow.",
                "That is one of the biggest things I learned while working on the original scripts and then ProductIQ. Web scraping is not just about finding the correct CSS selector. It is about deciding what to do when the selector is not there, when the same information moves somewhere else, or when the page that came back is not actually the product page you asked for." 
            ]),
            ("Amazon pages are inconsistent because the products are inconsistent", [
                "A laptop listing does not necessarily expose details in the same places as batteries, furniture, or a phone charger. Some listings have long descriptions. Some mostly rely on bullet points. Some have technical tables. Some have several tables. Some prices are obvious. Some depend on a selected offer or variation. Some listings have a manufacturer and model number. Others barely give anything beyond the title.",
                "Because of that, I stopped thinking about the extractor as one perfect set of selectors. ProductIQ checks several places for important fields and normalizes what it finds. If one location is empty, it can try another likely source. The goal is not to force every Amazon page into one imaginary template. The goal is to get the strongest result the page actually supports." 
            ]),
            ("Missing data and bad data are not the same thing", [
                "This matters more than it sounds. If Amazon does not show a product weight, an empty weight is honest. If the parser accidentally grabs the shipping weight, package dimensions, or some unrelated number and labels it as the product weight, that is worse than returning nothing.",
                "I would rather have ProductIQ mark a row as needing review than quietly fill the spreadsheet with values I cannot trust. That is why the app keeps the original input, the product URL it actually reached, the status, and any error or review message alongside the extracted fields. I need to be able to tell where the information came from and which rows deserve another look." 
            ]),
            ("A batch should not fall apart because one listing is weird", [
                "When I was working with the scripts directly, this was one of the easiest ways to waste time. A long run could get interrupted after a bunch of products already finished, and then I had to figure out what had been saved, what had not, and where to restart.",
                "ProductIQ saves results as products complete and keeps the queue separate from the results. If one listing fails, it can be marked as an error without erasing everything that came before it. If a product comes back incomplete, I can requeue that product instead of starting the entire batch again.",
                "That is what I mean when I say I care more about recovery than pretending nothing ever fails. Amazon is outside of my control. I cannot guarantee that every request will return a perfect page. I can make sure one bad response does not make the rest of the application useless." 
            ]),
            ("CAPTCHA handling is a good example of that", [
                "A CAPTCHA is not really a parsing error. Amazon is deliberately asking for a person. My original scripts recognized that and waited instead of treating the challenge page like a product listing. That same idea needed to carry into ProductIQ.",
                "The tricky part is that the challenge belongs to the session that hit it. If the app requests the CAPTCHA image with a different browser identity or loses the cookies, Amazon can reject the image or the answer even though the user did everything right. The hosted version therefore has to keep the session information together instead of fetching pieces of the challenge as unrelated requests.",
                "I am not trying to bypass Amazon's verification. I am trying to make the application behave reasonably when verification happens: pause, show the challenge, accept the user's answer, continue if Amazon accepts it, and keep the work that was already finished." 
            ]),
            ("Retries need limits too", [
                "It is tempting to make a scraper retry forever because that sounds more reliable. In practice, repeatedly hitting the same blocked page is usually the opposite. It wastes time, increases the chance of more blocking, and makes it harder to tell the difference between a temporary issue and a listing that really cannot be processed.",
                "ProductIQ uses deliberate delays and lets the user decide when incomplete products should be requeued. That gives me more control than an endless automatic loop. The application can be persistent without being reckless." 
            ]),
            ("The errors needed to actually tell me what happened", [
                "A Python traceback is useful while I am developing. It is not useful to someone trying to research products. In ProductIQ I want errors to answer a more practical question: what happened to this product and what can I do next? Was the listing unavailable? Did Amazon return a verification page? Did the product search fail to find a confident match? Did the page load but leave important fields missing?",
                "That is why I have been moving more of the raw scraper behavior into clear statuses and messages. The technical detail is still there when I need to debug it, but the main screen should tell me whether the product is complete, needs review, or needs another attempt." 
            ]),
            ("What I changed because of those problems", [
                "The more useful lesson was that an application built around an unreliable outside source has to be designed for that reality from the beginning. I cannot make Amazon promise to keep the same HTML, return every field, or never show a CAPTCHA. I can decide how much work ProductIQ loses when any of those things happen.",
                "That changed what I consider a successful result. Success is not every field being filled every single time. Success is getting the real information that is available, being honest about what is missing, preserving what already worked, and making the next step obvious when something did not." 
            ])
        ]
    },
    "spreadsheet-first": {
        "title": "Using CSV and Excel Files With ProductIQ",
        "dek": "Most of the time I already have the products I need to research in a spreadsheet, so ProductIQ needed to be able to use those files instead of making me enter everything again.",
        "read_time": "11 min read",
        "sections": [
            ("Most of my product lists are already in a spreadsheet", [
                "When I need to research more than a couple of products, I usually already have a file. It might be inventory. It might be a supplier list. It might be a spreadsheet I made myself. The columns are not always the same, but there is normally something useful in there: an ASIN, an Amazon URL, a product name, a model number, a SKU, or some combination of them.",
                "So one of my first requirements for ProductIQ was that I should not have to rebuild that list inside the app. Uploading the spreadsheet is not an extra feature to me. It is the normal starting point for bulk research." 
            ]),
            ("The file should not have to use one exact format", [
                "Requiring one exact file layout would make the upload technically easy and practically irritating. Real files do not all call a column the same thing. One might say ASIN. Another might say Amazon ASIN. A URL might be Product URL, Amazon URL, Web Page URL, or just Link. Product name fields are even less consistent.",
                "ProductIQ reads the available headings and suggests the columns that look relevant. The user can confirm or change the mapping before anything goes into the queue. That keeps the import flexible without making the app guess silently." 
            ]),
            ("ProductIQ only needs enough information to find the product", [
                "The upload does not need to already contain all of the data ProductIQ is supposed to research. That would defeat the purpose. If the file has an ASIN or a usable Amazon URL, that may be enough. If it only has a product name, ProductIQ can attempt to search for the listing.",
                "The research result then becomes the richer record. The original identifier stays with it so I can trace the result back to the row I started with." 
            ]),
            ("I still wanted a way to paste in a few products", [
                "Spreadsheet-first does not mean spreadsheet-only. If I have three ASINs copied from somewhere, making a CSV just so I can upload it would be ridiculous. That is why the dashboard also accepts one ASIN, URL, or product name per line.",
                "The two input methods solve different versions of the same problem. Paste a few products when the list is small. Upload the file when the list already exists. Both end up in the same research queue." 
            ]),
            ("The sample products should work from the dashboard", [
                "I originally included a sample spreadsheet in the repository, which is useful for someone looking through the source. It was not useful enough inside the app. If someone opens ProductIQ and just wants to see how the queue works, sending them to GitHub to download a CSV and then telling them to upload that same CSV back into the application is pointless extra work.",
                "That is why the dashboard has a Try Sample Products option. The sample rows are the same rows included in the CSV and XLSX files, but the button loads them directly into the queue. It is there so the workflow can be tested immediately without preparing a file first." 
            ]),
            ("I also needed to be able to get the results back out", [
                "I do not want ProductIQ to become another place where product data gets trapped. The information is useful because I can move it into whatever I am doing next. Sometimes that means Excel because I want to review and edit the workbook. Sometimes CSV is better because another platform can import it directly.",
                "Keeping both formats gives me a simple handoff. ProductIQ does the research and organization. It does not insist that every other part of the workflow has to happen inside ProductIQ too." 
            ]),
            ("A login was not the important part of this version", [
                "The current version saves completed research in the browser so I can come back to it on the same device and export it when I am ready. A full account and database system could make sense later, especially if I want research synchronized across devices, but it is not required to prove the main workflow.",
                "For this version I would rather spend the complexity on the thing ProductIQ is actually supposed to do: take the products I already have and reduce the amount of Amazon research I have to do by hand." 
            ]),
            ("Why the spreadsheet upload matters", [
                "This ended up being one of the design decisions I feel strongest about. It would have been easy to build a nice-looking product entry form and call bulk upload an enhancement for later. That would also make the app much less useful for the exact situation that made me build it.",
                "The whole point is not to give me another place to type product information. It is to take the information I already have, research what I do not have, and give the combined result back to me in a cleaner form." 
            ])
        ]
    }
}

def _load_sample_items() -> list[dict[str, str]]:
    sample_path = Path(app.root_path) / "sample-data" / "sample-products.csv"
    rows, _columns = parse_upload(sample_path.name, sample_path.read_bytes())
    items = [normalize_input_row(row) for row in rows]
    return [item for item in items if item.get("asin") or item.get("url") or item.get("name") or item.get("upc") or item.get("model")]


@app.get("/")
def index():
    try:
        sample_items = _load_sample_items()
    except (OSError, ValueError):
        sample_items = []
    return render_template("index.html", max_batch=MAX_BATCH, sample_items=sample_items)


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


@app.get("/health")
def health():
    return jsonify({"ok": True, "service": "ProductIQ", "maxBatch": MAX_BATCH})


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


@app.post("/api/jobs")
def create_job():
    payload = request.get_json(silent=True) or {}
    raw_items = payload.get("items") or []
    if not isinstance(raw_items, list) or not raw_items:
        return jsonify({"error": "Add at least one ASIN, Amazon URL, or product name."}), 400
    if len(raw_items) > MAX_BATCH:
        return jsonify({"error": f"The free-hosted version processes up to {MAX_BATCH} products per batch."}), 400

    items = [normalize_input_row(item) for item in raw_items]
    items = [item for item in items if item.get("asin") or item.get("url") or item.get("name") or item.get("upc") or item.get("model")]
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
        result = add_intelligence(result, item)
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


@app.post("/api/catalog/enrich")
def enrich_saved_catalog():
    payload = request.get_json(silent=True) or {}
    results = payload.get("results") or []
    if not isinstance(results, list):
        return jsonify({"error": "Catalog results must be a list."}), 400
    enriched = enrich_catalog(results)
    return jsonify({"results": enriched, "summary": catalog_summary(enriched)})


@app.post("/api/export/csv")
def export_csv():
    payload = request.get_json(silent=True) or {}
    results = payload.get("results") or []
    if not results:
        return jsonify({"error": "There are no results to export."}), 400

    output = io.StringIO()
    headers = [
        "Status", "ASIN", "Title", "Brand", "Price", "Availability", "Rating",
        "Review Count", "Seller", "Amazon URL", "Category", "Bullet Points",
        "Description", "Model Number", "Part Number", "Dimensions", "Weight",
        "Manufacturer", "Image 1", "Image 2", "Image 3", "Image 4", "Image 5", "SKU", "UPC", "Store Category", "Store Subcategory", "Input Cost", "Market Low", "Market Average", "Market High", "Suggested Price", "Estimated Profit", "Estimated Margin %", "Competitors", "Cross-Sells", "Upsells", "Error"
    ]
    writer = csv.writer(output)
    writer.writerow(headers)
    for result in results:
        images = result.get("images") or []
        writer.writerow([
            result.get("status", ""), result.get("asin", ""), result.get("title", ""),
            result.get("brand", ""), result.get("price", ""), result.get("availability", ""),
            result.get("rating", ""), result.get("reviewCount", ""), result.get("seller", ""),
            result.get("url", ""), " > ".join(result.get("categories") or []),
            " | ".join(result.get("bullets") or []), result.get("description", ""),
            result.get("modelNumber", ""), result.get("partNumber", ""),
            result.get("dimensions", ""), result.get("weight", ""),
            result.get("manufacturer", ""), *(images + [""] * 5)[:5],
            (result.get("sourceInput") or {}).get("sku", ""), (result.get("sourceInput") or {}).get("upc", ""),
            (result.get("catalogCategory") or {}).get("category", ""), (result.get("catalogCategory") or {}).get("subcategory", ""),
            (result.get("pricing") or {}).get("cost", ""), (result.get("pricing") or {}).get("marketLow", ""),
            (result.get("pricing") or {}).get("marketAverage", ""), (result.get("pricing") or {}).get("marketHigh", ""),
            (result.get("pricing") or {}).get("suggestedPrice", ""), (result.get("pricing") or {}).get("estimatedProfit", ""),
            (result.get("pricing") or {}).get("estimatedMargin", ""),
            " | ".join(f"{c.get('retailer','')}: ${c.get('price')} {c.get('url','')}" for c in result.get("competitors", []) if c.get("url")),
            " | ".join(f"{x.get('title','')} ({x.get('reason','')})" for x in result.get("crossSells", [])),
            " | ".join(f"{x.get('title','')} ({x.get('reason','')})" for x in result.get("upsells", [])), result.get("error", "")
        ])
    data = output.getvalue().encode("utf-8-sig")
    return send_file(
        io.BytesIO(data),
        mimetype="text/csv; charset=utf-8",
        as_attachment=True,
        download_name="productiq-amazon-research.csv",
    )


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
        "Manufacturer", "Image 1", "Image 2", "Image 3", "Image 4", "Image 5", "SKU", "UPC", "Store Category", "Store Subcategory", "Input Cost", "Market Low", "Market Average", "Market High", "Suggested Price", "Estimated Profit", "Estimated Margin %", "Competitors", "Cross-Sells", "Upsells", "Error"
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
            result.get("manufacturer", ""), *(images + [""] * 5)[:5],
            (result.get("sourceInput") or {}).get("sku", ""), (result.get("sourceInput") or {}).get("upc", ""),
            (result.get("catalogCategory") or {}).get("category", ""), (result.get("catalogCategory") or {}).get("subcategory", ""),
            (result.get("pricing") or {}).get("cost", ""), (result.get("pricing") or {}).get("marketLow", ""),
            (result.get("pricing") or {}).get("marketAverage", ""), (result.get("pricing") or {}).get("marketHigh", ""),
            (result.get("pricing") or {}).get("suggestedPrice", ""), (result.get("pricing") or {}).get("estimatedProfit", ""),
            (result.get("pricing") or {}).get("estimatedMargin", ""),
            " | ".join(f"{c.get('retailer','')}: ${c.get('price')} {c.get('url','')}" for c in result.get("competitors", []) if c.get("url")),
            " | ".join(f"{x.get('title','')} ({x.get('reason','')})" for x in result.get("crossSells", [])),
            " | ".join(f"{x.get('title','')} ({x.get('reason','')})" for x in result.get("upsells", [])), result.get("error", "")
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

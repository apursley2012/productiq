ARTICLES = {
    "why-i-built-productiq": {
        "title": "Why I Built ProductIQ",
        "dek": "I was tired of having product information in one place, research in another, and a ridiculous amount of the process still depending on me copying things around by hand.",
        "read_time": "8 min read",
        "sections": [
            ("I did not need another pretty dashboard", [
                "ProductIQ started because I already had product lists and I already had code that could pull information from Amazon. What I did not have was one tool that actually connected those things without making me babysit the entire process.",
                "Most of the time I am not starting with one perfect product record. I might have an ASIN for one item, a UPC for another, a model number for another, and a spreadsheet with names that are formatted however whoever made the spreadsheet felt like formatting them. I wanted to be able to hand that mess to one app and let it do as much of the repetitive work as possible.",
                "That is really the whole point. I do not want to spend my time opening the same kinds of pages, copying the same kinds of fields, checking the same kinds of prices, and putting all of it back into another spreadsheet."
            ]),
            ("The spreadsheet had to come first", [
                "A lot of apps make you enter everything into their system before they can help you. That would have been completely backwards for this. If I already have twenty-five products in a spreadsheet, I should not have to type twenty-five products into a form so the app can research them.",
                "So ProductIQ accepts CSV and Excel files and lets me map the columns that matter. ASIN, URL, UPC, EAN, GTIN, model, SKU, brand, cost, quantity, category, whatever I actually have can come along with the product instead of being thrown away.",
                "For a few products, pasting them in is easier. For a real inventory list, uploading the file is easier. I wanted both because that is how I would actually use it."
            ]),
            ("Finding the right product matters more than finding a product", [
                "One of the easiest ways for product research to become useless is for the app to confidently research the wrong variation. A twelve-pack is not the same thing as a single item. A different size is not close enough just because the title looks similar. A used listing should not be compared to a new item like they are the same thing.",
                "That is why ProductIQ keeps the identifiers it starts with and uses them when it scores possible matches. UPC, model number, part number, ASIN, brand, title terms, pack count, size, and condition all matter. If something conflicts, I would rather have it marked for review than have a bad comparison quietly influence the price."
            ]),
            ("I wanted the rest of the research connected too", [
                "Amazon research was the original piece, but once I already have the product in the app, stopping there does not make much sense. I also want to know where else that product is being sold, what the market range looks like, what I can realistically charge, what the margin would be, and what else in my own inventory makes sense next to it.",
                "That is where the competitor research, pricing, categorization, cross-sells, and upsells come in. Those pieces should use the product data I already uploaded. They should not disappear just because Amazon decides to throw a CAPTCHA in the middle of the process.",
                "That separation ended up being more important than I expected. Amazon is one source. It should not be a master switch that turns every other part of ProductIQ off."
            ]),
            ("I care more about useful failures than fake success", [
                "Anything that depends on outside websites is going to fail sometimes. Pages change. Search engines block automated requests. A listing disappears. Amazon asks for verification. Pretending none of that happens does not make the app better.",
                "What I want instead is for ProductIQ to tell me what it actually found, what it could not verify, and what I can do next. A result that needs review is useful. A made-up result that looks complete is not.",
                "The goal is not to make every card on the screen look full. The goal is to save me work without making me wonder whether the data is real."
            ]),
            ("What I want ProductIQ to feel like", [
                "I want to be able to upload a product list, start the research, deal with the occasional thing that genuinely needs me, and come back to organized information I can actually use.",
                "I do not want a dozen little tools that each solve ten percent of the problem. I want one workflow where the original product data stays attached to the research, the comparisons make sense, and I can export everything when I am done.",
                "That is what I am building ProductIQ around."
            ]),
        ],
    },
    "when-amazon-doesnt-cooperate": {
        "title": "When Amazon Gets in the Way",
        "dek": "The hardest part of ProductIQ is not parsing a title. It is keeping the whole workflow useful when Amazon decides not to give the app the page it asked for.",
        "read_time": "7 min read",
        "sections": [
            ("Amazon is not a database I control", [
                "It would be nice if every Amazon product page had the same structure, every field was always present, and the site never cared how many pages I needed to research. That is obviously not how it works.",
                "Different listings expose different information. Pages change. Search results are not always clean. Sometimes a request that should return a product page returns a verification page instead. Any app built around Amazon has to deal with that reality instead of designing as if it will never happen."
            ]),
            ("A CAPTCHA is not just a broken image", [
                "This was one of the more annoying problems because the CAPTCHA belongs to the same Amazon session that triggered it. The cookies matter. The form values matter. The browser identity matters. Even the image can stop working if I wait and try to fetch it again like it is just a normal picture.",
                "So ProductIQ should not throw a tiny broken image into a popup and call that CAPTCHA handling. When Amazon asks for verification, the research job needs to pause, keep that exact session alive, capture the challenge while it is fresh, and give me a separate verification screen to complete it.",
                "After Amazon accepts the answer, I should be able to go back to the original ProductIQ tab and continue the same batch. I should not have to start everything over because one product hit a robot check."
            ]),
            ("The rest of ProductIQ should not die with Amazon", [
                "This is the part that mattered once I started adding more intelligence around the original scraper. Categorization, competitor searching, pricing, and inventory relationships can use the data from my spreadsheet. They do not all need Amazon to finish first.",
                "If Amazon is blocked, I still have a product. I still have its name, UPC, model, brand, cost, quantity, and whatever else I uploaded. ProductIQ should keep working with that information instead of returning an empty shell."
            ]),
            ("No match should actually mean no match", [
                "There is a difference between 'I searched and did not find a convincing match' and 'the code only tried one overly specific query and gave up.' I do not want those treated like the same thing.",
                "The research needs to try identifiers first because they are the strongest signal, then model and brand, then product-title searches. It also needs more than one search source because any one public search page can fail or change.",
                "If ProductIQ finds candidates that are not strong enough, I still want to see that they were found and why they were considered weak. That gives me something I can check instead of a useless blank page."
            ]),
            ("A failure should be contained", [
                "If product nine out of twenty-five has a problem, product nine has a problem. Products one through eight should not suddenly stop existing.",
                "That sounds obvious, but it is one of the biggest differences between a script I can run and an app I actually want to use. The app needs to keep completed work, keep partial work when it is useful, and let me retry the thing that failed instead of repeating everything."
            ]),
            ("The point is less babysitting", [
                "I am not trying to pretend outside sites will always cooperate. I am trying to make sure their problems do not become twenty extra problems for me.",
                "If ProductIQ can keep the batch intact, show me exactly where it got stuck, let me handle the one manual step that is actually required, and continue, then it is doing what I built it for."
            ]),
        ],
    },
    "spreadsheet-first": {
        "title": "Why ProductIQ Starts With a Spreadsheet",
        "dek": "My product information already exists before I open ProductIQ. The app should work with that instead of making me start over.",
        "read_time": "6 min read",
        "sections": [
            ("My data is never in one perfect format", [
                "Sometimes I have an ASIN. Sometimes I have a UPC. Sometimes I have a model number and a brand. Sometimes the only useful thing in the row is the product name. Real inventory files are not neat just because an app wishes they were.",
                "That is why I wanted column mapping instead of one rigid upload template. ProductIQ can suggest which columns look like identifiers, cost, quantity, category, and the rest, but I can correct the mapping before the products go into the queue."
            ]),
            ("I do not want to throw away information I already have", [
                "If my spreadsheet already knows the SKU, cost, quantity, condition, or category, that data needs to stay attached to the product. It is not filler. It is what makes the later pricing and inventory logic useful.",
                "Cost is what lets me calculate whether a market price is even worth considering. Quantity is what keeps an out-of-stock item from being recommended as a cross-sell. Category data I already trust should beat an automatic guess."
            ]),
            ("Identifiers should actually be used", [
                "Accepting a UPC or model number in the upload does not count for much if the research code ignores it five seconds later. If I gave ProductIQ a strong identifier, it should use that identifier when it searches.",
                "The order matters too. Exact identifiers are better than title similarity. Brand and model are better than a couple of overlapping words. The weaker the evidence gets, the more clearly the result should say that it needs review."
            ]),
            ("Categorization cannot be a tiny keyword list", [
                "A real resale inventory can contain basically anything. Electronics, beauty products, furniture parts, baby items, tools, pet supplies, clothing, groceries, office supplies, weird replacement pieces that do not fit neatly anywhere. A list with thirty keyword rules is obviously not going to cover that.",
                "I still like having a store-friendly taxonomy because it makes browsing and related-product suggestions more useful, but it needs fallbacks. If Amazon or another product page gives me a legitimate category path, ProductIQ should preserve it even if I did not pre-write that exact category. If there is no marketplace category at all, it should at least derive a specific product-type bucket instead of dumping everything into 'Other.'"
            ]),
            ("The inventory itself should drive recommendations", [
                "Cross-sells and upsells are only useful to me if they are things I can actually sell. I do not need ProductIQ recommending a random accessory from the internet that I do not carry.",
                "So those suggestions should come from the products in the same catalog, and anything I know is out of stock should be excluded. An upsell should also actually be an upsell, not just another item in the same category that happens to exist."
            ]),
            ("The spreadsheet is the starting point, not the final destination", [
                "I want ProductIQ to add to the data I already have, not trap it. After the research and organization are done, I still need to be able to export the result and use it somewhere else.",
                "That is why CSV and Excel matter on both ends of the workflow. The file gets me into ProductIQ without retyping everything, and the export gets the finished data back out without making ProductIQ the only place it can live."
            ]),
        ],
    },
}

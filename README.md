<!--
File: README.md
Document Title: ProductIQ
Author: Alysha Pursley
Date: August 2026
-->

<div align="center">

<img src="./productiq-app/ProductIQ/static/assets/productiq-logo.PNG" alt="ProductIQ logo" width="65%">

<h1>ProductIQ 🔎</h1>

<p><a href="https://github.com/apursley2012/productiq/stargazers"><img src="https://img.shields.io/github/stars/apursley2012/productiq?style=for-the-badge&amp;logo=github&amp;label=Stars" alt="Stars"></a> <a href="https://github.com/apursley2012/productiq/forks"><img src="https://img.shields.io/github/forks/apursley2012/productiq?style=for-the-badge&amp;logo=github&amp;label=Forks" alt="Forks"></a> <a href="https://github.com/apursley2012/productiq/issues"><img src="https://img.shields.io/github/issues/apursley2012/productiq?style=for-the-badge&amp;logo=github&amp;label=Issues" alt="Issues"></a> <a href="https://github.com/apursley2012/productiq/commits"><img src="https://img.shields.io/github/last-commit/apursley2012/productiq?style=for-the-badge&amp;logo=git&amp;label=Last%20Commit" alt="Last Commit"></a> <a href="https://github.com/apursley2012/productiq"><img src="https://img.shields.io/github/repo-size/apursley2012/productiq?style=for-the-badge&amp;logo=github&amp;label=Repo%20Size" alt="Repo Size"></a> <a href="https://github.com/apursley2012/productiq"><img src="https://img.shields.io/github/languages/top/apursley2012/productiq?style=for-the-badge&amp;label=Top%20Language" alt="Top Language"></a></p>

<p><a href="https://apursley2012.github.io/productiq/"><img src="https://img.shields.io/badge/Live%20Demo-GitHub%20Pages-222222?style=for-the-badge&amp;logo=githubpages&amp;logoColor=white" alt="Live Demo"></a> <img src="https://img.shields.io/badge/Python-3776AB?style=for-the-badge&amp;logo=python&amp;logoColor=white" alt="Python"> <img src="https://img.shields.io/badge/Flask-000000?style=for-the-badge&amp;logo=flask&amp;logoColor=white" alt="Flask"> <img src="https://img.shields.io/badge/Playwright-2EAD33?style=for-the-badge&amp;logo=playwright&amp;logoColor=white" alt="Playwright"> <img src="https://img.shields.io/badge/HTML5-E34F26?style=for-the-badge&amp;logo=html5&amp;logoColor=white" alt="HTML5"> <img src="https://img.shields.io/badge/CSS3-1572B6?style=for-the-badge&amp;logo=css3&amp;logoColor=white" alt="CSS3"> <img src="https://img.shields.io/badge/JavaScript-F7DF1E?style=for-the-badge&amp;logo=javascript&amp;logoColor=black" alt="JavaScript"></p>

<p><strong>A product research workspace for turning product identifiers and spreadsheets into organized product intelligence, Amazon data, images, pricing context, and review-ready research results.</strong></p>

<p><a href="https://apursley2012.github.io/productiq/">Open the live project</a> · <a href="https://github.com/apursley2012/productiq">View the repository</a> · <a href="https://github.com/apursley2012/productiq/issues/new/choose">Report an issue or request an addition</a></p>

</div>

---

## Table of Contents 📖

*   [Project Overview 🔎](#project-overview)
    *   [Purpose 🎯](#purpose)
    *   [Design Style and Inspiration 🎨](#design-style-and-inspiration)
    *   [Main Color Palette 🌈](#main-color-palette)
    *   [Preview Screenshots 🖼️](#preview-screenshots)
*   [Key Features ✨](#key-features)
*   [Tech Stack 🛠️](#tech-stack)
*   [Live Demo 🚀](#live-demo)
*   [Installation 📦](#installation)
    *   [Local Use 💻](#local-use)
    *   [GitHub Pages Deployment 🌐](#github-pages-deployment)
*   [Usage 🧭](#usage)
*   [Project Structure 🗂️](#project-structure)
    *   [Pages Included 📄](#pages-included)
    *   [Core Files and Architecture 🧩](#core-files-and-architecture)
    *   [File and Folder Structure 🌳](#file-and-folder-structure)
*   [Research Pipeline and Hosting Model 🔬](#research-pipeline-and-hosting-model)
*   [Customization Guide 🎨](#customization-guide)
*   [Accessibility and Browser Compatibility ♿](#accessibility-and-browser-compatibility)
*   [Repository Relationship 🔗](#repository-relationship)
*   [Project Scope and Limitations 📌](#project-scope-and-limitations)
*   [Possible Future Enhancements 💡](#possible-future-enhancements)
*   [Contributing 🤝](#contributing)
    *   [Reporting Issues 🐛](#reporting-issues)
    *   [Requesting Additions 📝](#requesting-additions)
*   [License 📜](#license)
*   [Important Links 🔗](#important-links)
*   [Copyright ©️](#copyright)

---

<a id="project-overview"></a>

<details open>
<summary><strong>Project Overview 🔎</strong></summary>


## Project Overview 🔎

I developed **ProductIQ** as a product research workspace for turning product identifiers and spreadsheets into organized product intelligence, Amazon data, images, pricing context, and review-ready research results.

</details>

<a id="purpose"></a>

<details open>
<summary><strong>Purpose 🎯</strong></summary>


### Purpose 🎯

I built ProductIQ because product research gets tedious fast when the same information has to be copied, compared, cleaned up, and organized over and over. The application accepts product identifiers directly or through spreadsheet uploads, processes them through a research workflow, and keeps the resulting information together so it can be reviewed instead of reconstructed from scattered tabs. The project also keeps the GitHub Pages shell separate from the hosted research backend because scraping and browser automation cannot run inside a static site.

</details>

<a id="design-style-and-inspiration"></a>

<details open>
<summary><strong>Design Style and Inspiration 🎨</strong></summary>


### Design Style and Inspiration 🎨

ProductIQ is styled as a research workspace rather than a storefront. Dark navy panels, purple and blue accents, compact status treatments, tables, and result cards support dense product information while keeping verified data, comparisons, recommendations, and incomplete research visually distinct. The design follows the application workflow: identify a product, gather evidence, compare findings, and move into increasingly detailed research without losing context.

</details>

<a id="main-color-palette"></a>

<details open>
<summary><strong>Main Color Palette 🌈</strong></summary>


### Main Color Palette 🌈

I pulled the palette below directly from the current project stylesheet `productiq-app/ProductIQ/static/styles.css`.

| Hex | Color Name | Primary Use |
| --- | --- | --- |
| `#07101F` | Midnight Navy | Deep application background |
| `#0F172A` | Soft Navy | Secondary dark background and layered surfaces |
| `#111C31` | Panel Navy | Primary panels, cards, and research work areas |
| `#16243D` | Soft Panel Blue | Secondary panels and nested interface areas |
| `#7C3AED` | ProductIQ Purple | Primary brand accent and interactive emphasis |
| `#6425D0` | Deep Purple | Darker purple states and gradients |
| `#3B82F6` | Research Blue | Secondary action, status, and comparison accent |
| `#2563EB` | Deep Blue | Darker blue states and emphasis |
| `#F8FAFC` | Near White | Primary high-contrast text |
| `#9FB0C7` | Muted Blue Gray | Secondary text and metadata |
| `#263653` | Slate Line | Borders and panel separation |
| `#48D7AD` | Mint Green | Success and verified-result states |
| `#FF7188` | Soft Red | Warnings, errors, and risk states |

</details>

<a id="preview-screenshots"></a>

<details open>
<summary><strong>Preview Screenshots 🖼️</strong></summary>


### Preview Screenshots 🖼️

Click any preview image in the repository screenshot folder to open the full-size file.


#### 🖼️ Screenshot Gallery


The gallery uses paired, centered images when screenshots are present. Keep screenshots under `images/screenshots/` and use names such as `productiq-screenshot-01.png`, `productiq-screenshot-02.png`, and so on. I have not invented image filenames that were not verified in the current project source.

</details>

---

<a id="key-features"></a>

<details open>
<summary><strong>Key Features ✨</strong></summary>


## Key Features ✨

*   **Accept ASINs and other product identifiers through manual input**
*   **Upload spreadsheets and map product columns before processing**
*   **Queue and process multiple products in one research run**
*   **Retrieve Amazon product details through the backend research workflow**
*   **Capture product titles, descriptions, bullet points, pricing information, and images when available**
*   **Show progress, success, review-needed, error, and CAPTCHA states**
*   **Provide a dark product-intelligence workspace with responsive result cards**
*   **Keep the static GitHub Pages shell separate from the hosted Flask/Playwright application**

</details>

---

<a id="tech-stack"></a>

<details open>
<summary><strong>Tech Stack 🛠️</strong></summary>


## Tech Stack 🛠️

*   **HTML/CSS/JavaScript GitHub Pages shell**
*   **Python**
*   **Flask**
*   **Playwright**
*   **Beautiful Soup / HTML parsing utilities**
*   **Spreadsheet processing**
*   **Server-rendered templates**
*   **Static frontend assets**

</details>

---

<a id="live-demo"></a>

<details open>
<summary><strong>Live Demo 🚀</strong></summary>


## Live Demo 🚀

Open the published project here:

[https://apursley2012.github.io/productiq/](https://apursley2012.github.io/productiq/)

</details>

---

<a id="installation"></a>

<details open>
<summary><strong>Installation 📦</strong></summary>


## Installation 📦

</details>

<a id="local-use"></a>

<details open>
<summary><strong>Local Use 💻</strong></summary>


### Local Use 💻

1. Clone or download the repository.
2. Keep the existing folder structure intact so the page can still find its styles, scripts, data, and assets.
3. Open the root `index.html` for static projects, or follow the project-specific runtime instructions when a backend/source application is included.
4. Before I publish changes, I check the main workflow, navigation, saved browser data where it applies, and the responsive layout.

</details>

<a id="github-pages-deployment"></a>

<details open>
<summary><strong>GitHub Pages Deployment 🌐</strong></summary>


### GitHub Pages Deployment 🌐

For the static/public portion, keep `index.html` at the repository root, use relative asset paths, then enable **Settings → Pages → Deploy from a branch → main → / (root)**. Projects that include Python, Node, MongoDB, authentication, browser automation, or another server runtime still need an appropriate backend host for those server-dependent features.

</details>

---

<a id="usage"></a>

<details open>
<summary><strong>Usage 🧭</strong></summary>


## Usage 🧭

Start with the main page and follow the project’s primary workflow. The interface is intended to be usable without reading the source first, while the case studies, articles, documentation, and source folders provide the deeper implementation context. Where browser storage is used, saved information belongs to that browser/device unless the project explicitly includes a shared backend.

</details>

---

<a id="project-structure"></a>

<details open>
<summary><strong>Project Structure 🗂️</strong></summary>


## Project Structure 🗂️

</details>

<a id="pages-included"></a>

<details open>
<summary><strong>Pages Included 📄</strong></summary>


### Pages Included 📄

| Page / Area | Purpose |
| --- | --- |
| `index.html` | Static GitHub Pages shell that displays the hosted application |
| `styles.css` | Full-screen shell styling |
| `productiq-app/ProductIQ/` | Flask application, templates, static assets, and research logic |
| `productiq-app/ProductIQ/static/styles.css` | Main application design system |
| `productiq-app/ProductIQ/templates/` | Application pages, result views, case study, and CAPTCHA interface |

</details>

<a id="core-files-and-architecture"></a>

<details open>
<summary><strong>Core Files and Architecture 🧩</strong></summary>


### Core Files and Architecture 🧩

The repository separates the public interface from supporting source and documentation where the project needs that distinction. The important rule is that **ProductIQ should be documented as the project it is**, not as a generic theme or one-size-fits-all site. Files that implement the main workflow belong with the application, while case studies, articles, source history, data, or backend code are documented according to their real role.

</details>

<a id="file-and-folder-structure"></a>

<details open>
<summary><strong>File and Folder Structure 🌳</strong></summary>


### File and Folder Structure 🌳

```text
productiq/
├── README.md
├── index.html
├── styles.css
├── productiq-app/ProductIQ/
├── productiq-app/ProductIQ/static/styles.css
└── productiq-app/ProductIQ/templates/
```

This tree highlights the major documented areas rather than inventing files that were not verified.

</details>

---

<a id="research-pipeline-and-hosting-model"></a>

<details open>
<summary><strong>Research Pipeline and Hosting Model 🔬</strong></summary>


## Research Pipeline and Hosting Model 🔬

ProductIQ has two deliberate layers. The GitHub Pages repository root is a static shell, while the actual research application lives in the Python/Flask portion of the project. That split matters because GitHub Pages can display HTML, CSS, and JavaScript but cannot run Playwright, Python scraping logic, or server-side CAPTCHA handling.

The research flow starts with identification and input cleanup, moves through queued processing, and ends with result cards that make uncertainty visible. A product can complete successfully, need review, fail, or require CAPTCHA intervention. Those states are part of the workflow instead of being hidden behind a generic “research complete” message.

</details>

---

<a id="customization-guide"></a>

<details open>
<summary><strong>Customization Guide 🎨</strong></summary>


## Customization Guide 🎨

The safest way to customize or extend **ProductIQ** is to preserve its existing workflow first, then change one layer at a time. Update project content and data in the files that already own that information, keep visual changes inside the existing style system, and test every page that shares the changed component or data source. New features should solve a problem that belongs to this project instead of copying a feature from an unrelated application.

For visual changes, update the documented palette intentionally and re-check contrast, responsive spacing, screenshots, and any state colors that depend on the same variables. For data or logic changes, test both the normal path and empty/error/edge cases before publishing.

</details>

---

<a id="accessibility-and-browser-compatibility"></a>

<details open>
<summary><strong>Accessibility and Browser Compatibility ♿</strong></summary>


## Accessibility and Browser Compatibility ♿

The public interface should remain keyboard-navigable, readable at common mobile and desktop widths, and usable without relying on color alone to communicate state. Form controls should keep visible labels or accessible names, images should use meaningful `alt` text, focus indicators should remain visible, and decorative animation should respect reduced-motion preferences when motion is present. Browser compatibility should be checked in current Safari, Chrome, Firefox, and Edge where practical.

</details>

---

<a id="repository-relationship"></a>

<details open>
<summary><strong>Repository Relationship 🔗</strong></summary>


## Repository Relationship 🔗

**ProductIQ** is documented as its own project. Supporting case studies, articles, source history, static presentation layers, or backend/runtime folders are parts of this repository only when they help explain or run this project. They should not be described as separate replacement projects.

Where this repository contains both a static GitHub Pages layer and source that requires another runtime, the two are related but not interchangeable: the static layer provides the public experience that can run in a browser, while the source/runtime layer preserves functionality that GitHub Pages cannot execute directly.

</details>

---

<a id="project-scope-and-limitations"></a>

<details open>
<summary><strong>Project Scope and Limitations 📌</strong></summary>


## Project Scope and Limitations 📌

This README separates what the published browser version can do from functionality that belongs to a backend, database, native application, notebook, or other runtime. Static hosting limitations are stated where they materially affect the project. The documentation should not imply that GitHub Pages is providing server-side authentication, Python execution, MongoDB access, SMS delivery, or another service it cannot actually run.

</details>

---

<a id="possible-future-enhancements"></a>

<details open>
<summary><strong>Possible Future Enhancements 💡</strong></summary>


## Possible Future Enhancements 💡

*   Continue hardening CAPTCHA and retailer-response handling
*   Expand normalized competitor and supplier research while keeping confidence visible
*   Add more export formats for approved research data
*   Improve retry and recovery behavior for long multi-product runs

</details>

---

<a id="contributing"></a>

<details open>
<summary><strong>Contributing 🤝</strong></summary>


## Contributing 🤝

Contributions, bug reports, and practical improvement suggestions are welcome when they preserve the existing project direction and do not replace its identity with a generic redesign.

</details>

<a id="reporting-issues"></a>

<details open>
<summary><strong>Reporting Issues 🐛</strong></summary>


### Reporting Issues 🐛

When reporting a problem, include the page or workflow involved, what you expected, what actually happened, browser/device information when relevant, and a screenshot if the issue is visual.

</details>

<a id="requesting-additions"></a>

<details open>
<summary><strong>Requesting Additions 📝</strong></summary>


### Requesting Additions 📝

Feature requests should explain the user problem the addition would solve and how it fits the existing project. Project-specific improvements are preferred over adding features only because they are common in other applications.

</details>

---

<a id="license"></a>

<details open>
<summary><strong>License 📜</strong></summary>


## License 📜

No license terms are assumed here. If the repository includes a `LICENSE` file, that file controls reuse. If it does not, normal copyright applies and permission should not be inferred from the repository being public.

</details>

---

<a id="important-links"></a>

<details open>
<summary><strong>Important Links 🔗</strong></summary>


## Important Links 🔗

*   **Live Project:** [https://apursley2012.github.io/productiq/](https://apursley2012.github.io/productiq/)
*   **Repository:** [https://github.com/apursley2012/productiq](https://github.com/apursley2012/productiq)
*   **Issues / Requests:** [https://github.com/apursley2012/productiq/issues/new/choose](https://github.com/apursley2012/productiq/issues/new/choose)

</details>

---

<a id="copyright"></a>

<details open>
<summary><strong>Copyright ©️</strong></summary>


## Copyright ©️

© 2026 Alysha Pursley. Project documentation and original project materials are credited to their respective sources where applicable.


---

Made with care by Alysha Pursley.

</details>

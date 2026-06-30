import re
from urllib.parse import quote_plus, unquote, urlparse

import httpx
from selectolax.parser import HTMLParser

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
TIMEOUT = 10.0

TECH_KEYWORDS = [
    "aws", "azure", "gcp", "kubernetes", "docker", "postgresql", "postgres",
    "mysql", "redis", "react", "python", "node.js", "terraform", "kafka",
    "mongodb", "elasticsearch", "snowflake", "databricks",
]

INDUSTRY_KEYWORDS = {
    "saas": "SaaS",
    "fintech": "FinTech",
    "healthtech": "HealthTech",
    "healthcare": "Healthcare",
    "e-commerce": "E-Commerce",
    "ecommerce": "E-Commerce",
    "cybersecurity": "Cybersecurity",
    "artificial intelligence": "AI/ML",
    "machine learning": "AI/ML",
    "edtech": "EdTech",
    "logistics": "Logistics",
    "manufacturing": "Manufacturing",
}


def _slugify(company_name: str) -> str:
    slug = company_name.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "", slug)
    return slug


def _extract_text(html: str) -> str:
    parser = HTMLParser(html)
    for tag in parser.css("script, style, noscript"):
        tag.decompose()
    return parser.body.text(separator=" ", strip=True) if parser.body else ""


def _infer_company_size(text: str) -> str:
    patterns = [
        r"(\d[\d,]*)\s*\+\s*employees",
        r"(\d[\d,]*)\s*employees",
        r"team of\s*(\d[\d,]*)",
        r"(\d[\d,]*)\s*people\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(0).strip()
    return "unknown"


def _infer_tech_stack(text: str) -> str:
    lower = text.lower()
    found = [kw for kw in TECH_KEYWORDS if kw in lower]
    return ", ".join(found[:8]) if found else "unknown"


def _infer_industry(text: str) -> str:
    lower = text.lower()
    for keyword, label in INDUSTRY_KEYWORDS.items():
        if keyword in lower:
            return label
    return "unknown"


def _parse_ddg_results(html: str, limit: int = 5) -> list[dict[str, str]]:
    parser = HTMLParser(html)
    results: list[dict[str, str]] = []
    for node in parser.css(".result"):
        link = node.css_first("a.result__a")
        snippet = node.css_first(".result__snippet")
        if not link:
            continue
        href = link.attributes.get("href", "")
        if "uddg=" in href:
            match = re.search(r"uddg=([^&]+)", href)
            if match:
                href = unquote(match.group(1))
        results.append({
            "url": href,
            "title": link.text(strip=True),
            "snippet": snippet.text(strip=True) if snippet else "",
        })
        if len(results) >= limit:
            break
    return results


async def _ddg_search(client: httpx.AsyncClient, query: str, limit: int = 5) -> list[dict[str, str]]:
    response = await client.post(
        "https://html.duckduckgo.com/html/",
        data={"q": query},
        follow_redirects=True,
    )
    if response.status_code != 200:
        return []
    return _parse_ddg_results(response.text, limit=limit)


async def _fetch_page(client: httpx.AsyncClient, url: str) -> str | None:
    try:
        response = await client.get(url, follow_redirects=True)
        if response.status_code == 200 and "text/html" in response.headers.get("content-type", ""):
            return response.text
    except httpx.HTTPError:
        pass
    return None


async def _resolve_company_domain(client: httpx.AsyncClient, company_name: str) -> str | None:
    slug = _slugify(company_name)
    if not slug:
        return None

    candidates = [f"https://{slug}.com", f"https://www.{slug}.com"]
    # hyphenated fallback
    hyphenated = re.sub(r"[\s_]+", "-", company_name.lower())
    hyphenated = re.sub(r"[^a-z0-9-]", "", hyphenated)
    if hyphenated and hyphenated != slug:
        candidates.extend([f"https://{hyphenated}.com", f"https://www.{hyphenated}.com"])

    for url in candidates:
        html = await _fetch_page(client, url)
        if html:
            return url

    results = await _ddg_search(client, f"{company_name} official website", limit=3)
    for result in results:
        url = result["url"]
        if not url.startswith("http"):
            continue
        host = urlparse(url).netloc.lower()
        if any(skip in host for skip in ("linkedin.com", "facebook.com", "twitter.com", "wikipedia.org")):
            continue
        html = await _fetch_page(client, url)
        if html:
            return url

    return None


async def scrape_company_site(company_name: str) -> dict[str, str]:
    async with httpx.AsyncClient(
        timeout=TIMEOUT,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        domain = await _resolve_company_domain(client, company_name)
        if not domain:
            return {"error": "domain_not_found"}

        pages: list[str] = []
        homepage = await _fetch_page(client, domain)
        if homepage:
            pages.append(homepage)

        base = domain.rstrip("/")
        for path in ("/about", "/pricing"):
            page = await _fetch_page(client, f"{base}{path}")
            if page:
                pages.append(page)

            # also follow about/pricing links from homepage nav
        if homepage:
            parser = HTMLParser(homepage)
            for anchor in parser.css("a[href]"):
                href = anchor.attributes.get("href", "")
                lower = href.lower()
                if any(k in lower for k in ("/about", "/pricing", "about-us", "plans")):
                    if href.startswith("/"):
                        href = f"{base}{href}"
                    elif not href.startswith("http"):
                        continue
                    if urlparse(href).netloc and urlparse(href).netloc != urlparse(base).netloc:
                        continue
                    page = await _fetch_page(client, href)
                    if page:
                        pages.append(page)

        if not pages:
            return {"error": "no_content"}

        combined = " ".join(_extract_text(page) for page in pages)
        return {
            "company_domain": domain,
            "company_size": _infer_company_size(combined),
            "tech_stack": _infer_tech_stack(combined),
            "industry": _infer_industry(combined),
        }


async def scrape_linkedin(name: str, company: str) -> dict[str, str]:
    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            query = f'site:linkedin.com/in "{name}" "{company}"'
            results = await _ddg_search(client, query, limit=3)

            linkedin_urls = [
                r["url"] for r in results
                if "linkedin.com/in/" in r.get("url", "").lower()
            ]

            if not linkedin_urls:
                return {"error": "blocked_or_unavailable"}

            # light attempt — expect frequent blocks; never raise
            profile_url = linkedin_urls[0]
            response = await client.get(profile_url, follow_redirects=True)
            if response.status_code != 200:
                # fall back to DDG snippet only
                for result in results:
                    if "linkedin.com/in/" in result.get("url", "").lower():
                        title = result.get("title", "unknown")
                        return {
                            "title": title,
                            "seniority": title,
                            "snippet": result.get("snippet", ""),
                            "profile_url": result.get("url", ""),
                        }
                return {"error": "blocked_or_unavailable"}

            text = _extract_text(response.text)
            title_match = re.search(
                r"(CEO|CTO|CFO|COO|VP|Director|Manager|Engineer|Founder|Head of [A-Za-z\s]+)",
                text,
                re.IGNORECASE,
            )
            title = title_match.group(0) if title_match else "unknown"
            return {
                "title": title,
                "seniority": title,
                "profile_url": profile_url,
                "snippet": text[:300],
            }
    except Exception:
        return {"error": "blocked_or_unavailable"}


async def scrape_news(company_name: str) -> dict[str, str]:
    async with httpx.AsyncClient(
        timeout=TIMEOUT,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        query = f"{company_name} news"
        response = await client.get(
            f"https://html.duckduckgo.com/html/?q={quote_plus(query)}",
            follow_redirects=True,
        )
        if response.status_code != 200:
            return {"error": "search_failed"}

        results = _parse_ddg_results(response.text, limit=3)
        if not results:
            return {"error": "no_results"}

        output: dict[str, str] = {}
        headlines = []
        for i, item in enumerate(results, start=1):
            title = item.get("title", "")
            output[f"headline_{i}"] = title
            output[f"snippet_{i}"] = item.get("snippet", "")
            if title:
                headlines.append(title)
                
        output["recent_news"] = " | ".join(headlines) if headlines else "unknown"
        return output

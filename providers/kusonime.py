import urllib.parse
from bs4 import BeautifulSoup
from core.fetcher import fetch_html

BASE_URL = "https://kusonime.com"

def search(query: str, page: int = 1) -> list:
    """Cari anime batch di Kusonime dengan pagination web"""
    if page > 1:
        url = f"{BASE_URL}/page/{page}/?s={urllib.parse.quote(query)}"
    else:
        url = f"{BASE_URL}/?s={urllib.parse.quote(query)}"

    html = fetch_html(url)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    results = []
    articles = soup.select("article") or soup.select(".kover")

    for a in articles:
        link_el = a.select_one("a")
        if not link_el:
            continue
        href = link_el.get("href", "")
        title_el = a.select_one(".episodeye") or a.select_one("h2") or link_el
        title = title_el.get_text(strip=True) if title_el else ""

        img_el = a.select_one("img")
        thumb = ""
        if img_el:
            thumb = img_el.get("src") or img_el.get("data-src") or ""

        results.append({
            "provider": "kusonime",
            "title": title,
            "url": href,
            "thumbnail": thumb,
            "type": "batch"
        })

    return results

def get_detail(url: str) -> dict:
    """Ambil info anime dan paket batch di Kusonime"""
    html = fetch_html(url)
    if not html:
        return {}

    soup = BeautifulSoup(html, "html.parser")
    title_el = soup.select_one("h1.jdlmb") or soup.select_one(".jdlh1") or soup.select_one("h1")
    if title_el and title_el.get_text(strip=True):
        title = title_el.get_text(strip=True)
    elif soup.title and soup.title.string:
        title = soup.title.string.split("|")[0].split("–")[0].strip()
    else:
        title = "Anime Detail"

    thumb_el = soup.select_one(".post-thumb img") or soup.select_one("article img")
    thumb = thumb_el.get("src") if thumb_el else ""

    desc_ps = soup.select(".lexot p")
    synopsis = "\n\n".join([p.get_text(strip=True) for p in desc_ps if p.get_text(strip=True)]) if desc_ps else "Sinopsis tidak tersedia."

    batches = []
    blocks = soup.select(".smokeddlrh") or soup.select(".smokeddl")

    for block in blocks:
        ttl = block.select_one(".smokettlrh") or block.select_one(".smokettl")
        batch_title = ttl.get_text(strip=True) if ttl else "Batch Download"
        
        resolutions = {}
        rows = block.select(".smokeurlrh") or block.select(".smokeurl")
        for row in rows:
            strong = row.select_one("strong")
            res_name = strong.get_text(strip=True) if strong else "Links"
            
            links = []
            for a in row.select("a"):
                srv = a.get_text(strip=True)
                h = a.get("href", "")
                if h:
                    links.append({"server": srv, "url": h})
            if links:
                resolutions[res_name] = links

        if resolutions:
            batches.append({
                "batch_name": batch_title,
                "resolutions": resolutions
            })

    return {
        "provider": "kusonime",
        "title": title,
        "url": url,
        "thumbnail": thumb,
        "synopsis": synopsis,
        "batches": batches
    }

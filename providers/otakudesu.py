import urllib.parse
from bs4 import BeautifulSoup
from core.fetcher import fetch_html

BASE_URL = "https://otakudesu.best"

def search(query: str, page: int = 1) -> list:
    """Cari anime di Otakudesu dengan pagination web"""
    if page > 1:
        url = f"{BASE_URL}/page/{page}/?s={urllib.parse.quote(query)}"
    else:
        url = f"{BASE_URL}/?s={urllib.parse.quote(query)}"

    html = fetch_html(url)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    results = []
    items = soup.select(".chivsrc li") or soup.select(".venz li")

    for li in items:
        link_el = li.select_one("h2 a") or li.select_one("a")
        if not link_el:
            continue
        href = link_el.get("href", "")
        title = link_el.get_text(strip=True)

        img_el = li.select_one("img")
        thumb = img_el.get("src") if img_el else ""

        results.append({
            "provider": "otakudesu",
            "title": title,
            "url": href,
            "thumbnail": thumb,
            "type": "batch" if "batch" in href or "batch" in title.lower() else "episode"
        })

    return results

def get_detail(url: str) -> dict:
    """Ambil detail anime & link download di Otakudesu"""
    html = fetch_html(url)
    if not html:
        return {}

    soup = BeautifulSoup(html, "html.parser")
    title_el = soup.select_one(".jdlcontent") or soup.select_one("h1")
    title = title_el.get_text(strip=True) if title_el else "Anime Detail"

    downloads = {}
    dl_blocks = soup.select(".download ul li") or soup.select(".smokedl ul li")

    for li in dl_blocks:
        strong = li.select_one("strong")
        res_name = strong.get_text(strip=True) if strong else "Links"
        links = []
        for a in li.select("a"):
            srv = a.get_text(strip=True)
            h = a.get("href", "")
            if h:
                links.append({"server": srv, "url": h})
        if links:
            downloads[res_name] = links

    return {
        "provider": "otakudesu",
        "title": title,
        "url": url,
        "downloads": downloads
    }

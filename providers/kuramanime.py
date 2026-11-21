import urllib.parse
from bs4 import BeautifulSoup
from core.fetcher import fetch_html

BASE_URL = "https://v20.kuramanime.ing"

def search(query: str, page: int = 1) -> list:
    """Cari anime di Kuramanime"""
    if page > 1:
        url = f"{BASE_URL}/anime?search={urllib.parse.quote(query)}&page={page}&order_by=latest"
    else:
        url = f"{BASE_URL}/anime?search={urllib.parse.quote(query)}&order_by=latest"

    html = fetch_html(url)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    results = []
    items = soup.select(".anime__item") or soup.select(".product__item") or soup.select("article")

    for it in items:
        link_el = it.select_one("a")
        if not link_el:
            continue
        href = link_el.get("href", "")
        title_el = it.select_one("h5") or it.select_one(".anime__item__text h5") or link_el
        title = title_el.get_text(strip=True) if title_el else ""

        img_el = it.select_one(".anime__item__pic") or it.select_one("img")
        thumb = ""
        if img_el:
            thumb = img_el.get("data-setbg") or img_el.get("src") or ""

        results.append({
            "provider": "kuramanime",
            "title": title,
            "url": href,
            "thumbnail": thumb,
            "type": "episode"
        })

    return results

def get_detail(url: str) -> dict:
    """Ambil detail anime & episode di Kuramanime"""
    html = fetch_html(url)
    if not html:
        return {}

    soup = BeautifulSoup(html, "html.parser")
    title_el = soup.select_one(".anime__details__title h3") or soup.select_one("h1")
    title = title_el.get_text(strip=True) if title_el else "Kuramanime Detail"

    downloads = {}
    dl_links = soup.select("#episodeList a") or soup.select(".episodes a")

    for a in dl_links:
        ep_name = a.get_text(strip=True)
        href = a.get("href", "")
        if href:
            if "Semua Episode" not in downloads:
                downloads["Semua Episode"] = []
            downloads["Semua Episode"].append({
                "server": ep_name,
                "url": href
            })

    return {
        "provider": "kuramanime",
        "title": title,
        "url": url,
        "downloads": downloads
    }

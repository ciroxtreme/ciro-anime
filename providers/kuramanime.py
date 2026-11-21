import html
import urllib.parse
from bs4 import BeautifulSoup
from core.fetcher import fetch_html

BASE_URL = "https://v20.kuramanime.ing"

def search(query: str, page: int = 1) -> list:
    """Cari anime di Kuramanime (Multi-Server & Stream)"""
    if page > 1:
        url = f"{BASE_URL}/anime?search={urllib.parse.quote(query)}&page={page}&order_by=latest"
    else:
        url = f"{BASE_URL}/anime?search={urllib.parse.quote(query)}&order_by=latest"

    page_html = fetch_html(url)
    if not page_html:
        return []

    soup = BeautifulSoup(page_html, "html.parser")
    results = []

    # Kuramanime render cards via anchor with /anime/<id>/<slug>
    for a in soup.select("a"):
        href = a.get("href", "")
        if "/anime/" not in href or href.count("/") < 5:
            continue
        title_el = a.select_one("h5") or a.select_one(".sidebar-title-h5")
        if not title_el:
            continue
        title = title_el.get_text(strip=True)
        if not title:
            continue

        img_div = a.select_one("[data-setbg]") or a.select_one("img")
        thumb = ""
        if img_div:
            thumb = img_div.get("data-setbg") or img_div.get("src") or ""

        if any(r["url"] == href for r in results):
            continue

        results.append({
            "provider": "kuramanime",
            "title": title,
            "url": href,
            "thumbnail": thumb,
            "type": "episode"
        })

    return results

def get_detail(url: str) -> dict:
    """Ambil detail anime & daftar episode / batch di Kuramanime"""
    page_html = fetch_html(url)
    if not page_html:
        return {}

    soup = BeautifulSoup(page_html, "html.parser")
    title_el = soup.select_one(".anime__details__title h3") or soup.select_one("h3") or soup.select_one("h1")
    title = title_el.get_text(strip=True) if title_el else "Kuramanime Detail"

    downloads = {}

    # 1. Ambil daftar Episode Pilihan dari data-content #episodeListsSection
    for btn in soup.select("#episodeListsSection [data-content], #episodeLists[data-content]"):
        content_html = html.unescape(btn.get("data-content", ""))
        sub_soup = BeautifulSoup(content_html, "html.parser")
        for a in sub_soup.select("a"):
            ep_name = a.get_text(strip=True)
            href = a.get("href", "")
            if href and "/episode/" in href:
                if "Episode" not in downloads:
                    downloads["Episode"] = []
                if not any(x["url"] == href for x in downloads["Episode"]):
                    downloads["Episode"].append({"server": ep_name, "url": href})

    # 2. Ambil daftar Batch Download dari #episodeBatchListsSection
    for btn in soup.select("#episodeBatchListsSection [data-content], #episodeBatchLists[data-content]"):
        content_html = html.unescape(btn.get("data-content", ""))
        sub_soup = BeautifulSoup(content_html, "html.parser")
        for a in sub_soup.select("a"):
            b_name = a.get_text(strip=True)
            href = a.get("href", "")
            if href and "/batch/" in href:
                if "Paket Batch" not in downloads:
                    downloads["Paket Batch"] = []
                if not any(x["url"] == href for x in downloads["Paket Batch"]):
                    downloads["Paket Batch"].append({"server": b_name, "url": href})

    return {
        "provider": "kuramanime",
        "title": title,
        "url": url,
        "downloads": downloads
    }

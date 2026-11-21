import urllib.parse
from bs4 import BeautifulSoup
from core.fetcher import fetch_html

BASE_URL = "https://v2.samehadaku.how"

def search(query: str, page: int = 1) -> list:
    """Cari anime di Samehadaku (Episode & Ongoing) dengan pagination web"""
    if page > 1:
        url = f"{BASE_URL}/page/{page}/?s={urllib.parse.quote(query)}"
    else:
        url = f"{BASE_URL}/?s={urllib.parse.quote(query)}"

    html = fetch_html(url)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    results = []
    articles = soup.select("article")

    for a in articles:
        link_el = a.select_one("a")
        if not link_el:
            continue
        href = link_el.get("href", "")
        title_el = a.select_one(".entry-title") or a.select_one("h2") or link_el
        title = title_el.get_text(strip=True) if title_el else ""

        img_el = a.select_one("img")
        thumb = ""
        if img_el:
            thumb = img_el.get("src") or img_el.get("data-src") or ""

        # Deteksi tipe
        is_batch = "/batch/" in href or "[batch]" in title.lower()
        item_type = "batch" if is_batch else "episode"

        results.append({
            "provider": "samehadaku",
            "title": title,
            "url": href,
            "thumbnail": thumb,
            "type": item_type
        })

    return results

def get_detail(url: str) -> dict:
    """Ambil detail anime atau episode di Samehadaku"""
    html = fetch_html(url)
    if not html:
        return {}

    soup = BeautifulSoup(html, "html.parser")
    title_el = soup.select_one("h1.entry-title") or soup.select_one("h1")
    title = title_el.get_text(strip=True) if title_el else ""

    thumb_el = soup.select_one(".thumb img") or soup.select_one("article img")
    thumb = thumb_el.get("src") if thumb_el else ""

    # Sinopsis
    desc_el = soup.select_one(".entry-content p") or soup.select_one(".desc")
    synopsis = desc_el.get_text(strip=True) if desc_el else "Tidak ada sinopsis."

    # Parse download links jika halaman episode/batch
    download_data = parse_download_links(soup)

    return {
        "provider": "samehadaku",
        "title": title,
        "url": url,
        "thumbnail": thumb,
        "synopsis": synopsis,
        "downloads": download_data
    }

def parse_download_links(soup: BeautifulSoup) -> dict:
    """Parse link download per resolusi di Samehadaku"""
    downloads = {}
    dl_blocks = soup.select(".download-eps") or soup.select(".download-eps-links")

    for block in dl_blocks:
        for ul in block.select("ul"):
            for li in ul.select("li"):
                res_tag = li.select_one("strong") or li.select_one("b")
                res_name = res_tag.get_text(strip=True) if res_tag else "Unknown"
                links = []
                for a in li.select("span a") or li.select("a"):
                    server_name = a.get_text(strip=True)
                    href = a.get("href", "")
                    if href:
                        links.append({
                            "server": server_name,
                            "url": href
                        })
                if links:
                    downloads[res_name] = links

    return downloads

import os
import time
import subprocess
import tempfile
import shutil
from curl_cffi import requests

CURRENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHALLENGE_BIN = os.path.join(CURRENT_DIR, "bin", "challenge")
PROFILE_JSON = os.path.join(CURRENT_DIR, "profiles", "safari-26-ios.json")

PROXY_URL = os.environ.get("PROXY_URL", "").strip()
DEFAULT_RESIDENTIAL_PROXY = "http://hzvrsvul-rotate:je47prui48ga@p.webshare.io:80"

def get_proxy():
    if PROXY_URL:
        return PROXY_URL
    return DEFAULT_RESIDENTIAL_PROXY

def fetch_html(url: str, retries: int = 3, timeout: int = 15) -> str:
    """Fetch URL with curl_cffi Chrome impersonation + rotating proxy fallback"""
    proxy = get_proxy()
    proxies = {"http": proxy, "https": proxy} if proxy else None

    for attempt in range(retries):
        try:
            # 1. Coba request via curl_cffi impersonate
            r = requests.get(
                url,
                impersonate="chrome124",
                proxies=proxies,
                timeout=timeout,
                allow_redirects=True,
                headers={
                    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
                    "Referer": "https://www.google.com/"
                }
            )
            text = r.text
            if r.status_code == 200 and "Just a moment" not in text and "Attention Required" not in text:
                return text
            print(f"[fetch_html] Attempt {attempt+1} got status {r.status_code} for {url}")
        except Exception as e:
            print(f"[fetch_html] Attempt {attempt+1} exception: {e}")
        time.sleep(1)

    # 2. Jika gagal dan ada binary cfsolve challenge, coba bypass
    if os.path.exists(CHALLENGE_BIN) and os.path.exists(PROFILE_JSON):
        print(f"[fetch_html] Fallback to cfsolve for {url}")
        out_dir = tempfile.mkdtemp(prefix="cfsolve_")
        try:
            cmd = [CHALLENGE_BIN, "--page", url, out_dir, "--solve", "--fingerprint", PROFILE_JSON]
            if proxy:
                cmd.extend(["--proxy", proxy])
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=50)
            cleared_file = os.path.join(out_dir, "cleared.html")
            if os.path.exists(cleared_file):
                with open(cleared_file, "r", encoding="utf-8", errors="ignore") as f:
                    return f.read()
            page_file = os.path.join(out_dir, "page.html")
            if os.path.exists(page_file):
                with open(page_file, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                if "Just a moment" not in content and len(content) > 1000:
                    return content
        except Exception as ex:
            print(f"[fetch_html] cfsolve error: {ex}")
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)

    return ""

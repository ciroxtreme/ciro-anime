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

def fetch_html(url: str, retries: int = 2, timeout: int = 12) -> str:
    """Fetch URL with curl_cffi direct / Cloudflare WARP routing, auto-fallback to cfsolve on Cloudflare block"""
    for attempt in range(retries):
        try:
            r = requests.get(
                url,
                impersonate="chrome124",
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
            
            # Jika terkena 403 / Just a moment / Turnstile challenge, langsung break ke cfsolve!
            if r.status_code in (403, 503) or "Just a moment" in text or "challenges.cloudflare.com" in text or "Attention Required" in text:
                break
        except Exception as e:
            print(f"[fetch_html] Attempt {attempt+1} exception: {e}")
        time.sleep(0.5)

    # Fallback to cfsolve engine
    bin_target = None
    if os.path.exists(CHALLENGE_BIN) and os.access(CHALLENGE_BIN, os.X_OK):
        try:
            test_run = subprocess.run([CHALLENGE_BIN, "--help"], capture_output=True, timeout=2)
            if test_run.returncode == 0 or "Usage" in test_run.stdout.decode("utf-8", errors="ignore"):
                bin_target = CHALLENGE_BIN
        except Exception:
            pass

    if not bin_target:
        bin_target = shutil.which("cfsolve-cli") or shutil.which("challenge") or shutil.which("cfsolve")

    if bin_target and os.path.exists(PROFILE_JSON):
        print(f"[fetch_html] ⚡ Escalating to cfsolve engine ({bin_target}) for {url}")
        out_dir = tempfile.mkdtemp(prefix="cfsolve_")
        try:
            cmd = [bin_target, "--page", url, out_dir, "--solve", "--fingerprint", PROFILE_JSON]
            if PROXY_URL:
                cmd.extend(["--proxy", PROXY_URL])

            res = subprocess.run(cmd, capture_output=True, text=True, timeout=50)
            print(f"[cfsolve finished] returncode={res.returncode}, stdout len={len(res.stdout)}, stderr={res.stderr[-300:] if res.stderr else ''}")
            
            cleared_file = os.path.join(out_dir, "cleared.html")
            if os.path.exists(cleared_file):
                with open(cleared_file, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                if len(content) > 1000 and "Just a moment" not in content and "Attention Required" not in content:
                    print(f"[cfsolve success] cleared.html read ({len(content)} bytes)")
                    return content
            page_file = os.path.join(out_dir, "page.html")
            if os.path.exists(page_file):
                with open(page_file, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                if "Just a moment" not in content and len(content) > 1000:
                    print(f"[cfsolve success] page.html read ({len(content)} bytes)")
                    return content
            print(f"[cfsolve warning] neither cleared.html nor page.html contains valid content in {out_dir}")
        except Exception as ex:
            print(f"[fetch_html] cfsolve execution error: {ex}")
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)

    return ""

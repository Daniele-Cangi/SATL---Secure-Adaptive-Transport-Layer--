"""
Adapters per I/O reale:
- Browser-in-the-loop via Playwright (fingerprint TLS/JA3 "umano") se disponibile
- Fallback HTTPS/HTTP2 con requests+httpx se presenti
- Interfaccia comune: send_chunk(payload: bytes, url: str) -> bool
"""
from typing import Optional
import json, time

# browser adapter
try:
    from playwright.sync_api import sync_playwright  # type: ignore
    _HAS_PW=True
except Exception:
    _HAS_PW=False

# https adapter
try:
    import requests  # type: ignore
    _HAS_REQ=True
except Exception:
    _HAS_REQ=False

class AdaptiveSender:
    def __init__(self, target_url: str, user_agent: Optional[str]=None):
        self.url = target_url
        self.ua  = user_agent
        self._ctx = None
        if _HAS_PW:
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=True, args=["--disable-features=NetworkService"])
            self._context = self._browser.new_context(user_agent=self.ua) if self.ua else self._browser.new_context()
            self._page = self._context.new_page()
        elif _HAS_REQ:
            self._session = requests.Session()
            if self.ua: self._session.headers.update({"User-Agent": self.ua})
        else:
            self._session = None

    def send_chunk(self, payload: bytes) -> bool:
        if _HAS_PW:
            # Browser: usa fetch() dentro la pagina per preservare fingerprint
            data = payload.decode('latin1', errors='ignore')
            script = f"""
                await fetch("{self.url}", {{
                  method: "POST",
                  headers: {{ "Content-Type": "application/octet-stream" }},
                  body: new Blob([new TextEncoder().encode({json.dumps(data)})])
                }});
            """
            try:
                self._page.evaluate(script)
                return True
            except Exception:
                return False
        elif _HAS_REQ:
            try:
                print(f"Sending payload len={len(payload)} to {self.url}")
                r = self._session.post(self.url, data=payload, timeout=10)
                print(f"Response status: {r.status_code}")
                result = r.status_code//100 == 2
                print(f"Send result: {result}")
                return result
            except Exception as e:
                print(f"Exception in send_chunk: {e}")
                return False
        else:
            # Nessun adapter disponibile
            return False

    def close(self):
        try:
            if _HAS_PW:
                self._context.close(); self._browser.close(); self._pw.stop()
        except Exception:
            pass
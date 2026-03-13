import requests
import urllib3
from typing import Optional


class NSXClient:
    def __init__(self, host: str, username: str, password: str, verify_ssl: bool = True):
        if not host:
            raise ValueError("NSX_HOST is not configured")
        if not username:
            raise ValueError("NSX_USERNAME is not configured")
        if not password:
            raise ValueError("NSX_PASSWORD is not configured")

        self.base_url = host.rstrip("/")
        if not self.base_url.startswith("http"):
            self.base_url = f"https://{self.base_url}"

        self.session = requests.Session()
        self.session.auth = (username, password)
        self.session.verify = verify_ssl
        self.session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

        if not verify_ssl:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def get(self, path: str, params: Optional[dict] = None) -> dict:
        url = f"{self.base_url}{path}"
        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            return {
                "error": f"HTTP {e.response.status_code}",
                "message": str(e),
                "details": e.response.text[:2000] if e.response else "",
            }
        except requests.exceptions.ConnectionError as e:
            return {"error": "Connection failed", "message": str(e)}
        except requests.exceptions.Timeout:
            return {"error": "Timeout", "message": f"GET {path} timed out after 30s"}
        except Exception as e:
            return {"error": "Unexpected error", "message": str(e)}

"""
Page fetch proxy for Google AI Edge Gallery skill.
Fetches a URL server-side (no CORS restrictions) and returns clean text.

Endpoint: GET /fetch?url=https://example.com
Returns: JSON { "text": "clean page content..." }
         or  { "error": "reason" }
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
import json
import re
import os

PORT = int(os.environ.get("PORT", 8081))

# Max characters of text to return per page
MAX_TEXT_LENGTH = 1500

def extract_text(html):
    """Strip HTML down to clean readable text."""
    # Remove scripts, styles, nav, footer, header, ads
    html = re.sub(r'<(script|style|nav|footer|header|aside|noscript|iframe)[^>]*>[\s\S]*?</\1>', ' ', html, flags=re.IGNORECASE)
    # Remove all remaining tags
    html = re.sub(r'<[^>]+>', ' ', html)
    # Decode common HTML entities
    html = html.replace('&nbsp;', ' ') \
               .replace('&amp;', '&') \
               .replace('&lt;', '<') \
               .replace('&gt;', '>') \
               .replace('&quot;', '"') \
               .replace('&#39;', "'")
    # Collapse whitespace
    html = re.sub(r'\s+', ' ', html).strip()
    return html[:MAX_TEXT_LENGTH]


class ProxyHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        # Suppress default access logs
        pass

    def send_json(self, status, data):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        # Allow requests from any origin (needed for Edge Gallery webview)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        # Handle CORS preflight
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)

        # Health check
        if parsed.path == "/health":
            self.send_json(200, {"status": "ok"})
            return

        # Only handle /fetch
        if parsed.path != "/fetch":
            self.send_json(404, {"error": "Not found. Use /fetch?url=https://example.com"})
            return

        # Parse the url param
        params = parse_qs(parsed.query)
        target_url = params.get("url", [None])[0]

        if not target_url:
            self.send_json(400, {"error": "Missing url parameter"})
            return

        target_url = unquote(target_url)

        # Only allow http/https
        scheme = urlparse(target_url).scheme
        if scheme not in ("http", "https"):
            self.send_json(400, {"error": "Only http and https URLs are allowed"})
            return

        # Fetch the page
        try:
            req = Request(
                target_url,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; PrivacySearchSkill/1.0)",
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "en-US,en;q=0.9",
                }
            )
            with urlopen(req, timeout=8) as response:
                # Only process HTML pages
                content_type = response.headers.get("Content-Type", "")
                if "html" not in content_type.lower():
                    self.send_json(200, {"text": "(Non-HTML page, cannot extract text)", "url": target_url})
                    return

                raw = response.read(500_000)  # Max 500KB
                html = raw.decode("utf-8", errors="ignore")
                text = extract_text(html)

                if not text:
                    self.send_json(200, {"text": "(Page was empty or unreadable)", "url": target_url})
                    return

                self.send_json(200, {"text": text, "url": target_url})

        except HTTPError as e:
            self.send_json(200, {"text": "(Page returned HTTP " + str(e.code) + ", could not fetch)", "url": target_url})
        except URLError as e:
            self.send_json(200, {"text": "(Could not reach page: " + str(e.reason) + ")", "url": target_url})
        except Exception as e:
            self.send_json(200, {"text": "(Unexpected error fetching page: " + str(e) + ")", "url": target_url})


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), ProxyHandler)
    print(f"Proxy running on port {PORT}")
    server.serve_forever()

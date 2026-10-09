import hashlib
import ipaddress
import re
import socket
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit, urljoin
import feedparser
import urllib3
from bs4 import BeautifulSoup
from ..db import utcnow
from ..security import SecurityError

SOURCES = {
    "openai": {"name": "OpenAI News", "feed": "https://openai.com/news/rss.xml", "hosts": {"openai.com"}},
    "huggingface": {"name": "Hugging Face Blog", "feed": "https://huggingface.co/blog/feed.xml", "hosts": {"huggingface.co"}},
    "google_ai": {"name": "Google AI", "feed": "https://blog.google/technology/ai/rss/", "hosts": {"blog.google"}},
    "techcrunch": {"name": "TechCrunch AI", "feed": "https://techcrunch.com/category/artificial-intelligence/feed/", "hosts": {"techcrunch.com"}},
}
ALLOWED_HOSTS = set().union(*(s["hosts"] for s in SOURCES.values()))


def canonical_url(url):
    p = urlsplit(url)
    if p.scheme != "https" or p.hostname not in ALLOWED_HOSTS or p.username or p.password or p.port not in (None, 443):
        raise SecurityError("Only HTTPS URLs on configured news hosts are allowed")
    if any(ord(c) < 33 for c in url) or len(url) > 1500:
        raise SecurityError("Invalid URL")
    return urlunsplit(("https", p.hostname, p.path or "/", p.query, ""))


def public_ips(host):
    ips = list(dict.fromkeys(r[4][0] for r in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)))
    if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
        raise SecurityError("Private, loopback and reserved destinations are forbidden")
    return ips


class SafeHTTP:
    """Pin validated DNS IPs while preserving TLS SNI and hostname verification."""
    def get(self, url, max_bytes=2_000_000):
        for _ in range(4):
            url = canonical_url(url)
            p = urlsplit(url)
            addresses = public_ips(p.hostname)
            response = None
            pool = None
            last_error = None
            for address in addresses[:3]:
                pool = urllib3.HTTPSConnectionPool(address, port=443, server_hostname=p.hostname,
                                                   assert_hostname=p.hostname, cert_reqs="CERT_REQUIRED",
                                                   timeout=urllib3.Timeout(connect=5, read=12), retries=False)
                try:
                    response = pool.urlopen("GET", urlunsplit(("", "", p.path, p.query, "")),
                                            headers={"Host": p.hostname, "User-Agent": "DailyAINewsAgent/1.0 (+RSS reader)",
                                                     "Accept-Encoding": "identity"},
                                            redirect=False, preload_content=False)
                    break
                except urllib3.exceptions.HTTPError as exc:
                    last_error = exc
                    pool.close()
            if response is None:
                raise ValueError(f"News host unavailable ({type(last_error).__name__})")
            try:
                if response.status in (301, 302, 303, 307, 308):
                    url = urljoin(url, response.headers.get("Location", ""))
                    continue
                if response.status != 200:
                    raise ValueError(f"News source returned HTTP {response.status}")
                content_type = response.headers.get("Content-Type", "").lower()
                if not any(t in content_type for t in ("text/", "xml", "json")):
                    raise ValueError("Unsupported response content type")
                body = response.read(max_bytes + 1, decode_content=True)
                if len(body) > max_bytes:
                    raise ValueError("Response exceeds size limit")
                return body, url
            finally:
                response.close()
                pool.close()
        raise SecurityError("Too many redirects")


def strip_html(raw):
    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "form", "noscript", "iframe"]):
        tag.decompose()
    main = soup.find("article") or soup.find("main") or soup
    return re.sub(r"\s+", " ", main.get_text(" ", strip=True)).strip()


INJECTION_PATTERNS = re.compile(
    r"ignore.{0,30}(instructions|previous)|system\s*prompt|developer\s*message|"
    r"(send|reveal|exfiltrate).{0,40}(secret|api.?key|password)|忽略.{0,20}(指令|提示)|泄露.{0,15}(密钥|密码)", re.I)


class NewsService:
    def __init__(self, http=None):
        self.http = http or SafeHTTP()

    def search(self, query, source_ids, days):
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        candidates, errors = [], []
        terms = [t for t in re.split(r"[\s,，]+", query.casefold()) if t]
        for source_id in source_ids:
            source = SOURCES[source_id]
            try:
                raw, _ = self.http.get(source["feed"])
                parsed = feedparser.parse(raw)
                if not parsed.entries:
                    raise ValueError("Feed has no parseable entries")
                for entry in parsed.entries[:80]:
                    try:
                        url = canonical_url(entry.get("link", ""))
                        if urlsplit(url).hostname not in source["hosts"]:
                            continue
                        date_tuple = entry.get("published_parsed") or entry.get("updated_parsed")
                        # Undated entries cannot be presented as fresh news.
                        if not date_tuple:
                            continue
                        published = datetime(*date_tuple[:6], tzinfo=timezone.utc)
                        if published < cutoff or published > datetime.now(timezone.utc) + timedelta(hours=12):
                            continue
                        title = strip_html(entry.get("title", ""))[:300]
                        snippet = strip_html(entry.get("summary", ""))[:500]
                        score = sum(term in (title + " " + snippet).casefold() for term in terms)
                        candidates.append({"url": url, "title": title, "source": source_id,
                                           "published_at": published.isoformat(), "snippet": snippet, "score": score})
                    except (ValueError, TypeError):
                        continue
            except Exception as exc:
                errors.append({"source": source_id, "error": str(exc)[:160]})
        unique = {c["url"]: c for c in candidates}
        ranked = sorted(unique.values(), key=lambda c: (c["score"], c["published_at"]), reverse=True)[:24]
        return {"trust": "untrusted_news_data", "candidates": ranked, "source_errors": errors,
                "retrieved_at": utcnow(), "note": "Ranked by keyword match then publication time; not all items necessarily match."}

    def fetch(self, candidate):
        raw, final_url = self.http.get(candidate["url"])
        if urlsplit(final_url).hostname not in SOURCES[candidate["source"]]["hosts"]:
            raise SecurityError("Article redirected to a different source")
        text = strip_html(raw)[:18000]
        if len(text) < 200:
            raise ValueError("Article text too short; cannot verify a summary")
        return {**candidate, "url": final_url, "content": text, "fetched_at": utcnow(),
                "sha256": hashlib.sha256(text.encode()).hexdigest(),
                "injection_suspected": bool(INJECTION_PATTERNS.search(text))}

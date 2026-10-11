import hashlib
import ipaddress
import re
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
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
    "anthropic": {"name": "Anthropic", "feed": "https://www.anthropic.com/news/rss.xml", "hosts": {"www.anthropic.com", "anthropic.com"}, "requires_check": True},
    "meta_ai": {"name": "Meta AI", "feed": "https://ai.meta.com/blog/rss/", "hosts": {"ai.meta.com"}, "requires_check": True},
    "microsoft_research": {"name": "Microsoft Research", "feed": "https://www.microsoft.com/en-us/research/feed/", "hosts": {"www.microsoft.com"}, "requires_check": True},
    "arxiv": {"name": "arXiv cs.AI", "feed": "https://rss.arxiv.org/rss/cs.AI", "hosts": {"rss.arxiv.org", "arxiv.org"}, "requires_check": True},
}
ALLOWED_HOSTS = set().union(*(s["hosts"] for s in SOURCES.values()))


def normalize_public_url(url):
    """Syntax only; every network request separately validates and pins DNS."""
    if any(ord(c) < 33 for c in url) or "\\" in url or len(url) > 1500:
        raise SecurityError("Invalid URL")
    try:
        p = urlsplit(url)
        host = (p.hostname or "").encode("idna").decode("ascii").lower().rstrip(".")
        if p.scheme != "https" or not host or p.username is not None or p.password is not None or p.port not in (None, 443):
            raise ValueError()
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if (address and not public_address(address)) or host in {"localhost", "metadata.google.internal"} or host.endswith((".localhost", ".local", ".internal")):
            raise SecurityError("Private, local and metadata destinations are forbidden")
        netloc = f"[{host}]" if ":" in host else host
        return urlunsplit(("https", netloc, p.path or "/", p.query, ""))
    except (ValueError, UnicodeError) as exc:
        raise SecurityError("Only public HTTPS URLs without credentials on port 443 are allowed") from exc


def canonical_url(url):
    normalized = normalize_public_url(url)
    if urlsplit(normalized).hostname not in ALLOWED_HOSTS:
        raise SecurityError("Only HTTPS URLs on configured news hosts are allowed")
    return normalized


def public_ips(host):
    ips = list(dict.fromkeys(r[4][0] for r in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)))
    if not ips or any(not public_address(ipaddress.ip_address(ip)) for ip in ips):
        raise SecurityError("Private, loopback and reserved destinations are forbidden")
    return ips


def public_address(address):
    # Azure's WireServer is globally numbered but is an infrastructure metadata endpoint.
    if not address.is_global or str(address) == "168.63.129.16":
        return False
    if address.version == 6:
        if address in ipaddress.ip_network("64:ff9b::/96") or address in ipaddress.ip_network("64:ff9b:1::/48"):
            return False
        embedded = address.ipv4_mapped or address.sixtofour
        if embedded and not public_address(embedded):
            return False
        if address.teredo:
            return all(public_address(v) for v in address.teredo)
    return True


_DNS_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="news-dns")
_DNS_SLOTS = threading.BoundedSemaphore(4)


def bounded_dns(host, timeout):
    if not _DNS_SLOTS.acquire(timeout=max(0, timeout)):
        raise ValueError("DNS resolver busy / timeout")
    started = time.monotonic()
    future = _DNS_POOL.submit(public_ips, host)
    future.add_done_callback(lambda _: _DNS_SLOTS.release())
    try:
        return future.result(timeout=max(0, timeout - (time.monotonic() - started)))
    except FutureTimeout as exc:
        raise ValueError("DNS resolution timeout") from exc


class SafeHTTP:
    """Pin validated DNS IPs while preserving TLS SNI and hostname verification."""
    def get(self, url, max_bytes=2_000_000, timeout=15, public=False):
        deadline = time.monotonic() + timeout
        validate = normalize_public_url if public else canonical_url
        def remaining():
            value = deadline - time.monotonic()
            if value <= 0:
                raise ValueError("News request total timeout")
            return value
        for _ in range(4):
            url = validate(url)
            p = urlsplit(url)
            addresses = bounded_dns(p.hostname, min(3, remaining()))
            response = None
            pool = None
            last_error = None
            for address in addresses[:3]:
                pool = urllib3.HTTPSConnectionPool(address, port=443, server_hostname=p.hostname,
                                                   assert_hostname=p.hostname, cert_reqs="CERT_REQUIRED",
                                                   timeout=urllib3.Timeout(total=remaining(), connect=min(4, remaining()), read=min(4, remaining())), retries=False)
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
                    location = response.headers.get("Location")
                    if not location:
                        raise ValueError("Redirect missing Location")
                    url = validate(urljoin(url, location))
                    continue
                if response.status != 200:
                    raise ValueError(f"News source returned HTTP {response.status}")
                content_type = response.headers.get("Content-Type", "").lower()
                if not any(t in content_type for t in ("text/", "xml", "json")):
                    raise ValueError("Unsupported response content type")
                if response.headers.get("Content-Encoding", "identity").lower() not in ("", "identity"):
                    raise ValueError("Compressed responses are not accepted")
                size = response.headers.get("Content-Length")
                if size and (not size.isdigit() or int(size) > max_bytes):
                    raise ValueError("Response exceeds size limit")
                body = bytearray()
                while True:
                    # read1 performs a single socket read: slow streams cannot extend the total deadline.
                    conn = response.connection
                    if conn and conn.sock:
                        conn.sock.settimeout(min(4, remaining()))
                    remaining()
                    chunk = response.read1(min(65536, max_bytes + 1 - len(body)), decode_content=False)
                    remaining()
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        raise ValueError("Response exceeds size limit")
                    if not chunk:
                        return bytes(body), url
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
        self._cache = {}
        self._cache_lock = threading.Lock()

    def feed(self, source, timeout=15):
        url = source["feed"]
        # A URL is fetched at most once per minute; successful AND failed checks are cached.
        with self._cache_lock:
            cached = self._cache.get(url)
            if cached and time.monotonic() - cached[0] < 60:
                if cached[2]:
                    raise ValueError(cached[2])
                if cached[1] is None:
                    raise ValueError("Source check already in progress; retry shortly")
                return cached[1]
            if len(self._cache) >= 128:
                self._cache = {k: v for k, v in self._cache.items() if time.monotonic() - v[0] < 60}
                if len(self._cache) >= 128:
                    raise ValueError("Feed request capacity reached; retry shortly")
            self._cache[url] = (time.monotonic(), None, None)
        try:
            raw, final = self.http.get(url, public=bool(source.get("custom")), timeout=timeout)
            parsed = feedparser.parse(raw)
            if parsed.bozo or not parsed.entries:
                raise ValueError("Invalid RSS/Atom XML or no parseable entries")
            valid = self.entries(parsed, source, days=None)
            if not valid:
                raise ValueError("Feed has no valid titled, dated HTTPS entries")
            value = (valid, final)
            with self._cache_lock:
                self._cache[url] = (time.monotonic(), value, None)
            return value
        except Exception as exc:
            # Network library exceptions may contain URLs with credentials; expose controlled diagnostics.
            error = str(exc)[:160] if isinstance(exc, ValueError) else f"Source unavailable ({type(exc).__name__}; network timeout or connection failure)"
            with self._cache_lock:
                self._cache[url] = (time.monotonic(), None, error)
            raise ValueError(error) from exc

    def entries(self, parsed, source, days):
        result = []
        now = datetime.now(timezone.utc)
        for entry in parsed.entries[:80]:
            try:
                link = entry.get("link", "")
                # arXiv's official RSS publishes legacy HTTP links; normalize only known arXiv links.
                if urlsplit(link).scheme == "http" and urlsplit(link).hostname == "arxiv.org" and source.get("feed") == SOURCES["arxiv"]["feed"]:
                    link = "https:" + link[5:]
                url = normalize_public_url(link) if source.get("custom") else canonical_url(link)
                if not source.get("custom") and urlsplit(url).hostname not in source["hosts"]:
                    continue
                date_tuple = entry.get("published_parsed") or entry.get("updated_parsed")
                if not date_tuple:
                    continue
                published = datetime(*date_tuple[:6], tzinfo=timezone.utc)
                if published > now + timedelta(hours=12) or (days is not None and published < now - timedelta(days=days)):
                    continue
                title = strip_html(entry.get("title", ""))[:300]
                snippet = strip_html(entry.get("summary", ""))[:500]
                if not title or INJECTION_PATTERNS.search(title + " " + snippet):
                    continue
                result.append({"url": url, "title": title, "published_at": published.isoformat(), "snippet": snippet})
            except (ValueError, TypeError):
                continue
        return result

    def search(self, query, source_ids, days, *, definitions=None, watch_objects=(), topics=(), budget_seconds=35, status_callback=None):
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        candidates, errors = [], []
        terms = list(dict.fromkeys([t for t in re.split(r"[\s,，]+", query.casefold()) if t] + [t.casefold() for t in topics]))
        deadline = time.monotonic() + budget_seconds
        definitions = definitions if definitions is not None else SOURCES
        for source_id in source_ids:
            source = definitions.get(source_id)
            try:
                if not source:
                    raise ValueError("Source disabled, unverified, deleted or not owned by this user")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ValueError("Search time budget exhausted; source not requested")
                entries, _ = self.feed(source, timeout=min(10, remaining))
                if status_callback:
                    status_callback(source_id, True, None)
                for item in entries:
                    if datetime.fromisoformat(item["published_at"]) < cutoff:
                        continue
                    text = item["title"] + " " + item["snippet"]
                    matched = [o["name"] for o in watch_objects if any(matches(text, alias) for alias in [o["name"], *o["aliases"]])]
                    score = sum(matches(text, term) for term in terms) + 3 * len(matched)
                    if not score:
                        continue
                    candidates.append({**item, "source": source_id, "source_name": source["name"], "score": score,
                                       "matched_objects": matched, "custom": bool(source.get("custom"))})
            except Exception as exc:
                error = str(exc)[:160]
                errors.append({"source": source_id, "error": error})
                if source and status_callback and "budget exhausted" not in error:
                    status_callback(source_id, False, error)
        unique = {c["url"]: c for c in candidates}
        ranked = sorted(unique.values(), key=lambda c: (c["score"], c["published_at"]), reverse=True)[:24]
        return {"trust": "untrusted_news_data", "candidates": ranked, "source_errors": errors,
                "retrieved_at": utcnow(), "unmatched_objects": [o["name"] for o in watch_objects if not any(o["name"] in c["matched_objects"] for c in unique.values())],
                "note": "No relevant updates found." if not ranked else "Keyword/alias matches are retrieval candidates, not verified article facts. Fetch original text before summarizing."}

    def fetch(self, candidate):
        raw, final_url = self.http.get(candidate["url"], public=bool(candidate.get("custom")))
        if not candidate.get("custom") and urlsplit(final_url).hostname not in SOURCES[candidate["source"]]["hosts"]:
            raise SecurityError("Article redirected to a different source")
        text = strip_html(raw)[:18000]
        if len(text) < 200:
            raise ValueError("Article text too short; cannot verify a summary")
        return {**candidate, "url": final_url, "content": text, "fetched_at": utcnow(),
                "sha256": hashlib.sha256(text.encode()).hexdigest(),
                "injection_suspected": bool(INJECTION_PATTERNS.search(text))}


def matches(text, term):
    # Literal Unicode phrases; prevent AI matching paid, or vLLM matching vLLMish.
    return bool(re.search(r"(?<!\w)" + re.escape(term.casefold()) + r"(?!\w)", text.casefold())) if term.isascii() else term.casefold() in text.casefold()

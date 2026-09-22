from flask import Flask, render_template, request
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import json
import re
import time
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, template_folder=os.path.join(BASE_DIR, 'templates'))

app.config['TEMPLATES_AUTO_RELOAD'] = False

ARTICLES_PER_PAGE = 20
CACHE_TTL = 600
REQUEST_TIMEOUT = 8
ARCHIVE_MONTHS_BACK = 6   # bump this up — JSON extraction is fast, so we can afford more

_cache = {"data": None, "ts": 0}

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

TARGET_DATE = datetime(2022, 1, 1).date()


def extract_articles_from_json(html):
    """Pull article entries out of The Verge's embedded JSON payloads."""
    articles = []

    # The Verge embeds data as __NEXT_DATA__ or in inline JSON
    for script in BeautifulSoup(html, 'html.parser').find_all('script'):
        text = script.string
        if not text:
            continue
        if 'application/ld+json' in (script.get('type') or ''):
            try:
                data = json.loads(text)
                articles.extend(_walk_jsonld(data))
            except Exception:
                pass
        elif script.get('id') in ('__NEXT_DATA__',):
            try:
                data = json.loads(text)
                articles.extend(_walk_next_data(data))
            except Exception:
                pass

    return articles


def _walk_jsonld(node):
    """Extract Article items from JSON-LD."""
    out = []
    if isinstance(node, dict):
        t = node.get('@type')
        if t in ('NewsArticle', 'Article', 'BlogPosting'):
            title = node.get('headline') or node.get('name')
            url = node.get('url') or (node.get('mainEntityOfPage') or {}).get('@id')
            date = node.get('datePublished') or node.get('dateModified')
            if title and url and date:
                try:
                    d = datetime.fromisoformat(date.replace('Z', '+00:00')).date()
                    if d >= TARGET_DATE:
                        out.append({'title': title.strip(), 'link': url, 'date': d})
                except Exception:
                    pass
        for v in node.values():
            out.extend(_walk_jsonld(v))
    elif isinstance(node, list):
        for v in node:
            out.extend(_walk_jsonld(v))
    return out


def _walk_next_data(node):
    """Extract article entries from __NEXT_DATA__ blobs."""
    out = []
    if isinstance(node, dict):
        # Heuristic: entries with title + href + publishedAt-like keys
        title = node.get('title') or node.get('headline')
        url = node.get('url') or node.get('href') or node.get('permalink')
        date = (node.get('datePublished') or node.get('publishedAt')
                or node.get('date') or node.get('published'))
        if title and url and date and isinstance(title, str) and len(title) > 15:
            try:
                if isinstance(date, (int, float)):
                    d = datetime.fromtimestamp(date).date()
                else:
                    d = datetime.fromisoformat(str(date).replace('Z', '+00:00')).date()
                if d >= TARGET_DATE:
                    if not url.startswith('http'):
                        url = f"https://www.theverge.com{url}"
                    out.append({'title': title.strip(), 'link': url, 'date': d})
            except Exception:
                pass
        for v in node.values():
            out.extend(_walk_next_data(v))
    elif isinstance(node, list):
        for v in node:
            out.extend(_walk_next_data(v))
    return out


def extract_from_html_fallback(html, page_url):
    """Fallback: find <h2>/<h3> links with proper date tags."""
    out = []
    soup = BeautifulSoup(html, 'html.parser')
    for a in soup.find_all('a', href=True):
        href = a['href']
        if not re.search(r'/\d{4}/\d{1,2}/\d{1,2}/', href):
            continue
        title_el = a.find(['h1', 'h2', 'h3', 'h4'])
        title = (title_el or a).get_text().strip()
        if not title or len(title) < 20:
            continue
        url = href if href.startswith('http') else f"https://www.theverge.com{href}"
        date_match = re.search(r'/(\d{4})/(\d{1,2})/(\d{1,2})/', url)
        if not date_match:
            continue
        try:
            y, m, d = map(int, date_match.groups())
            date = datetime(y, m, d).date()
            if date >= TARGET_DATE:
                out.append({'title': title, 'link': url, 'date': date})
        except Exception:
            pass
    return out


def scrape_url(url, articles):
    try:
        r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        html = r.text

        found = extract_articles_from_json(html)
        if not found:
            found = extract_from_html_fallback(html, url)

        for a in found:
            if not any(x['link'] == a['link'] for x in articles):
                articles.append(a)
    except Exception as e:
        print(f"Error fetching {url}: {e}")


def scrape_the_verge():
    articles = []
    scrape_url("https://www.theverge.com", articles)

    current = datetime.now()
    first_month = (current.replace(day=1)
                   - timedelta(days=30 * (ARCHIVE_MONTHS_BACK - 1))).replace(day=1)

    d = first_month
    while d <= current:
        scrape_url(f"https://www.theverge.com/archives/{d.year}/{d.month}", articles)
        d = datetime(d.year + 1, 1, 1) if d.month == 12 else datetime(d.year, d.month + 1, 1)

    articles.sort(key=lambda x: x['date'], reverse=True)
    print(f"Scraped {len(articles)} articles")
    return articles


def get_articles_cached():
    now = time.time()
    if _cache["data"] is None or (now - _cache["ts"]) > CACHE_TTL:
        _cache["data"] = scrape_the_verge()
        _cache["ts"] = now
    return _cache["data"]


@app.route('/')
def index():
    try:
        page = max(1, int(request.args.get('page', 1)))
    except (ValueError, TypeError):
        page = 1

    articles = get_articles_cached()
    total = len(articles)
    total_pages = max(1, (total + ARTICLES_PER_PAGE - 1) // ARTICLES_PER_PAGE)
    if page > total_pages:
        page = total_pages

    start = (page - 1) * ARTICLES_PER_PAGE
    return render_template(
        'index.html',
        articles=articles[start:start + ARTICLES_PER_PAGE],
        page=page,
        total_pages=total_pages,
        total_articles=total,
        per_page=ARTICLES_PER_PAGE,
    )


@app.route('/debug')
def debug():
    articles = get_articles_cached()
    return {
        'total': len(articles),
        'sample': [
            {'title': a['title'][:80], 'date': a['date'].strftime('%Y-%m-%d')}
            for a in articles[:10]
        ],
    }


if __name__ == '__main__':
    app.run(debug=True, port=5001)
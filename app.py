from flask import Flask, render_template, request, jsonify
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from dateutil import parser
import re
import time
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, template_folder=os.path.join(BASE_DIR, 'templates'))

app.config['TEMPLATES_AUTO_RELOAD'] = False
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=5)

# ---------- Config ----------
ARTICLES_PER_PAGE = 20
CACHE_TTL = 600            # 10 minutes
REQUEST_TIMEOUT = 8
ARCHIVE_MONTHS_BACK = 3    # keep it low so Vercel doesn't 504

_cache = {"data": None, "ts": 0}


def parse_date_string(date_str):
    try:
        current_year = datetime.now().year
        return parser.parse(f"{date_str} {current_year}").date()
    except Exception:
        try:
            return parser.parse(date_str).date()
        except Exception:
            return None


def scrape_page(url, target_date, articles):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                      '(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    try:
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        article_links = soup.find_all('a', href=True)

        for link in article_links:
            try:
                href = link['href']
                if any(skip in href.lower() for skip in [
                    '/login', '/signup', '/about', '/contact',
                    '/privacy', '/terms', '#', 'javascript:', 'mailto:'
                ]):
                    continue

                title = link.get_text().strip()
                if not title or len(title) < 10:
                    continue

                article_url = href
                if not article_url.startswith('http'):
                    article_url = f"https://www.theverge.com{article_url}"

                date = None
                date_match = re.search(r'/(\d{4})/(\d{1,2})/(\d{1,2})/', article_url)
                if date_match:
                    try:
                        y, m, d = map(int, date_match.groups())
                        date = datetime(y, m, d).date()
                    except Exception:
                        pass

                parent = link.find_parent(['div', 'article'])
                if not parent:
                    continue

                if not date:
                    time_elem = parent.find('time')
                    if time_elem and time_elem.get('datetime'):
                        try:
                            date = parser.parse(time_elem['datetime']).date()
                        except Exception:
                            pass

                if not date:
                    for elem in parent.find_all(['span', 'div', 'time']):
                        text = elem.get_text().strip().upper()
                        if any(m in text for m in [
                            'JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN',
                            'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'
                        ]):
                            date = parse_date_string(elem.get_text().strip())
                            if date:
                                break

                if date and date >= target_date.date():
                    if not any(a['link'] == article_url for a in articles):
                        articles.append({'title': title, 'link': article_url, 'date': date})
            except Exception as e:
                print(f"Error processing article: {e}")
                continue
    except Exception as e:
        print(f"Error fetching page {url}: {e}")


def scrape_the_verge():
    articles = []
    target_date = datetime(2022, 1, 1)

    try:
        scrape_page("https://www.theverge.com", target_date, articles)

        current_date = datetime.now()
        first_month = (current_date.replace(day=1)
                       - timedelta(days=30 * (ARCHIVE_MONTHS_BACK - 1))).replace(day=1)

        archive_date = first_month
        while archive_date <= current_date:
            archive_url = (f"https://www.theverge.com/archives/"
                           f"{archive_date.year}/{archive_date.month}")
            scrape_page(archive_url, target_date, articles)

            if archive_date.month == 12:
                archive_date = datetime(archive_date.year + 1, 1, 1)
            else:
                archive_date = datetime(archive_date.year, archive_date.month + 1, 1)

        articles.sort(
            key=lambda x: x['date'] if x['date'] else datetime.min.date(),
            reverse=True
        )
        print(f"Scraped {len(articles)} articles")
        return articles
    except Exception as e:
        print(f"Error fetching The Verge: {e}")
        return []


def get_articles_cached():
    now = time.time()
    if _cache["data"] is None or (now - _cache["ts"]) > CACHE_TTL:
        _cache["data"] = scrape_the_verge()
        _cache["ts"] = now
    return _cache["data"]


# ---------- Routes ----------

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
    page_articles = articles[start:start + ARTICLES_PER_PAGE]

    return render_template(
        'index.html',
        articles=page_articles,
        page=page,
        total_pages=total_pages,
        total_articles=total,
        per_page=ARTICLES_PER_PAGE,
    )


@app.route('/api/articles')
def api_articles():
    try:
        page = max(1, int(request.args.get('page', 1)))
        per_page = min(100, max(1, int(request.args.get('per_page', ARTICLES_PER_PAGE))))
    except (ValueError, TypeError):
        page, per_page = 1, ARTICLES_PER_PAGE

    articles = get_articles_cached()
    total = len(articles)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, total_pages)

    start = (page - 1) * per_page
    page_articles = articles[start:start + per_page]

    return jsonify({
        'page': page,
        'per_page': per_page,
        'total': total,
        'total_pages': total_pages,
        'articles': [
            {'title': a['title'], 'link': a['link'], 'date': a['date'].strftime('%Y-%m-%d')}
            for a in page_articles
        ],
    })


if __name__ == '__main__':
    app.run(debug=True)
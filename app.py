from flask import Flask, render_template, request, jsonify
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from dateutil import parser
import re
import time

app = Flask(__name__)

# Add Vercel-specific configuration
app.config['TEMPLATES_AUTO_RELOAD'] = False
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=5)

def parse_date_string(date_str):
    try:
        # Try parsing with current year
        current_year = datetime.now().year
        date_str = f"{date_str} {current_year}"
        date = parser.parse(date_str)
        return date.date() 
    except:
        try:
            date = parser.parse(date_str)
            return date.date() 
        except:
            return None

def scrape_page(url, target_date, articles):

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # get article links
        article_links = soup.find_all('a', href=True)
        
        for link in article_links:
            try:
                # avoid navigation and footer links
                if any(skip in link['href'].lower() for skip in ['/login', '/signup', '/about', '/contact', '/privacy', '/terms', '#', 'javascript:', 'mailto:']):
                    continue
                    
                # title of article
                title = link.get_text().strip()
                if not title or len(title) < 10:  # skip unnecessary text
                    continue
                
                # Get the link
                article_url = link['href']
                if not article_url.startswith('http'):
                    article_url = f"https://www.theverge.com{article_url}"
                
                #extract date from url
                date = None
                date_match = re.search(r'/(\d{4})/(\d{1,2})/(\d{1,2})/', article_url)
                if date_match:
                    try:
                        year, month, day = map(int, date_match.groups())
                        date = datetime(year, month, day).date()  # Convert to date object
                    except:
                        pass
                
                # Find the parent container
                parent = link.find_parent(['div', 'article'])
                if not parent:
                    continue
                
                # if no date from URL, look for date in the HTML
                if not date:
                    # Try to find timestamp attribute first
                    time_elem = parent.find('time')
                    if time_elem and time_elem.get('datetime'):
                        try:
                            date = parser.parse(time_elem['datetime']).date()  # Convert to date object
                        except:
                            pass
                    
                    # find date in text
                    if not date:
                        for elem in parent.find_all(['span', 'div', 'time']):
                            text = elem.get_text().strip().upper()
                            if any(month in text for month in ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']):
                                date = parse_date_string(elem.get_text().strip())
                                if date:
                                    break
                
                # proceed if we have a valid date from 2022 onwards
                if date and date >= target_date.date():  # Convert target_date to date for comparison
                    
                    # Check if article is already added (avoid duplicates)
                    if not any(a['link'] == article_url for a in articles):
                        try:
                            formatted_date = date
                            if isinstance(date, datetime):
                                formatted_date = date.date()
                            articles.append({
                                'title': title,
                                'link': article_url,
                                'date': formatted_date,
                            })
                            print(f"Added article from {formatted_date.strftime('%Y-%m-%d')}: {title}")
                        except Exception as e:
                            print(f"Error formatting date for article: {str(e)}")
                            continue
            
            except Exception as e:
                print(f"Error processing article: {str(e)}")
                continue
    except Exception as e:
        print(f"Error fetching page {url}: {str(e)}")

def scrape_the_verge():
    articles = []
    target_date = datetime(2022, 1, 1)
    print(f"Fetching articles from {target_date.strftime('%B %d, %Y')} onwards...")
    
    try:
        # scrape the homepage
        print("\nScraping homepage...")
        scrape_page("https://www.theverge.com", target_date, articles)
        
        # scrape archive pages from 2022
        current_date = datetime.now()
        archive_date = target_date
        
        while archive_date <= current_date:
            archive_url = f"https://www.theverge.com/archives/{archive_date.year}/{archive_date.month}"
            print(f"\nScraping archive for {archive_date.strftime('%B %Y')}...")
            scrape_page(archive_url, target_date, articles)
            
            # subsequent months
            if archive_date.month == 12:
                archive_date = datetime(archive_date.year + 1, 1, 1)
            else:
                archive_date = datetime(archive_date.year, archive_date.month + 1, 1)
        
        # Sort articles by date in descending order (newest first)
        articles.sort(key=lambda x: x['date'] if x['date'] else datetime.min.date(), reverse=True)
        
        # Print debug information
        print(f"\nFound {len(articles)} articles from {target_date.strftime('%B %d, %Y')} onwards")
        if len(articles) == 0:
            print("No articles found.")
        else:
            print("\nFirst 5 articles after sorting:")
            for i, article in enumerate(articles[:5]):
                print(f"{i+1}. {article['date'].strftime('%Y-%m-%d')} - {article['title']}")
        return articles
        
    except Exception as e:
        print(f"Error fetching The Verge website: {str(e)}")
        return []

@app.route('/')
def index():
    try:
        print("Starting to fetch articles...")
        articles = scrape_the_verge()
        print(f"Rendering template with {len(articles)} articles")
        return render_template('index.html', articles=articles)
    except Exception as e:
        print(f"Error in index route: {str(e)}")
        return render_template('index.html', articles=[], error=str(e)) 
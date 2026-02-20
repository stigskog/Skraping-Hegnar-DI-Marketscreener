import requests
from bs4 import BeautifulSoup
import json
import re
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)

COMMON_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36',
    'Accept': '*/*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Cache-Control': 'no-cache',
}


def scrape_finansavisen(max_pages=3, page_size=50):
    """Scrape news from Finansavisen API. Returns list of article dicts."""
    articles = []
    for page in range(max_pages):
        offset = page * page_size
        url = f'https://ws.finansavisen.no/context/market-news?source=all&limit={page_size}&offset={offset}'
        headers = {
            **COMMON_HEADERS,
            'Origin': 'https://www.finansavisen.no',
            'Referer': 'https://www.finansavisen.no/',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-site',
        }
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            raw_articles = data.get('articles', [])
            if not raw_articles:
                break
            for art in raw_articles:
                ticker_tags = art.get('tickerTags', [])
                tickers = []
                for t in ticker_tags:
                    tickers.append({
                        'symbol': t.get('symbol', ''),
                        'name': t.get('name', ''),
                        'country': t.get('countryCode', ''),
                    })
                published = art.get('published', '')
                try:
                    pub_dt = datetime.fromisoformat(published.replace('Z', '+00:00'))
                    time_str = pub_dt.strftime('%H:%M')
                except:
                    time_str = ''
                articles.append({
                    'source': 'Finansavisen',
                    'title': art.get('title', ''),
                    'summary': art.get('preamble', ''),
                    'published': published,
                    'time': time_str,
                    'category': art.get('category', ''),
                    'type': art.get('type', ''),
                    'tickers': tickers,
                    'url': art.get('url', ''),
                    'is_paid': art.get('isPaid', False),
                })
            logger.info(f"Finansavisen page {page+1}: {len(raw_articles)} articles")
        except Exception as e:
            logger.error(f"Finansavisen page {page+1} error: {e}")
            break
    return articles


def scrape_di(max_pages=3):
    """Scrape news from Dagens Industri (DI.se). Returns list of article dicts."""
    articles = []
    for page in range(1, max_pages + 1):
        url = f'https://www.di.se/live-by-page/?page={page}'
        headers = {
            **COMMON_HEADERS,
            'Referer': 'https://www.di.se/live/',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
        }
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')
            news_items = soup.find_all('article', class_='news-item')
            if not news_items:
                break
            for item in news_items:
                title_el = item.find('h2', class_='news-item__heading')
                title = title_el.get_text(strip=True) if title_el else ''
                text_el = item.find('p', class_='news-item__text')
                summary = text_el.get_text(strip=True) if text_el else ''
                time_el = item.find('time', class_='news-item-left__time')
                time_str = time_el.get_text(strip=True) if time_el else ''
                datetime_attr = time_el.get('datetime', '') if time_el else ''
                vignette_el = item.find('label', class_='news-item-vignette')
                category = vignette_el.get_text(strip=True) if vignette_el else ''
                byline_els = item.find_all('p', class_='news-item-left__byline')
                bylines = [b.get_text(strip=True) for b in byline_els]
                link_el = item.find('a', href=True)
                link = link_el['href'] if link_el else ''
                if link and not link.startswith('http'):
                    link = 'https://www.di.se' + link
                articles.append({
                    'source': 'DI',
                    'title': title,
                    'summary': summary,
                    'published': datetime_attr,
                    'time': time_str,
                    'category': category,
                    'type': 'di',
                    'tickers': [],
                    'url': link,
                    'bylines': bylines,
                })
            logger.info(f"DI page {page}: {len(news_items)} articles")
        except Exception as e:
            logger.error(f"DI page {page} error: {e}")
            break
    return articles


def scrape_marketscreener(max_pages=1):
    """Scrape news from MarketScreener. Returns list of article dicts."""
    articles = []
    url = 'https://www.marketscreener.com/news/'
    headers = {
        **COMMON_HEADERS,
        'Referer': 'https://www.marketscreener.com/',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    }
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'lxml')
        # MarketScreener has news items in table rows or article blocks
        news_rows = soup.select('table.table--hover tbody tr')
        if not news_rows:
            # Fallback: try article elements
            news_rows = soup.select('article, .news-item, .article-item')
        for row in news_rows:
            link_el = row.find('a', href=True)
            if not link_el:
                continue
            title = link_el.get_text(strip=True)
            if not title or len(title) < 10:
                continue
            href = link_el.get('href', '')
            if href and not href.startswith('http'):
                href = 'https://www.marketscreener.com' + href
            time_el = row.find('time') or row.find(class_=re.compile(r'time|date|hour'))
            time_str = ''
            datetime_attr = ''
            if time_el:
                time_str = time_el.get_text(strip=True)
                datetime_attr = time_el.get('datetime', '')
            # Try to find text/summary
            td_els = row.find_all('td')
            summary = ''
            source_name = 'MarketScreener'
            for td in td_els:
                txt = td.get_text(strip=True)
                if len(txt) > len(summary) and txt != title:
                    summary = txt
            articles.append({
                'source': source_name,
                'title': title,
                'summary': summary,
                'published': datetime_attr,
                'time': time_str,
                'category': '',
                'type': 'marketscreener',
                'tickers': [],
                'url': href,
            })
        logger.info(f"MarketScreener: {len(articles)} articles")
    except Exception as e:
        logger.error(f"MarketScreener error: {e}")
    return articles


def scrape_all_sources(config):
    """Scrape all enabled sources based on config. Returns combined article list."""
    all_articles = []
    sources = config.get('sources', {})

    if sources.get('finansavisen', {}).get('enabled', True):
        max_p = sources['finansavisen'].get('max_pages', 3)
        page_size = sources['finansavisen'].get('page_size', 50)
        arts = scrape_finansavisen(max_pages=max_p, page_size=page_size)
        all_articles.extend(arts)

    if sources.get('di', {}).get('enabled', True):
        max_p = sources['di'].get('max_pages', 3)
        arts = scrape_di(max_pages=max_p)
        all_articles.extend(arts)

    if sources.get('marketscreener', {}).get('enabled', True):
        max_p = sources['marketscreener'].get('max_pages', 1)
        arts = scrape_marketscreener(max_pages=max_p)
        all_articles.extend(arts)

    return all_articles


def scrape_single_source(source_name, config):
    """Scrape a single source by name."""
    sources = config.get('sources', {})
    src = sources.get(source_name, {})
    if source_name == 'finansavisen':
        return scrape_finansavisen(
            max_pages=src.get('max_pages', 3),
            page_size=src.get('page_size', 50)
        )
    elif source_name == 'di':
        return scrape_di(max_pages=src.get('max_pages', 3))
    elif source_name == 'marketscreener':
        return scrape_marketscreener(max_pages=src.get('max_pages', 1))
    return []

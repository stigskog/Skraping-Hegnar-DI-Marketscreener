import requests
from bs4 import BeautifulSoup
import json
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import logging

OSLO_TZ = ZoneInfo('Europe/Oslo')

try:
    from curl_cffi import requests as curl_requests
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False

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
                    # Convert to Oslo timezone for correct local time
                    pub_dt = pub_dt.astimezone(OSLO_TZ)
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


def scrape_advfn(max_pages=1):
    """Scrape news from ADVFN newspaper. Returns list of article dicts."""
    articles = []
    for page in range(1, max_pages + 1):
        url = 'https://uk.advfn.com/newspaper' if page == 1 else f'https://uk.advfn.com/newspaper/page/{page}'
        headers = {
            **COMMON_HEADERS,
            'Referer': 'https://uk.advfn.com/',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        }
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')
            article_divs = soup.find_all('div', class_='article')
            if not article_divs:
                break
            for art in article_divs:
                h3 = art.find('h3')
                link = h3.find('a', href=True) if h3 else None
                if not link:
                    continue
                title = link.get_text(strip=True)
                if not title or len(title) < 10:
                    continue
                href = link.get('href', '')

                # Date from div with class containing 'date'
                date_el = art.find(class_=lambda x: x and 'date' in x.lower())
                date_text = date_el.get_text(strip=True) if date_el else ''
                time_str = ''
                published = ''
                if date_text:
                    # Format: "27 Feb 2026 @ 15:30"
                    try:
                        dt = datetime.strptime(date_text, '%d %b %Y @ %H:%M')
                        time_str = dt.strftime('%H:%M')
                        published = dt.isoformat()
                    except:
                        published = date_text

                # Summary from first <p> in article
                p_el = art.find('p')
                summary = p_el.get_text(strip=True)[:200] if p_el else ''

                articles.append({
                    'source': 'ADVFN',
                    'title': title,
                    'summary': summary,
                    'published': published,
                    'time': time_str,
                    'category': '',
                    'type': 'advfn',
                    'tickers': [],
                    'url': href,
                })
            logger.info(f"ADVFN page {page}: {len(article_divs)} articles")
        except Exception as e:
            logger.error(f"ADVFN page {page} error: {e}")
            break
    return articles


def scrape_finanzen(max_pages=2):
    """Scrape news from finanzen.net. Requires curl_cffi for Akamai bypass. Returns list of article dicts."""
    if not HAS_CURL_CFFI:
        logger.error("finanzen.net requires curl_cffi package. Install with: pip install curl_cffi")
        return []

    articles = []
    seen_urls = set()
    for page in range(1, max_pages + 1):
        url = 'https://www.finanzen.net/news/' if page == 1 else f'https://www.finanzen.net/news/?intpagenr={page}'
        try:
            resp = curl_requests.get(url, impersonate='chrome', timeout=30)
            if resp.status_code != 200:
                logger.error(f"finanzen.net page {page}: status {resp.status_code}")
                break
            soup = BeautifulSoup(resp.text, 'html.parser')

            # Featured articles in div.article-layout__list
            layout_list = soup.find('div', class_='article-layout__list')
            if layout_list:
                for art in layout_list.find_all('div', class_='article', recursive=False):
                    a_el = art.find('a', href=lambda h: h and '/nachricht/' in h)
                    if not a_el:
                        continue
                    href = a_el.get('href', '')
                    if href and not href.startswith('http'):
                        href = 'https://www.finanzen.net' + href
                    if href in seen_urls:
                        continue
                    seen_urls.add(href)

                    time_el = art.find('time')
                    time_str = ''
                    published = ''
                    if time_el:
                        datetime_attr = time_el.get('datetime', '')
                        published = datetime_attr
                        time_text = time_el.get_text(strip=True)
                        # "17:58 Uhr"
                        m = re.match(r'(\d{1,2}:\d{2})', time_text)
                        if m:
                            time_str = m.group(1)

                    raw_text = a_el.get_text(strip=True)
                    # Remove leading time like "17:58 Uhr"
                    title = re.sub(r'^\d{1,2}:\d{2}\s*Uhr\s*', '', raw_text)

                    articles.append({
                        'source': 'Finanzen.net',
                        'title': title,
                        'summary': '',
                        'published': published,
                        'time': time_str,
                        'category': '',
                        'type': 'finanzen',
                        'tickers': [],
                        'url': href,
                    })

            # Table-based articles
            for row in soup.find_all('tr', class_='table__tr'):
                a_el = row.find('a', href=lambda h: h and '/nachricht/' in h)
                if not a_el:
                    continue
                href = a_el.get('href', '')
                if href and not href.startswith('http'):
                    href = 'https://www.finanzen.net' + href
                if href in seen_urls:
                    continue
                seen_urls.add(href)

                tds = row.find_all('td')
                time_str = ''
                title = ''
                if len(tds) >= 2:
                    # First TD = time, second TD = title
                    time_str = tds[0].get_text(strip=True)
                    title = a_el.get_text(strip=True)
                elif len(tds) == 1:
                    raw_text = a_el.get_text(strip=True)
                    title = re.sub(r'^\d{1,2}:\d{2}\s*Uhr\s*', '', raw_text)

                if not title or len(title) < 10:
                    continue

                articles.append({
                    'source': 'Finanzen.net',
                    'title': title,
                    'summary': '',
                    'published': '',
                    'time': time_str,
                    'category': '',
                    'type': 'finanzen',
                    'tickers': [],
                    'url': href,
                })

            logger.info(f"finanzen.net page {page}: {len(articles)} articles total")
        except Exception as e:
            logger.error(f"finanzen.net page {page} error: {e}")
            break
    return articles


def scrape_proinvestor(max_pages=3, proxy_token=''):
    """Scrape news from ProInvestor (Danish). Uses scrape.do proxy to bypass Cloudflare. Returns list of article dicts."""
    if not proxy_token:
        logger.error("ProInvestor requires a Scrape.do proxy token. Set it in Settings > News Sources > ProInvestor.")
        return []

    articles = []
    PAGE_SIZE = 27  # ProInvestor uses offsets in multiples of 27
    for page in range(max_pages):
        offset = page * PAGE_SIZE
        target_url = 'https://proinvestor.com/alle-aktienyheder/' if page == 0 else f'https://proinvestor.com/alle-aktienyheder/{offset}/'
        proxy_url = f'https://api.scrape.do?token={proxy_token}&url={target_url}'
        try:
            resp = requests.get(proxy_url, timeout=45)
            if resp.status_code != 200:
                logger.error(f"ProInvestor page {page+1}: status {resp.status_code}")
                break
            soup = BeautifulSoup(resp.text, 'html.parser')
            container = soup.find('div', class_='bottom row')
            if not container:
                logger.warning(f"ProInvestor page {page+1}: no article container found")
                break
            article_ps = container.find_all('p')
            if not article_ps:
                break
            page_count = 0
            for p in article_ps:
                title_a = p.find('a', class_='title left')
                if not title_a:
                    continue
                title = title_a.get_text(strip=True)
                if not title or len(title) < 10:
                    continue
                href = title_a.get('href', '')
                if href and not href.startswith('http'):
                    href = 'https://proinvestor.com' + href

                time_span = p.find('span', class_='light right')
                time_text = time_span.get_text(strip=True) if time_span else ''

                source_span = p.find('span', class_='grey')
                source_name = source_span.get_text(strip=True) if source_span else ''

                articles.append({
                    'source': 'ProInvestor',
                    'title': title,
                    'summary': source_name,
                    'published': '',
                    'time': time_text,
                    'category': source_name,
                    'type': 'proinvestor',
                    'tickers': [],
                    'url': href,
                })
                page_count += 1
            logger.info(f"ProInvestor page {page+1}: {page_count} articles")
        except Exception as e:
            logger.error(f"ProInvestor page {page+1} error: {e}")
            break
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

    if sources.get('advfn', {}).get('enabled', True):
        max_p = sources['advfn'].get('max_pages', 1)
        arts = scrape_advfn(max_pages=max_p)
        all_articles.extend(arts)

    if sources.get('finanzen', {}).get('enabled', True):
        max_p = sources['finanzen'].get('max_pages', 2)
        arts = scrape_finanzen(max_pages=max_p)
        all_articles.extend(arts)

    if sources.get('proinvestor', {}).get('enabled', True):
        max_p = sources['proinvestor'].get('max_pages', 3)
        proxy_token = sources.get('proinvestor', {}).get('proxy_token', '')
        arts = scrape_proinvestor(max_pages=max_p, proxy_token=proxy_token)
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
    elif source_name == 'advfn':
        return scrape_advfn(max_pages=src.get('max_pages', 1))
    elif source_name == 'finanzen':
        return scrape_finanzen(max_pages=src.get('max_pages', 2))
    elif source_name == 'proinvestor':
        return scrape_proinvestor(max_pages=src.get('max_pages', 3), proxy_token=src.get('proxy_token', ''))
    return []

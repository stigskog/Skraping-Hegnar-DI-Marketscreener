import os
import json

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance', 'config.json')

DEFAULT_COUNTRIES = [
    {'code': 'NO', 'label': 'Norske aksjer (Oslo Børs)', 'exchange': 'Oslo Børs', 'region': 'Norway'},
    {'code': 'SE', 'label': 'Svenske aksjer (Stockholmsbörsen)', 'exchange': 'Stockholm', 'region': 'Sweden'},
    {'code': 'DK', 'label': 'Danske aksjer (København)', 'exchange': 'Copenhagen', 'region': 'Denmark'},
    {'code': 'FI', 'label': 'Finske aksjer (Helsinki)', 'exchange': 'Helsinki', 'region': 'Finland'},
    {'code': 'US', 'label': 'Amerikanske aksjer (USA)', 'exchange': 'US exchanges', 'region': 'United States'},
    {'code': 'GE', 'label': 'Tyske aksjer (Frankfurt/XETRA)', 'exchange': 'XETRA, Frankfurt', 'region': 'Germany'},
    {'code': 'UK', 'label': 'Britiske aksjer (London)', 'exchange': 'London Stock Exchange', 'region': 'United Kingdom'},
]

# Flag emojis for country codes
COUNTRY_FLAGS = {
    'NO': '\U0001f1f3\U0001f1f4',
    'SE': '\U0001f1f8\U0001f1ea',
    'DK': '\U0001f1e9\U0001f1f0',
    'FI': '\U0001f1eb\U0001f1ee',
    'US': '\U0001f1fa\U0001f1f8',
    'GE': '\U0001f1e9\U0001f1ea',
    'UK': '\U0001f1ec\U0001f1e7',
    'FR': '\U0001f1eb\U0001f1f7',
    'NL': '\U0001f1f3\U0001f1f1',
    'CH': '\U0001f1e8\U0001f1ed',
    'ES': '\U0001f1ea\U0001f1f8',
    'IT': '\U0001f1ee\U0001f1f9',
    'CA': '\U0001f1e8\U0001f1e6',
    'JP': '\U0001f1ef\U0001f1f5',
    'AU': '\U0001f1e6\U0001f1fa',
}

DEFAULT_CONFIG = {
    'username': 'admin',
    'password': 'admin123',
    'ai_provider': 'deepseek',
    'ai_api_key': '',
    'ai_model': 'deepseek-chat',
    'system_prompt': '',
    'batch_size': 25,
    'manual_prompt': '',
    'schedule_enabled': False,
    'schedule_interval_minutes': 30,
    'countries': DEFAULT_COUNTRIES,
    'sources': {
        'finansavisen': {
            'enabled': True,
            'max_pages': 3,
            'url': 'https://ws.finansavisen.no/context/market-news',
            'page_size': 50
        },
        'di': {
            'enabled': True,
            'max_pages': 3,
            'url': 'https://www.di.se/live-by-page/',
        },
        'marketscreener': {
            'enabled': True,
            'max_pages': 1,
            'url': 'https://www.marketscreener.com/news/',
        },
        'advfn': {
            'enabled': True,
            'max_pages': 1,
            'url': 'https://uk.advfn.com/newspaper',
        },
        'finanzen': {
            'enabled': True,
            'max_pages': 2,
            'url': 'https://www.finanzen.net/news/',
        },
        'proinvestor': {
            'enabled': True,
            'max_pages': 3,
            'url': 'https://proinvestor.com/alle-aktienyheder/',
        },
    }
}


def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            saved = json.load(f)
        merged = {**DEFAULT_CONFIG, **saved}
        merged['sources'] = {**DEFAULT_CONFIG['sources'], **saved.get('sources', {})}
        # Keep saved countries if they exist, otherwise use defaults
        if 'countries' not in saved:
            merged['countries'] = DEFAULT_COUNTRIES
        return merged
    return DEFAULT_CONFIG.copy()


def save_config(config):
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

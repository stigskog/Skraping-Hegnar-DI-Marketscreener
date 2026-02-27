import os
import json

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance', 'config.json')

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
        return merged
    return DEFAULT_CONFIG.copy()


def save_config(config):
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

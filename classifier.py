import json
import logging

logger = logging.getLogger(__name__)

AI_PROVIDERS = {
    'deepseek': {
        'label': 'DeepSeek',
        'base_url': 'https://api.deepseek.com',
        'key_placeholder': 'sk-...',
        'key_link': 'https://platform.deepseek.com/api_keys',
        'key_help': '1. Go to platform.deepseek.com and sign up\n2. Click "API Keys" in the left sidebar\n3. Click "Create new API key"\n4. Copy the key (starts with sk-)',
        'models': [
            {'id': 'deepseek-chat', 'label': 'DeepSeek Chat (recommended)'},
            {'id': 'deepseek-reasoner', 'label': 'DeepSeek Reasoner'},
        ],
        'type': 'openai_compat',
    },
    'openai': {
        'label': 'OpenAI',
        'base_url': 'https://api.openai.com/v1',
        'key_placeholder': 'sk-...',
        'key_link': 'https://platform.openai.com/api-keys',
        'key_help': '1. Go to platform.openai.com and sign in\n2. Click your profile icon > "API keys"\n3. Click "Create new secret key"\n4. Copy the key (starts with sk-)',
        'models': [
            {'id': 'gpt-4o-mini', 'label': 'GPT-4o Mini (faster, cheaper)'},
            {'id': 'gpt-4o', 'label': 'GPT-4o'},
            {'id': 'gpt-4.1-mini', 'label': 'GPT-4.1 Mini'},
            {'id': 'gpt-4.1', 'label': 'GPT-4.1'},
        ],
        'type': 'openai_compat',
    },
    'anthropic': {
        'label': 'Claude (Anthropic)',
        'key_placeholder': 'sk-ant-...',
        'key_link': 'https://console.anthropic.com/settings/keys',
        'key_help': '1. Go to console.anthropic.com and sign up\n2. Go to Settings > API Keys\n3. Click "Create Key"\n4. Copy the key (starts with sk-ant-)',
        'models': [
            {'id': 'claude-sonnet-4-20250514', 'label': 'Claude Sonnet 4'},
            {'id': 'claude-3-5-haiku-20241022', 'label': 'Claude 3.5 Haiku (faster, cheaper)'},
        ],
        'type': 'anthropic',
    },
    'gemini': {
        'label': 'Gemini (Google)',
        'key_placeholder': 'AIza...',
        'key_link': 'https://aistudio.google.com/apikey',
        'key_help': '1. Go to aistudio.google.com/apikey\n2. Sign in with your Google account\n3. Click "Create API key"\n4. Select a Google Cloud project or create one\n5. Copy the key (starts with AIza)',
        'models': [
            {'id': 'gemini-2.0-flash', 'label': 'Gemini 2.0 Flash (recommended)'},
            {'id': 'gemini-2.5-flash-preview-05-20', 'label': 'Gemini 2.5 Flash Preview'},
            {'id': 'gemini-2.0-flash-lite', 'label': 'Gemini 2.0 Flash Lite (cheapest)'},
        ],
        'type': 'gemini',
    },
}

SYSTEM_PROMPT_TEMPLATE = """You are a stock market signal analyst. You receive raw financial news articles and must:

1. FILTER: Only keep news about LISTED companies with a concrete catalyst:
   - Analyst upgrade/downgrade or price target change
   - Insider buying/selling
   - Earnings report (quarterly/annual results)
   - Contract win / new order
   - Acquisition / merger / divestiture
   - Short position changes
   - New product/approval/patent
   - Flagging (ownership threshold crossed)
   - Bond/loan placement
   - Management changes (CEO, board)

   EXCLUDE: Pure price movement descriptions, macro/political news, general market commentary, interest rate fixings for bonds, financial calendar announcements.

2. CLASSIFY each signal as "Bullish" or "Bearish" based on the catalyst.

3. ASSIGN COUNTRY strictly from this list only:
{country_list}
   Do NOT default to US if the company is European. Ignore ADRs.

4. TRANSLATE everything to Norwegian. Swedish, English, German, and Danish text must be translated to Norwegian.

5. For each signal, extract:
   - company_name: Full company name
   - ticker: Stock ticker symbol (e.g., EQNR, SUBC, KOG)
   - direction: "Bullish" or "Bearish"
   - comment: Short Norwegian description of the catalyst (max 80 chars)
   - time: Time of the news (HH:MM format)
   - country: Country code ({country_codes})

Return a JSON array of signal objects. If no valid signals found, return an empty array [].
IMPORTANT: Only return the JSON array, nothing else. No markdown, no code blocks."""


def build_system_prompt(countries=None):
    """Build the system prompt dynamically from the configured countries list."""
    if not countries:
        from config import DEFAULT_COUNTRIES
        countries = DEFAULT_COUNTRIES
    lines = []
    for c in countries:
        lines.append(f'   - "{c["code"]}" = {c["exchange"]} ({c["region"]})')
    country_list = '\n'.join(lines)
    country_codes = ', '.join(c['code'] for c in countries)
    return SYSTEM_PROMPT_TEMPLATE.format(country_list=country_list, country_codes=country_codes)


# Default prompt for backward compatibility
SYSTEM_PROMPT = build_system_prompt()

BATCH_SIZE = 25


def _call_openai_compat(api_key, base_url, model, messages):
    from openai import OpenAI
    client = OpenAI(api_key=api_key, base_url=base_url)
    response = client.chat.completions.create(
        model=model, messages=messages, temperature=0.1, max_tokens=4000,
    )
    return response.choices[0].message.content.strip()


def _call_anthropic(api_key, model, messages):
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    system_msg = ''
    user_msgs = []
    for m in messages:
        if m['role'] == 'system':
            system_msg = m['content']
        else:
            user_msgs.append(m)
    response = client.messages.create(
        model=model, max_tokens=4000, system=system_msg,
        messages=user_msgs, temperature=0.1,
    )
    return response.content[0].text.strip()


def _call_gemini(api_key, model, messages):
    from google import genai
    client = genai.Client(api_key=api_key)
    system_msg = ''
    user_msg = ''
    for m in messages:
        if m['role'] == 'system':
            system_msg = m['content']
        else:
            user_msg = m['content']
    combined = f"{system_msg}\n\n{user_msg}" if system_msg else user_msg
    response = client.models.generate_content(
        model=model, contents=combined,
        config={'temperature': 0.1, 'max_output_tokens': 4000},
    )
    return response.text.strip()


def call_ai(provider, api_key, model, messages):
    provider_info = AI_PROVIDERS.get(provider, AI_PROVIDERS['deepseek'])
    ptype = provider_info['type']
    if ptype == 'openai_compat':
        return _call_openai_compat(api_key, provider_info['base_url'], model, messages)
    elif ptype == 'anthropic':
        return _call_anthropic(api_key, model, messages)
    elif ptype == 'gemini':
        return _call_gemini(api_key, model, messages)
    raise ValueError(f"Unknown provider type: {ptype}")


def classify_articles(articles, api_key, model='deepseek-chat', provider='deepseek',
                      on_progress=None, system_prompt=None, batch_size=None, stop_check=None):
    """Send articles to AI for classification. Returns list of signal dicts.
    on_progress(batch_num, total_batches, signals_so_far) is called after each batch.
    stop_check() returns True if the run should be stopped.
    """
    if not api_key:
        logger.error("No AI API key configured")
        return []

    prompt = system_prompt if system_prompt else SYSTEM_PROMPT
    bs = batch_size if batch_size and batch_size > 0 else BATCH_SIZE

    all_signals = []
    total_batches = (len(articles) + bs - 1) // bs

    for i in range(0, len(articles), bs):
        if stop_check and stop_check():
            logger.info("Classification stopped by user")
            break

        batch = articles[i:i + bs]
        batch_text = format_articles_for_prompt(batch)
        batch_num = i // bs + 1

        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"Analyze these news articles and extract stock signals:\n\n{batch_text}"}
        ]

        try:
            result_text = call_ai(provider, api_key, model, messages)
            if result_text.startswith('```'):
                result_text = result_text.split('\n', 1)[-1]
                if result_text.endswith('```'):
                    result_text = result_text[:-3]
                result_text = result_text.strip()

            signals = json.loads(result_text)
            if isinstance(signals, list):
                all_signals.extend(signals)
                logger.info(f"Batch {batch_num}/{total_batches}: {len(signals)} signals")
        except json.JSONDecodeError as e:
            logger.error(f"Batch {batch_num}: JSON parse error: {e}")
        except Exception as e:
            logger.error(f"Batch {batch_num}: API error: {e}")

        if on_progress:
            on_progress(batch_num, total_batches, len(all_signals))

    seen = set()
    unique = []
    for sig in all_signals:
        key = (sig.get('ticker', ''), sig.get('comment', ''))
        if key not in seen:
            seen.add(key)
            unique.append(sig)
    return unique


def format_articles_for_prompt(articles):
    lines = []
    for art in articles:
        source = art.get('source', '')
        time = art.get('time', '')
        title = art.get('title', '')
        summary = art.get('summary', '')
        category = art.get('category', '')
        tickers = art.get('tickers', [])
        ticker_str = ', '.join([f"{t['symbol']} ({t['name']})" for t in tickers if t.get('symbol')])
        parts = [f"[{source}] {time}"]
        if category:
            parts.append(f"Category: {category}")
        if ticker_str:
            parts.append(f"Tickers: {ticker_str}")
        parts.append(f"Title: {title}")
        if summary:
            parts.append(f"Summary: {summary[:300]}")
        lines.append('\n'.join(parts))
    return '\n---\n'.join(lines)

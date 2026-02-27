import os
import io
import re
import json
import logging
import zipfile
import threading
from datetime import datetime
from collections import OrderedDict
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, jsonify
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_apscheduler import APScheduler
from config import load_config, save_config
from scrapers import scrape_all_sources, scrape_single_source
from classifier import classify_articles, call_ai, AI_PROVIDERS, SYSTEM_PROMPT as DEFAULT_SYSTEM_PROMPT
from excel_generator import generate_excel

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'stox-signals-secret-key-change-me')

# Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = None

# Scheduler
scheduler = APScheduler()

# Ensure instance dirs exist
INSTANCE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance')
OUTPUTS_DIR = os.path.join(INSTANCE_DIR, 'outputs')
RUNS_DIR = os.path.join(INSTANCE_DIR, 'runs')
os.makedirs(OUTPUTS_DIR, exist_ok=True)
os.makedirs(RUNS_DIR, exist_ok=True)

# Track active background runs: {run_id: {'thread': Thread, 'stop_event': Event}}
_active_runs = {}
_runs_lock = threading.Lock()


class User(UserMixin):
    def __init__(self, username):
        self.id = username


@login_manager.user_loader
def load_user(user_id):
    config = load_config()
    if user_id == config.get('username', 'admin'):
        return User(user_id)
    return None


# ============ ROUTES ============

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')
        config = load_config()
        if username == config.get('username', 'admin') and password == config.get('password', 'admin123'):
            user = User(username)
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Invalid credentials', 'error')
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


@app.route('/')
@login_required
def dashboard():
    runs = get_runs()
    config = load_config()
    return render_template('dashboard.html', runs=runs, config=config)


@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    config = load_config()
    if request.method == 'POST':
        # Update credentials
        new_user = request.form.get('username', '').strip()
        new_pass = request.form.get('password', '').strip()
        if new_user:
            config['username'] = new_user
        if new_pass:
            config['password'] = new_pass

        # Update AI config
        config['ai_provider'] = request.form.get('ai_provider', 'deepseek').strip()
        api_key = request.form.get('ai_api_key', '').strip()
        if api_key:
            config['ai_api_key'] = api_key
        config['ai_model'] = request.form.get('ai_model', 'deepseek-chat').strip()

        # Update prompt and batch size
        config['system_prompt'] = request.form.get('system_prompt', '').strip()
        try:
            bs = int(request.form.get('batch_size', 25))
            config['batch_size'] = max(1, min(100, bs))
        except (ValueError, TypeError):
            config['batch_size'] = 25

        # Update schedule
        config['schedule_enabled'] = request.form.get('schedule_enabled') == 'on'
        try:
            config['schedule_interval_minutes'] = int(request.form.get('schedule_interval', 30))
        except:
            config['schedule_interval_minutes'] = 30

        # Update sources
        for src_name in ['finansavisen', 'di', 'marketscreener', 'advfn', 'finanzen', 'proinvestor']:
            if src_name not in config['sources']:
                config['sources'][src_name] = {}
            config['sources'][src_name]['enabled'] = request.form.get(f'{src_name}_enabled') == 'on'
            if src_name not in ('marketscreener',):
                try:
                    config['sources'][src_name]['max_pages'] = int(request.form.get(f'{src_name}_max_pages', 3))
                except:
                    config['sources'][src_name]['max_pages'] = 3
            else:
                config['sources'][src_name]['max_pages'] = 1

        save_config(config)
        update_scheduler(config)
        flash('Settings saved', 'success')
        return redirect(url_for('settings'))

    providers = {k: {'label': v['label'], 'key_placeholder': v['key_placeholder'],
                      'key_link': v['key_link'], 'key_help': v.get('key_help', ''),
                      'models': v['models']}
                 for k, v in AI_PROVIDERS.items()}
    return render_template('settings.html', config=config, providers=providers,
                           providers_json=json.dumps(providers),
                           default_prompt=DEFAULT_SYSTEM_PROMPT)


@app.route('/files')
@login_required
def files():
    """List all output files grouped by day."""
    file_list = []
    if os.path.exists(OUTPUTS_DIR):
        for fname in os.listdir(OUTPUTS_DIR):
            if fname.endswith('.xlsx'):
                fpath = os.path.join(OUTPUTS_DIR, fname)
                stat = os.stat(fpath)
                size_kb = stat.st_size / 1024
                date_match = re.search(r'(\d{4}-\d{2}-\d{2})', fname)
                date_str = date_match.group(1) if date_match else 'Unknown'
                file_list.append({
                    'name': fname,
                    'date': date_str,
                    'size': f'{size_kb:.1f} KB',
                    'size_bytes': stat.st_size,
                })
    file_list.sort(key=lambda f: f['name'], reverse=True)
    grouped = OrderedDict()
    for f in file_list:
        day = f['date']
        if day not in grouped:
            grouped[day] = []
        grouped[day].append(f)
    return render_template('files.html', grouped_files=grouped, total_files=len(file_list))


@app.route('/api/providers')
@login_required
def api_providers():
    """Return AI provider data for the settings JS."""
    data = {}
    for key, prov in AI_PROVIDERS.items():
        data[key] = {
            'label': prov['label'],
            'key_placeholder': prov['key_placeholder'],
            'key_link': prov['key_link'],
            'key_help': prov.get('key_help', ''),
            'models': prov['models'],
        }
    return jsonify(data)


@app.route('/api/start_run', methods=['POST'])
@login_required
def api_start_run():
    """Start a scrape run in the background. Returns run_id immediately."""
    source = request.json.get('source', 'all') if request.is_json else request.form.get('source', 'all')
    config = load_config()

    if not config.get('ai_api_key'):
        return jsonify({'error': 'No AI API key configured'}), 400

    run_id = datetime.now().strftime('%Y%m%d_%H%M%S')
    run_data = {
        'id': run_id,
        'started': datetime.now().isoformat(),
        'source': source,
        'status': 'scraping',
        'phase': 'Scraping articles...',
        'article_count': 0,
        'signal_count': 0,
        'batch_progress': '',
        'excel_file': None,
        'error': None,
        'logs': [],
    }
    save_run(run_data)

    stop_event = threading.Event()
    thread = threading.Thread(target=_background_run, args=(run_id, source, config, stop_event), daemon=True)
    with _runs_lock:
        _active_runs[run_id] = {'thread': thread, 'stop_event': stop_event}
    thread.start()

    return jsonify({'run_id': run_id})


@app.route('/api/run_status/<run_id>')
@login_required
def api_run_status(run_id):
    """Poll the status of a run."""
    run_file = os.path.join(RUNS_DIR, f'{run_id}.json')
    if not os.path.exists(run_file):
        return jsonify({'error': 'Run not found'}), 404
    with open(run_file, 'r') as f:
        run_data = json.load(f)
    return jsonify(run_data)


@app.route('/api/stop_run/<run_id>', methods=['POST'])
@login_required
def api_stop_run(run_id):
    """Request a running task to stop."""
    with _runs_lock:
        run_info = _active_runs.get(run_id)
    if not run_info:
        return jsonify({'error': 'Run not active'}), 404
    stop_event = run_info.get('stop_event')
    if stop_event:
        stop_event.set()
        return jsonify({'status': 'stop_requested'})
    return jsonify({'error': 'Cannot stop this run'}), 400


@app.route('/api/download_zip', methods=['POST'])
@login_required
def api_download_zip():
    """Create a zip of selected files and return it."""
    filenames = request.json.get('files', []) if request.is_json else request.form.getlist('files')
    if not filenames:
        return jsonify({'error': 'No files selected'}), 400

    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        for fname in filenames:
            safe_name = os.path.basename(fname)
            fpath = os.path.join(OUTPUTS_DIR, safe_name)
            if os.path.exists(fpath) and safe_name.endswith('.xlsx'):
                zf.write(fpath, safe_name)
    memory_file.seek(0)

    zip_name = f'signals_{datetime.now().strftime("%Y%m%d_%H%M%S")}.zip'
    return send_file(memory_file, mimetype='application/zip', as_attachment=True, download_name=zip_name)


@app.route('/api/delete_files', methods=['POST'])
@login_required
def api_delete_files():
    """Delete selected output files."""
    filenames = request.json.get('files', []) if request.is_json else []
    deleted = 0
    for fname in filenames:
        safe_name = os.path.basename(fname)
        fpath = os.path.join(OUTPUTS_DIR, safe_name)
        if os.path.exists(fpath) and safe_name.endswith('.xlsx'):
            os.remove(fpath)
            deleted += 1
    return jsonify({'deleted': deleted})


@app.route('/run', methods=['POST'])
@login_required
def run_scrape():
    """Legacy form-based run - redirects to dashboard, run starts in background."""
    source = request.form.get('source', 'all')
    config = load_config()

    if not config.get('ai_api_key'):
        flash('Please set your AI API key in Settings first', 'error')
        return redirect(url_for('dashboard'))

    run_id = datetime.now().strftime('%Y%m%d_%H%M%S')
    run_data = {
        'id': run_id,
        'started': datetime.now().isoformat(),
        'source': source,
        'status': 'scraping',
        'phase': 'Scraping articles...',
        'article_count': 0,
        'signal_count': 0,
        'batch_progress': '',
        'excel_file': None,
        'error': None,
        'logs': [],
    }
    save_run(run_data)

    stop_event = threading.Event()
    thread = threading.Thread(target=_background_run, args=(run_id, source, config, stop_event), daemon=True)
    with _runs_lock:
        _active_runs[run_id] = {'thread': thread, 'stop_event': stop_event}
    thread.start()

    flash('Run started in background', 'success')
    return redirect(url_for('dashboard'))


@app.route('/download/<filename>')
@login_required
def download(filename):
    filepath = os.path.join(OUTPUTS_DIR, filename)
    if os.path.exists(filepath):
        return send_file(filepath, as_attachment=True)
    flash('File not found', 'error')
    return redirect(url_for('dashboard'))


@app.route('/delete_run/<run_id>', methods=['POST'])
@login_required
def delete_run(run_id):
    run_file = os.path.join(RUNS_DIR, f'{run_id}.json')
    if os.path.exists(run_file):
        with open(run_file, 'r') as f:
            run_data = json.load(f)
        if run_data.get('excel_file'):
            excel_path = os.path.join(OUTPUTS_DIR, run_data['excel_file'])
            if os.path.exists(excel_path):
                os.remove(excel_path)
        os.remove(run_file)
        flash('Run deleted', 'success')
    return redirect(url_for('dashboard'))


MANUAL_DEFAULT_PROMPT = """You are a stock market signal analyst. The user will paste raw text (news, reports, messages, etc.) in any format. Your job is to:

1. EXTRACT any mentions of listed companies with a concrete catalyst:
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

   EXCLUDE: Pure price movement descriptions, macro/political news, general market commentary.

2. CLASSIFY each signal as "Bullish" or "Bearish" based on the catalyst.

3. ASSIGN COUNTRY based on where the company is primarily listed:
   - "NO" for Oslo Børs (Norway), "SE" for Stockholm (Sweden)
   - "DK" for Copenhagen (Denmark), "FI" for Helsinki (Finland)
   - "US" for US exchanges, "OTHER" for any other

4. TRANSLATE everything to Norwegian.

5. For each signal, extract:
   - company_name: Full company name
   - ticker: Stock ticker symbol (e.g., EQNR, SUBC, KOG). Use your best guess if not explicitly stated.
   - direction: "Bullish" or "Bearish"
   - comment: Short Norwegian description of the catalyst (max 80 chars)
   - time: Time if mentioned (HH:MM format), otherwise ""
   - country: Country code (NO, SE, DK, FI, US, OTHER)

Return a JSON array of signal objects. If no valid signals found, return an empty array [].
IMPORTANT: Only return the JSON array, nothing else. No markdown, no code blocks."""


@app.route('/manual')
@login_required
def manual():
    config = load_config()
    return render_template('manual.html', config=config,
                           default_prompt=MANUAL_DEFAULT_PROMPT)


@app.route('/api/manual_classify', methods=['POST'])
@login_required
def api_manual_classify():
    """Classify raw pasted text using AI."""
    data = request.get_json() if request.is_json else {}
    raw_text = data.get('text', '').strip()
    custom_prompt = data.get('prompt', '').strip()

    if not raw_text:
        return jsonify({'error': 'No text provided'}), 400

    MAX_CHARS = 50000
    if len(raw_text) > MAX_CHARS:
        return jsonify({'error': f'Text exceeds maximum of {MAX_CHARS:,} characters'}), 400

    config = load_config()
    if not config.get('ai_api_key'):
        return jsonify({'error': 'No AI API key configured. Go to Settings to set one.'}), 400

    prompt = custom_prompt if custom_prompt else MANUAL_DEFAULT_PROMPT

    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": f"Analyze this raw text and extract stock signals:\n\n{raw_text}"}
    ]

    try:
        result_text = call_ai(
            provider=config.get('ai_provider', 'deepseek'),
            api_key=config['ai_api_key'],
            model=config.get('ai_model', 'deepseek-chat'),
            messages=messages,
        )

        # Clean markdown code blocks if present
        if result_text.startswith('```'):
            result_text = result_text.split('\n', 1)[-1]
            if result_text.endswith('```'):
                result_text = result_text[:-3]
            result_text = result_text.strip()

        signals = json.loads(result_text)
        if not isinstance(signals, list):
            return jsonify({'error': 'AI returned unexpected format'}), 500

        return jsonify({'signals': signals, 'count': len(signals)})

    except json.JSONDecodeError:
        return jsonify({'error': 'AI response was not valid JSON. Try again or adjust your prompt.'}), 500
    except Exception as e:
        return jsonify({'error': f'AI error: {str(e)}'}), 500


@app.route('/api/manual_save_prompt', methods=['POST'])
@login_required
def api_manual_save_prompt():
    """Save the manual classification prompt to config."""
    data = request.get_json() if request.is_json else {}
    prompt = data.get('prompt', '').strip()
    config = load_config()
    config['manual_prompt'] = prompt
    save_config(config)
    return jsonify({'status': 'saved'})


@app.route('/api/manual_download', methods=['POST'])
@login_required
def api_manual_download():
    """Generate and download Excel from manual classification signals."""
    data = request.get_json() if request.is_json else {}
    signals = data.get('signals', [])
    if not signals:
        return jsonify({'error': 'No signals to download'}), 400

    excel_path = generate_excel(signals)
    return send_file(excel_path, as_attachment=True,
                     download_name=os.path.basename(excel_path))


# ============ BACKGROUND RUN ============

def _add_log(run_data, message):
    """Append a timestamped log entry to run_data and persist."""
    if 'logs' not in run_data:
        run_data['logs'] = []
    run_data['logs'].append({
        'ts': datetime.now().strftime('%H:%M:%S'),
        'msg': message
    })
    save_run(run_data)


def _check_stopped(run_data, stop_event):
    """Check if stop was requested. Returns True if stopped."""
    if stop_event and stop_event.is_set():
        run_data['status'] = 'stopped'
        run_data['phase'] = 'Stopped by user'
        run_data['completed'] = datetime.now().isoformat()
        _add_log(run_data, 'Run stopped by user')
        return True
    return False


def _background_run(run_id, source, config, stop_event=None):
    """Execute scrape + classify + excel in a background thread."""
    run_data = load_run(run_id)
    if not run_data:
        return
    if 'logs' not in run_data:
        run_data['logs'] = []

    try:
        # Phase 1: Scrape
        run_data['status'] = 'scraping'
        run_data['phase'] = 'Scraping articles...'
        save_run(run_data)
        _add_log(run_data, f'Starting scrape (source: {source})')

        if source == 'all':
            articles = scrape_all_sources(config)
        else:
            articles = scrape_single_source(source, config)

        run_data['article_count'] = len(articles)
        _add_log(run_data, f'Scraping complete: {len(articles)} articles found')

        if not articles:
            run_data['status'] = 'completed'
            run_data['phase'] = 'Done'
            run_data['error'] = 'No articles found'
            run_data['completed'] = datetime.now().isoformat()
            _add_log(run_data, 'No articles found. Run completed.')
            return

        if _check_stopped(run_data, stop_event):
            return

        # Phase 2: AI Classification
        run_data['status'] = 'classifying'
        run_data['phase'] = f'Classifying {len(articles)} articles with AI...'
        _add_log(run_data, f'Starting AI classification ({len(articles)} articles)')
        save_run(run_data)

        def on_progress(batch_num, total_batches, signals_so_far):
            run_data['batch_progress'] = f'Batch {batch_num}/{total_batches}'
            run_data['signal_count'] = signals_so_far
            run_data['phase'] = f'AI batch {batch_num}/{total_batches} ({signals_so_far} signals so far)'
            _add_log(run_data, f'Batch {batch_num}/{total_batches} done - {signals_so_far} signals so far')

        def stop_check():
            return stop_event.is_set() if stop_event else False

        signals = classify_articles(
            articles,
            api_key=config['ai_api_key'],
            model=config.get('ai_model', 'deepseek-chat'),
            provider=config.get('ai_provider', 'deepseek'),
            on_progress=on_progress,
            system_prompt=config.get('system_prompt') or None,
            batch_size=config.get('batch_size') or None,
            stop_check=stop_check,
        )

        if _check_stopped(run_data, stop_event):
            return

        run_data['signal_count'] = len(signals)
        _add_log(run_data, f'Classification complete: {len(signals)} unique signals')

        if not signals:
            run_data['status'] = 'completed'
            run_data['phase'] = 'Done'
            run_data['error'] = 'No signals extracted (AI returned empty)'
            run_data['completed'] = datetime.now().isoformat()
            _add_log(run_data, 'No signals extracted. Run completed.')
            return

        # Phase 3: Generate Excel
        run_data['status'] = 'generating'
        run_data['phase'] = f'Generating Excel with {len(signals)} signals...'
        _add_log(run_data, f'Generating Excel ({len(signals)} signals)')
        save_run(run_data)

        excel_path = generate_excel(signals)
        run_data['excel_file'] = os.path.basename(excel_path)
        run_data['status'] = 'completed'
        run_data['phase'] = 'Done'
        run_data['completed'] = datetime.now().isoformat()
        _add_log(run_data, f'Excel saved: {os.path.basename(excel_path)}')
        _add_log(run_data, f'Run completed: {len(articles)} articles, {len(signals)} signals')

        logger.info(f"Run {run_id}: {len(articles)} articles, {len(signals)} signals")

    except Exception as e:
        logger.exception(f"Run {run_id} failed")
        run_data['status'] = 'failed'
        run_data['phase'] = 'Failed'
        run_data['error'] = str(e)
        run_data['completed'] = datetime.now().isoformat()
        _add_log(run_data, f'ERROR: {str(e)}')
    finally:
        save_run(run_data)
        with _runs_lock:
            _active_runs.pop(run_id, None)


# ============ HELPERS ============

def get_runs():
    runs = []
    if os.path.exists(RUNS_DIR):
        for f in sorted(os.listdir(RUNS_DIR), reverse=True):
            if f.endswith('.json'):
                with open(os.path.join(RUNS_DIR, f), 'r') as fh:
                    runs.append(json.load(fh))
    return runs[:50]


def save_run(run_data):
    filepath = os.path.join(RUNS_DIR, f"{run_data['id']}.json")
    with open(filepath, 'w') as f:
        json.dump(run_data, f, indent=2)


def load_run(run_id):
    filepath = os.path.join(RUNS_DIR, f'{run_id}.json')
    if os.path.exists(filepath):
        with open(filepath, 'r') as f:
            return json.load(f)
    return None


def scheduled_run():
    """Run by the scheduler."""
    with app.app_context():
        config = load_config()
        if not config.get('ai_api_key'):
            logger.warning("Scheduled run skipped: no API key")
            return

        run_id = datetime.now().strftime('%Y%m%d_%H%M%S')
        run_data = {
            'id': run_id,
            'started': datetime.now().isoformat(),
            'source': 'all (scheduled)',
            'status': 'scraping',
            'phase': 'Scraping articles...',
            'article_count': 0,
            'signal_count': 0,
            'batch_progress': '',
            'excel_file': None,
            'error': None,
            'logs': [],
        }
        try:
            save_run(run_data)
            _add_log(run_data, 'Scheduled run started')
            articles = scrape_all_sources(config)
            run_data['article_count'] = len(articles)
            _add_log(run_data, f'Scraping complete: {len(articles)} articles')

            if articles:
                run_data['status'] = 'classifying'
                run_data['phase'] = f'Classifying {len(articles)} articles...'
                _add_log(run_data, f'Starting AI classification')
                save_run(run_data)

                def on_progress(batch_num, total_batches, signals_so_far):
                    run_data['batch_progress'] = f'Batch {batch_num}/{total_batches}'
                    run_data['signal_count'] = signals_so_far
                    _add_log(run_data, f'Batch {batch_num}/{total_batches} done - {signals_so_far} signals')

                signals = classify_articles(
                    articles,
                    api_key=config['ai_api_key'],
                    model=config.get('ai_model', 'deepseek-chat'),
                    provider=config.get('ai_provider', 'deepseek'),
                    on_progress=on_progress,
                    system_prompt=config.get('system_prompt') or None,
                    batch_size=config.get('batch_size') or None,
                )
                run_data['signal_count'] = len(signals)
                _add_log(run_data, f'Classification complete: {len(signals)} signals')

                if signals:
                    run_data['status'] = 'generating'
                    run_data['phase'] = 'Generating Excel...'
                    save_run(run_data)
                    excel_path = generate_excel(signals)
                    run_data['excel_file'] = os.path.basename(excel_path)
                    _add_log(run_data, f'Excel saved: {os.path.basename(excel_path)}')

            run_data['status'] = 'completed'
            run_data['phase'] = 'Done'
            run_data['completed'] = datetime.now().isoformat()
            _add_log(run_data, 'Scheduled run completed')
            save_run(run_data)
            logger.info(f"Scheduled run {run_id}: {run_data['article_count']} articles, {run_data['signal_count']} signals")
        except Exception as e:
            logger.exception("Scheduled run failed")
            run_data['status'] = 'failed'
            run_data['phase'] = 'Failed'
            run_data['error'] = str(e)
            run_data['completed'] = datetime.now().isoformat()
            _add_log(run_data, f'ERROR: {str(e)}')
            save_run(run_data)


def update_scheduler(config):
    """Update the scheduler based on config."""
    job_id = 'scheduled_scrape'
    try:
        scheduler.remove_job(job_id)
    except:
        pass

    if config.get('schedule_enabled') and config.get('ai_api_key'):
        interval = config.get('schedule_interval_minutes', 30)
        scheduler.add_job(
            id=job_id,
            func=scheduled_run,
            trigger='interval',
            minutes=interval,
        )
        logger.info(f"Scheduler enabled: every {interval} minutes")
    else:
        logger.info("Scheduler disabled")


# ============ STARTUP ============

scheduler.init_app(app)
scheduler.start()
config = load_config()
update_scheduler(config)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)

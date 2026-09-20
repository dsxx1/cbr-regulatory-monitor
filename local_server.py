"""Visible local service: persistent jobs/outbox, explicit start/stop, no cloud runtime."""
import hashlib
import json
import os
import secrets
import shutil
import sqlite3
import subprocess
import sys
import signal
import threading
import time
from datetime import datetime, timezone
from contextlib import contextmanager
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

APP = Path(__file__).parent
DATA = Path(os.environ.get('MONITOR_DATA', '/data'))
TOKEN = secrets.token_urlsafe(32)
LOCK = threading.Lock()
DELIVERY_LOCK = threading.Lock()
CHILDREN = set()
CHILD_LOCK = threading.Lock()
AUTH = None
LAB_LOCK = threading.Lock()


def now():
    return datetime.now(timezone.utc).isoformat()


def setup_tls():
    extra = Path('/run/monitor-ca.pem')
    if extra.exists():
        bundle = Path('/tmp/monitor-ca-bundle.pem')
        bundle.write_bytes(Path('/etc/ssl/certs/ca-certificates.crt').read_bytes()+b'\n'+extra.read_bytes())
        os.environ['SSL_CERT_FILE'] = str(bundle)
        os.environ['NODE_EXTRA_CA_CERTS'] = str(extra)


@contextmanager
def db():
    con = sqlite3.connect(DATA / 'service.sqlite', timeout=30)
    con.row_factory = sqlite3.Row
    try:
        with con:
            yield con
    finally:
        con.close()


def init():
    global AUTH
    setup_tls()
    DATA.mkdir(parents=True, exist_ok=True)
    from admin_auth import OwnerAuth
    AUTH = OwnerAuth(DATA)
    sid = os.environ.get('MONITOR_OWNER_SID')
    if os.name == 'nt' and sid:
        secret_path=Path(os.environ.get('B24_SECRET_FILE',APP/'secrets.txt'))
        if secret_path.exists():subprocess.run(['icacls',str(secret_path),'/inheritance:r','/grant:r','*'+sid+':(F)','*S-1-5-18:(F)'],check=True,capture_output=True)
    for name in ('cloud-state.json', 'news-catalog.json', 'material-briefs.json', 'source-cache.json',
                 'analysis-queue.json', 'monitor-settings.json', 'llm-health.json'):
        if not (DATA / name).exists() and (APP / name).exists():
            shutil.copyfile(APP / name, DATA / name)
    if not (DATA / 'public').exists(): shutil.copytree(APP / 'public', DATA / 'public')
    if os.name == 'nt':
        shutil.copytree(APP / 'web', DATA / 'web', dirs_exist_ok=True)
    elif not (DATA / 'web').exists():
        (DATA / 'web').symlink_to(APP / 'web', target_is_directory=True)
    os.chdir(DATA)
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY, state TEXT, stage TEXT, started TEXT, finished TEXT, error TEXT);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS seen(id TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS outbox(id TEXT PRIMARY KEY, message TEXT, state TEXT, error TEXT);
        CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, task_id INTEGER, state TEXT, error TEXT);
        ''')
        c.execute("UPDATE jobs SET state='interrupted',error='Процесс остановлен; запустите проверку повторно' WHERE state='running'")
        c.execute("INSERT OR IGNORE INTO settings VALUES('schedule','off')")
        if not c.execute("SELECT 1 FROM settings WHERE key='baseline'").fetchone():
            for card in json.loads(Path('public/news.json').read_text(encoding='utf-8'))['news']:
                c.execute('INSERT OR IGNORE INTO seen VALUES(?)', (card['id'],))
            c.execute("INSERT INTO settings VALUES('baseline','done')")
    # Credentials stay in a read-only Docker secret, never in state/export.
    secret = Path(os.environ.get('B24_SECRET_FILE', '/run/secrets/b24'))
    if secret.exists():
        for line in secret.read_text(encoding='utf-8-sig').splitlines():
            key, sep, value = line.partition('=')
            if sep and key.strip() == 'B24_WEBHOOK' and value.strip():
                os.environ['B24_WEBHOOK'] = value.strip().strip('"').strip("'")
    from dashboard_export import export
    export()


def run_script(name, *args, timeout=1200):
    print(f'[{now()}] Начало: {name}', flush=True)
    child = subprocess.Popen([sys.executable, str(APP / name), *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0, start_new_session=os.name != 'nt')
    with CHILD_LOCK: CHILDREN.add(child)
    try:
        child.communicate(timeout=timeout)
        if child.returncode: raise RuntimeError(f'Ошибка этапа {name}; код {child.returncode}')
        print(f'[{now()}] Завершено: {name}', flush=True)
    except subprocess.TimeoutExpired:
        stop_child(child)
        raise RuntimeError(f'Превышено время этапа {name}') from None
    finally:
        with CHILD_LOCK: CHILDREN.discard(child)


def run_model(command,*,input,text,encoding,capture_output,timeout):
    child=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=text,encoding=encoding,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name=='nt' else 0,start_new_session=os.name!='nt')
    with CHILD_LOCK:CHILDREN.add(child)
    try:
        output,error=child.communicate(input=input,timeout=timeout)
        return subprocess.CompletedProcess(command,child.returncode,output,error)
    except subprocess.TimeoutExpired:
        stop_child(child);raise
    finally:
        with CHILD_LOCK:CHILDREN.discard(child)


def stop_child(child):
    if child.poll() is not None: return
    if os.name == 'nt':
        subprocess.run(['taskkill','/PID',str(child.pid),'/T','/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        os.killpg(child.pid, signal.SIGTERM)


def collect_outbox():
    cards = json.loads(Path('public/news.json').read_text(encoding='utf-8'))['news']
    labels = {'high':'ВАЖНО', 'medium':'ПОДГОТОВИТЬСЯ', 'low':'УЧЕСТЬ', 'news':'ДЛЯ СВЕДЕНИЯ', 'unknown':'РАЗБОР НЕ ГОТОВ'}
    with db() as c:
        for card in cards:
            if c.execute('SELECT 1 FROM seen WHERE id=?', (card['id'],)).fetchone(): continue
            brief = card.get('brief') or {}
            text = f"{labels.get(card['priority'],'НЕ ОЦЕНЕНО')}\n{card['title']}\n{card['url']}"
            if brief:
                text += '\n'+brief['summary']+'\nПочему важно: '+brief['priority_reason']+'\nСроки: '+brief['timing']
            else:
                text += '\nНовый материал найден. Полный разбор ещё не готов; важность не определена.'
            if card['priority'] == 'high': text += '\nРекомендуем рассмотреть постановку задачи. Создать заполненную задачу можно в карточке локального сайта.'
            c.execute('INSERT OR IGNORE INTO outbox VALUES(?,?,?,?)', (card['id'], text, 'pending', ''))
            c.execute('INSERT INTO seen VALUES(?)', (card['id'],))


def deliver():
    with DELIVERY_LOCK:
        return deliver_pending()


def deliver_pending():
    if not os.environ.get('B24_WEBHOOK'): return
    from bot_cloud import report_delivery
    Path('runtime').mkdir(exist_ok=True)
    with db() as c: rows = c.execute("SELECT * FROM outbox WHERE state='pending' LIMIT 15").fetchall()
    for row in rows:
        file = Path('runtime') / (row['id']+'.txt')
        file.write_text(row['message'], encoding='utf-8')
        report_delivery('sending','Проверяем доставку')
        try:
            run_script('bot_cloud.py', '--message', str(file), timeout=150)
            receipt = json.loads(Path('public/delivery.json').read_text(encoding='utf-8'))
            if receipt.get('state') != 'delivered': raise RuntimeError('Отправка не подтверждена')
            with db() as c: c.execute("UPDATE outbox SET state='sent',error='' WHERE id=?", (row['id'],))
        except Exception:
            with db() as c: c.execute("UPDATE outbox SET error='Доставка не подтверждена; очередь сохранена' WHERE id=?", (row['id'],))
            break


def worker(job_id):
    try:
        for stage, script, args in [('Источники и анализ', 'cloud_monitor.py', []),
                                    ('Разбор очереди', 'backfill.py', ['--limit','3','--workers','1'])]:
            with db() as c: c.execute('UPDATE jobs SET stage=? WHERE id=?', (stage, job_id))
            run_script(script, *args)
        with db() as c: c.execute("UPDATE jobs SET stage='Отправка в Б24' WHERE id=?", (job_id,))
        run_script('dashboard_export.py')
        collect_outbox()
        deliver()
        run_script('dashboard_export.py')
        with db() as c:
            pending=c.execute("SELECT count(*) FROM outbox WHERE state='pending'").fetchone()[0]
            stage=f'Сбор завершён; ожидают отправки: {pending}' if pending else 'Проверка завершена'
            c.execute("UPDATE jobs SET state='done',stage=?,finished=? WHERE id=?", (stage,now(), job_id))
    except Exception as exc:
        print(f'[{now()}] Проверка не завершена: {str(exc)[:150]}', flush=True)
        with db() as c: c.execute("UPDATE jobs SET state='failed',error=?,finished=? WHERE id=?", (str(exc)[:150], now(), job_id))


def start_job():
    with LOCK, db() as c:
        old = c.execute("SELECT id FROM jobs WHERE state='running'").fetchone()
        if old: return old['id']
        job_id = c.execute("INSERT INTO jobs(state,stage,started) VALUES('running','Запуск',?)", (now(),)).lastrowid
    threading.Thread(target=worker, args=(job_id,), daemon=True).start()
    return job_id


def create_task(card_id):
    from bot_cloud import call
    cards = json.loads(Path('public/news.json').read_text(encoding='utf-8'))['news']
    card = next((n for n in cards if n['id'] == card_id), None)
    if not card or not card.get('brief'): raise ValueError('Сначала нужен проверенный разбор')
    # Check scope before reserving an idempotency slot: permission errors must be retryable.
    with db() as c:
        existing = c.execute('SELECT * FROM tasks WHERE id=?', (card_id,)).fetchone()
    if existing:
        if existing['task_id']: return existing['task_id']
        raise ValueError('Результат прошлой попытки неясен; проверьте Б24 перед повтором')
    try:
        call('tasks.task.getFields', {})
    except Exception:
        raise ValueError('Вебхуку требуется право «Задачи». Ничего не создано; после добавления права можно повторить.') from None
    with LOCK, db() as c:
        existing = c.execute('SELECT * FROM tasks WHERE id=?', (card_id,)).fetchone()
        if existing:
            if existing['task_id']: return existing['task_id']
            raise ValueError('Результат прошлой попытки неясен; проверьте Б24 перед повтором')
        c.execute("INSERT INTO tasks VALUES(?,NULL,'creating','')", (card_id,))
    try:
        owner = call('user.current', {})
        responsible = int(os.environ.get('B24_RESPONSIBLE_ID') or owner['ID'])
        brief = card['brief']
        description = '\n'.join([brief['summary'], 'Почему важно: '+brief['priority_reason'],
            'Применимость: '+brief['impact'], 'Сроки из источника: '+brief['timing'],
            'Действия:', *['• '+a for a in brief['actions']], 'Источник: '+card['url'], 'RM-TASK-'+card_id])
        result = call('tasks.task.add', {'fields': {'TITLE':'Проверить изменение: '+card['title'][:180],
            'DESCRIPTION':description, 'RESPONSIBLE_ID':responsible}})
        task_id = int(result['task']['id'])
        with db() as c:
            c.execute("UPDATE tasks SET task_id=?,state='created' WHERE id=?", (task_id, card_id))
            url = f'https://sks-portal.bitrix24.ru/company/personal/user/{responsible}/tasks/task/view/{task_id}/'
            c.execute('INSERT OR IGNORE INTO outbox VALUES(?,?,?,?)', ('task-'+card_id,
                'Создана задача по материалу: '+card['title']+'\n'+url, 'pending',''))
        threading.Thread(target=deliver, daemon=True).start()
        return task_id
    except Exception:
        with db() as c: c.execute("UPDATE tasks SET state='uncertain',error='Проверьте Б24 перед повтором' WHERE id=?", (card_id,))
        raise ValueError('Не удалось подтвердить создание задачи. Проверьте права «Задачи» и журнал Б24.') from None


class BoundedServer(ThreadingHTTPServer):
    def __init__(self,*args,**kwargs):
        self.slots=threading.BoundedSemaphore(32)
        super().__init__(*args,**kwargs)
    def process_request(self,request,address):
        if not self.slots.acquire(blocking=False):
            try:request.sendall(b'HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
            finally:self.close_request(request)
            return
        try:super().process_request(request,address)
        except Exception:self.slots.release();raise
    def process_request_thread(self,request,address):
        try:super().process_request_thread(request,address)
        finally:self.slots.release()


class Handler(SimpleHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(15)
    def end_headers(self):
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        self.send_header('X-Frame-Options','DENY')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Permissions-Policy','camera=(), microphone=(), geolocation=()')
        super().end_headers()
    def do_HEAD(self):
        self.send_error(405)
    def __init__(self, *args, **kwargs): super().__init__(*args, directory=str(DATA/'public'), **kwargs)
    def log_message(self, *args): pass
    def owner(self):
        # Explicit passwordless owner mode: only this PC via literal loopback host.
        # Requiring both peer and Host prevents LAN clients and DNS rebinding from becoming owner.
        return AUTH is not None and AUTH.local(self.client_address[0]) and urlparse('http://'+self.headers.get('Host','')).hostname in ('localhost','127.0.0.1','::1')
    def list_directory(self,path):
        self.send_error(404)
        return None
    def reply(self, code, value):
        raw = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(code); self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(raw)))
        self.end_headers(); self.wfile.write(raw)
    def do_GET(self):
        route=urlparse(self.path).path
        if route=='/api/sources':
            from custom_sources import load
            return self.reply(200,{'sources':load()})
        if route == '/news.json':
            value=json.loads((DATA/'public/news.json').read_text(encoding='utf-8'))
            if not self.owner():
                value['settings']={};value['models']=[];value.pop('llmHealth',None)
                value['delivery']={'state':'private','text':'Управление уведомлениями доступно владельцу.'}
                value['status']={k:v for k,v in value.get('status',{}).items() if k in ('checked','sources','accepted','pending','needs_full_text')}
                for card in value.get('news',[]):
                    card.get('verification',{}).pop('receipts',None)
                    card.get('processing',{}).pop('error',None)
            return self.reply(200,value)
        if self.path == '/api/status':
            if not self.owner():
                return self.reply(200,{'owner':False,'available':True})
            from llm_health import report
            with db() as c:
                job = c.execute('SELECT * FROM jobs ORDER BY id DESC LIMIT 1').fetchone()
                schedule = c.execute("SELECT value FROM settings WHERE key='schedule'").fetchone()[0]
                pending = c.execute("SELECT count(*) FROM outbox WHERE state='pending'").fetchone()[0]
                history = [dict(row) for row in c.execute('SELECT * FROM jobs ORDER BY id DESC LIMIT 10')]
            return self.reply(200, {'owner':True,'token':TOKEN,'job':dict(job) if job else None,'schedule':schedule,
                'b24Configured':bool(os.environ.get('B24_WEBHOOK')),'pendingMessages':pending,'pid':os.getpid(),'runtime':'local' if os.name=='nt' else 'docker','health':report(persist=False),'history':history,
                'settings':json.loads((DATA/'monitor-settings.json').read_text(encoding='utf-8'))})
        if self.path.startswith('/api/'): return self.reply(404, {'error':'Not found'})
        allowed = {'/','/index.html','/app.css','/editorial.css','/readable.css','/minimal.css','/app.js','/material.js','/operations.js'}
        import re
        if route not in allowed and not re.fullmatch(r'/materials/[a-f0-9]+\.md',route):
            return self.reply(404,{'error':'Not found'})
        return super().do_GET()
    def do_POST(self):
        origin = self.headers.get('Origin')
        if origin and urlparse(origin).netloc != self.headers.get('Host'):
            return self.reply(403, {'error':'Недопустимый источник запроса'})
        if self.path in ('/api/login','/api/login-ticket','/api/login-code','/api/logout'):
            return self.reply(404,{'error':'Вход не требуется: управление доступно на этом ПК через localhost'})
        if not self.owner():
            return self.reply(403, {'error':'Управление доступно только владельцу'})
        if self.headers.get('X-Monitor-Token') != TOKEN:
            return self.reply(403, {'error':'Обновите страницу'})
        try:
            length = int(self.headers.get('Content-Length','0'))
            if not 0 <= length <= (24576 if self.path=='/api/model-test' else 4096): return self.reply(413, {'error':'Слишком большой запрос'})
            value = json.loads(self.rfile.read(length) or '{}')
            if not isinstance(value,dict):raise ValueError('Нужен объект параметров')
            if self.path == '/api/model-test':
                if not LAB_LOCK.acquire(blocking=False):return self.reply(429,{'error':'Один тест модели уже выполняется. Дождитесь ответа.'})
                try:
                    from model_lab import ask
                    result=ask(value.get('model'),value.get('message'),runner=run_model)
                    return self.reply(200,result)
                finally:LAB_LOCK.release()
            if self.path == '/api/check': return self.reply(202, {'job':start_job()})
            if self.path == '/api/sources':
                from custom_sources import add
                with LOCK: result=add(value.get('name'),value.get('url'),value.get('kind'))
                return self.reply(201,result)
            if self.path == '/api/backup':
                with LOCK,db() as c:
                    if c.execute("SELECT 1 FROM jobs WHERE state='running'").fetchone():
                        return self.reply(409,{'error':'Дождитесь окончания текущей проверки для согласованной резервной копии.'})
                    from runtime_backup import create_backup
                    return self.reply(200,create_backup(DATA))
            if self.path == '/api/schedule':
                enabled = 'on' if value.get('enabled') is True else 'off'
                with db() as c: c.execute("UPDATE settings SET value=? WHERE key='schedule'", (enabled,))
                return self.reply(200, {'schedule':enabled})
            if self.path == '/api/settings':
                from dashboard_export import MODELS
                if value.get('generator') not in MODELS or value.get('reviewer') not in MODELS or type(value.get('max_calls')) is not int or not 1 <= value['max_calls'] <= 5:
                    raise ValueError('Разрешены только бесплатные модели и лимит 1–5')
                config = {key:value[key] for key in ('generator','reviewer','max_calls')}
                temporary = DATA/'monitor-settings.tmp'
                temporary.write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
                temporary.replace(DATA/'monitor-settings.json')
                return self.reply(200, config)
            if self.path == '/api/task': return self.reply(200, {'taskId':create_task(value.get('id'))})
            if self.path == '/api/stop':
                self.reply(200, {'stopped':True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            return self.reply(404, {'error':'Not found'})
        except ValueError as exc: return self.reply(400, {'error':str(exc)})
        except Exception: return self.reply(500, {'error':'Операция не завершена; состояние сохранено'})


def scheduler():
    last = time.monotonic()
    while True:
        time.sleep(15)
        with db() as c: enabled = c.execute("SELECT value FROM settings WHERE key='schedule'").fetchone()[0] == 'on'
        if enabled and time.monotonic()-last >= 3600:
            start_job(); last = time.monotonic()


if __name__ == '__main__':
    init()
    threading.Thread(target=scheduler, daemon=True).start()
    server = BoundedServer((os.environ.get('MONITOR_BIND','0.0.0.0'),int(os.environ.get('MONITOR_PORT','8080'))),Handler)
    print('Мониторинг запущен. Сайт: http://localhost:'+str(server.server_port), flush=True)
    print('Расписание управляется на сайте. Ctrl+C останавливает процесс и его задания.', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        with CHILD_LOCK:
            for child in list(CHILDREN): stop_child(child)
        server.server_close()
        print('Мониторинг остановлен. Данные сохранены.', flush=True)

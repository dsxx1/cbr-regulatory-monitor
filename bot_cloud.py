"""Cloud-only Bitrix24 delivery. Credentials never leave the Actions runner."""
import argparse
import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError

PORTAL = 'sks-portal.bitrix24.ru'
DIALOG = 'chat374331'


class DeliveryBlocked(RuntimeError):
    """Expected configuration boundary, not a failed collection run."""


def report_delivery(state, text, delivered=False):
    Path('public').mkdir(exist_ok=True)
    Path('public/delivery.json').write_text(json.dumps({'state':state,'text':text,
        'verifiedAt':datetime.now(timezone.utc).isoformat()},ensure_ascii=False),encoding='utf-8')
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a',encoding='utf-8') as out:
            out.write('delivered='+('true' if delivered else 'false')+'\n')
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a',encoding='utf-8') as out:
            out.write('### Доставка в Б24\n\n'+text+'\n')


def call(method, params):
    base = os.environ.get('B24_WEBHOOK', '').rstrip('/')
    if urlparse(base).hostname != PORTAL or urlparse(base).scheme != 'https':
        raise RuntimeError('B24 target missing or does not match approved portal')
    request = Request(base+'/'+method+'.json', data=json.dumps(params).encode(),
                      headers={'Content-Type':'application/json'})
    try:
        with urlopen(request, timeout=30) as response:
            data = json.load(response)
    except HTTPError as exc:
        # Only controlled error code, never webhook URL or response description.
        try:
            code = json.load(exc).get('error','HTTP_ERROR')
        except Exception:
            code = 'HTTP_ERROR'
        if method=='imbot.v2.Bot.register' and str(code).lower()=='insufficient_scope':
            raise DeliveryBlocked('Сбор работает. Отправка в Б24 ожидает права «Чат-боты» (imbot). Сообщение сохранено.') from None
        raise RuntimeError(f'{method}: HTTP {exc.code} {str(code)[:80]}') from None
    except Exception as exc:
        raise RuntimeError(f'{method}: {type(exc).__name__}') from None
    if data.get('error'):
        if method=='imbot.v2.Bot.register' and str(data['error']).lower()=='insufficient_scope':
            raise DeliveryBlocked('Сбор работает. Отправка в Б24 ожидает права «Чат-боты» (imbot). Сообщение сохранено.')
        raise RuntimeError(f'{method}: {str(data["error"])[:80]}')
    return data.get('result')


def token():
    return hmac.new(os.environ['B24_WEBHOOK'].rstrip('/').encode(),
                    b'cbr-monitor-bot-v1', hashlib.sha256).hexdigest()[:40]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--probe', action='store_true')
    parser.add_argument('--check-delivery', action='store_true')
    parser.add_argument('--message', default='runtime/message.txt')
    args = parser.parse_args()
    if args.check_delivery:
        methods=call('methods',{})
        if isinstance(methods,dict): methods=methods.get('methods',[])
        if 'imbot.v2.bot.register' not in [str(m).lower() for m in methods]:
            raise DeliveryBlocked('Мониторинг и сайт работают. Для отправки ботом нужно право «Чат-боты» (imbot).')
        report_delivery('ready','Методы чат-бота доступны. Контрольная отправка ещё не выполнялась.')
        return
    if args.probe:
        methods = call('methods', {})
        if isinstance(methods, dict):
            methods = methods.get('methods', [])
        lower = [str(m).lower() for m in methods]
        print(json.dumps({'bot_register_available': 'imbot.v2.bot.register' in lower,
            'bot_send_available': 'imbot.v2.chat.message.send' in lower,
            'bot_methods': [m for m in methods if 'imbot' in str(m).lower()][:12],
            'chat_read_available': 'im.dialog.get' in methods}))
        chat = call('im.dialog.get', {'DIALOG_ID':DIALOG})
        print(json.dumps({'chat_verified':str(chat.get('id')) == '374331',
                          'chat_title':chat.get('name', chat.get('title',''))}, ensure_ascii=False))
        return
    message = Path(args.message).read_text(encoding='utf-8')
    if not message.strip():
        print('Nothing to send')
        return
    registered = call('imbot.v2.Bot.register', {'fields':{'code':'cbr_regulatory_monitor_v1',
        'botToken':token(), 'eventMode':'fetch','type':'bot',
        'properties':{'name':'Мониторинг регулирования','workPosition':'ЦБ · ломбарды · проверяемые источники'}}})
    bot_id = registered['bot']['id']
    members = call('im.chat.user.list', {'CHAT_ID':374331})
    if str(bot_id) not in [str(x) for x in members]:
        call('im.chat.user.add', {'CHAT_ID':374331,'USERS':[bot_id],'HIDE_HISTORY':'Y'})
    key = 'RM-CLOUD-'+hashlib.sha256(message.encode()).hexdigest()[:20]
    previous = call('im.dialog.messages.get', {'DIALOG_ID':DIALOG,'LIMIT':50})
    for item in previous.get('messages', []):
        if key in item.get('text','') and str(item.get('author_id')) == str(bot_id):
            print('Already delivered; no duplicate')
            report_delivery('delivered','Сообщение уже найдено в чате, повторно не отправлено.',True)
            return
    result = call('imbot.v2.Chat.Message.send', {'botId':bot_id,'botToken':token(),
        'dialogId':DIALOG,'fields':{'message':message[:19000]+'\n'+key,'urlPreview':False}})
    if not isinstance(result,dict) or not isinstance(result.get('id'),int):
        raise RuntimeError('No confirmed message ID; do not retry blindly')
    history = call('im.dialog.messages.get', {'DIALOG_ID':DIALOG,'LIMIT':20})
    verified = any(str(m.get('id')) == str(result['id']) and str(m.get('author_id')) == str(bot_id)
                   for m in history.get('messages',[]))
    print(json.dumps({'delivered':True,'read_back_verified':verified,'message_id':result['id'],'bot_id':bot_id}))
    if not verified:
        raise RuntimeError('Message accepted, but read-back not verified; inspect chat before retry')
    report_delivery('delivered','Сообщение отправлено ботом и найдено при повторном чтении чата.',True)


if __name__ == '__main__':
    try:
        main()
    except DeliveryBlocked as exc:
        report_delivery('blocked',str(exc))
        print(str(exc))
    except RuntimeError as exc:
        report_delivery('error','Не удалось подтвердить доставку. Проверьте журнал запуска; сообщение сохранено.')
        print(str(exc))
        raise SystemExit(1)

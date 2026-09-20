"""Owner-only free-model smoke chat. Prompts and responses are not persisted."""
import json
import re
import subprocess
import time
from pathlib import Path

MODELS=['kilo-auto/free','inclusionai/ling-3.0-flash-vl:free','poolside/laguna-s-2.1:free']


def validate(model,message):
    if model not in MODELS: raise ValueError('Выберите разрешённую бесплатную модель')
    if not isinstance(message,str) or not 1<=len(message.strip())<=4000:
        raise ValueError('Сообщение должно содержать от 1 до 4000 символов')
    if re.search(r'/rest/\d+/[A-Za-z0-9_-]+|-----BEGIN .*PRIVATE KEY|\bsk-[A-Za-z0-9_-]{15,}',message):
        raise ValueError('Похоже, в тексте есть секрет. Уберите ключ или вебхук перед отправкой.')


def ask(model,message,runner=None):
    validate(model,message)
    payload={'model':model,'_strict_model':model!='kilo-auto/free',
        'messages':[{'role':'system','content':'Отвечай по-русски, кратко и по существу. Не выдавай предположения за проверенные факты.'},
                    {'role':'user','content':message.strip()}],
        'max_tokens':3000,'temperature':0,'usage':{'include':True}}
    started=time.monotonic()
    try:
        result=(runner or subprocess.run)(['node',str(Path(__file__).with_name('free_llm_transport.mjs'))],
            input=json.dumps(payload),text=True,encoding='utf-8',capture_output=True,timeout=180)
    except subprocess.TimeoutExpired:
        raise ValueError('Модель не ответила за 180 секунд. Повторите позднее.') from None
    if result.returncode:
        raw=result.stderr
        reason='Достигнут бесплатный лимит провайдера.' if '429' in raw else 'Ответ оборвался по лимиту.' if 'truncated' in raw else 'Не удалось подтвердить бесплатную цену.' if 'price not verified' in raw else 'Бесплатный маршрут временно недоступен или не ответил вовремя.'
        raise ValueError(reason+' Платная модель не подключалась.')
    try:
        envelope=json.loads(result.stdout); answer=envelope['result'];usage=answer.get('usage',{})
        text=answer['choices'][0]['message']['content']
        if not isinstance(text,str) or not text.strip(): raise ValueError()
        return {'answer':text,'requested':model,'route':envelope['route'],'actualModel':answer.get('model','Не сообщена'),
            'seconds':round(time.monotonic()-started,1),'tokens':usage.get('total_tokens'),
            'cost':usage.get('cost'),'fallbacks':len(envelope.get('attempts',[])),'priceChecked':True}
    except (ValueError,KeyError,TypeError):
        raise ValueError('Провайдер вернул непонятный ответ. Он не считается успешным тестом.') from None

"""Keyless zero-priced route; no paid fallback, local service or credentials."""
import json
import urllib.request
import subprocess
from pathlib import Path
from decimal import Decimal

from analyze import Analyzer, SYSTEM_PROMPT

CATALOG = 'https://api.kilo.ai/api/gateway/models'
ENDPOINT = 'https://api.kilo.ai/api/gateway/v1/chat/completions'
MODEL = 'kilo-auto/free'


def verify_price(catalog, model_id=MODEL):
    model = next((m for m in catalog.get('data', []) if m.get('id') == model_id), None)
    if not model:
        raise ValueError('Free model absent from live catalog')
    pricing = model.get('pricing', {})
    if not all(k in pricing for k in ('prompt', 'completion')) or any(Decimal(str(v)) != 0 for v in pricing.values()):
        raise ValueError('Nonzero or unknown price: request blocked')
    return pricing


class FreeAnalyzer(Analyzer):
    def __init__(self, max_calls=3):
        # Do not load legacy API keys/configuration, even if they exist.
        self.model = MODEL
        self.max_calls = max_calls
        self.calls = self.rejected_claims = self.fallbacks = self.throttled = 0
        self.errors = []
        self.receipts = []
        self.timeout = 90
        self.system_prompt = SYSTEM_PROMPT + '\nВерни не больше трёх требований. Пиши кратко; суммарный ответ до 2000 символов. Не выдавай рассуждения вне JSON.'

    @property
    def enabled(self):
        return True

    def _call(self, text):
        if len(text)>65000:
            raise ValueError('Input too long; silent truncation prohibited')
        payload = {'model': self.model, 'messages': [
            {'role': 'system', 'content': getattr(self, 'system_prompt', SYSTEM_PROMPT)},
            {'role': 'user', 'content': '<document>\n' + text + '\n</document>'}],
            'max_tokens': 6000, 'temperature': 0, 'usage': {'include': True}}
        completed = subprocess.run(['node', str(Path(__file__).with_name('free_llm_transport.mjs'))],
            input=json.dumps(payload), text=True, encoding='utf-8', capture_output=True, timeout=180)
        if completed.returncode:
            raise RuntimeError(completed.stderr[:250])
        envelope = json.loads(completed.stdout)
        result, pricing = envelope['result'], envelope['pricing']
        verify_price({'data': [{'id': self.model, 'pricing': pricing}]}, self.model)
        self.receipts.append({'model': result.get('model'), 'pricing': pricing,'route':envelope.get('route',self.model),'attempts':envelope.get('attempts',[]),
                              'usage': result.get('usage', {})})
        cost = result.get('usage', {}).get('cost')
        if cost is not None and Decimal(str(cost)) != 0:
            self.max_calls = self.calls
            raise ValueError('Provider reported nonzero cost; further calls blocked')
        if result.get('error'):
            raise ValueError('Free provider rejected request')
        if result['choices'][0].get('finish_reason') == 'length':
            raise ValueError('Truncated model response')
        return self._extract_json(result['choices'][0]['message']['content'])

    def analyze(self, text):
        try:
            return super().analyze(text)
        except (TypeError, ValueError, AttributeError, KeyError):
            self.errors.append('Invalid model schema')
            return None

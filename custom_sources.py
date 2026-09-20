"""Owner-managed public RSS feeds and explicit webpage-change monitoring."""
import hashlib
import ipaddress
import json
import socket
import ssl
import http.client
import re
from pathlib import Path
from datetime import datetime,timezone
from urllib.parse import urlparse,urljoin,quote
from urllib.request import urlopen
from sources import Document,parse_rss

FILE=Path('custom-sources.json')


def addresses_for(host):
    try:addresses=list(dict.fromkeys(a[4][0] for a in socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)))
    except OSError:raise ValueError('Не удалось определить адрес сайта') from None
    fake=ipaddress.ip_network('198.18.0.0/15')
    if addresses and all(ipaddress.ip_address(a) in fake for a in addresses):
        # FlClash fake-IP mode. Resolve the public hostname, never trust fake-IP as a public endpoint.
        try:ipaddress.ip_address(host)
        except ValueError:
            with urlopen('https://dns.google/resolve?name='+quote(host,safe='')+'&type=A',timeout=10) as response:
                answer=json.load(response)
            addresses=[r['data'] for r in answer.get('Answer',[]) if r.get('type')==1]
    if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):
        raise ValueError('Внутренние и служебные адреса нельзя добавлять как источник новостей')
    return addresses


def public_url(url):
    value=urlparse(url)
    if value.scheme!='https' or not value.hostname or value.username or value.password or value.port not in (None,443):
        raise ValueError('Нужен публичный HTTPS-адрес без пароля и нестандартного порта')
    if re.search(r'(?:^|&)(?:api[_-]?key|token|password|secret|auth)=',value.query,re.I):
        raise ValueError('Адрес источника не должен содержать ключи доступа')
    addresses_for(value.hostname)
    return url


def fetch(url):
    for _ in range(6):
        public_url(url);parsed=urlparse(url)
        addresses=addresses_for(parsed.hostname)
        # Pin the validated IP; TLS still validates the original hostname.
        class Connection(http.client.HTTPSConnection):
            def connect(self):
                self.sock=self._context.wrap_socket(socket.create_connection((addresses[0],443),self.timeout),server_hostname=self.host)
        connection=Connection(parsed.hostname,timeout=20,context=ssl.create_default_context())
        try:
            target=parsed.path or '/'
            if parsed.query:target+='?'+parsed.query
            connection.request('GET',target,headers={'User-Agent':'RegulatoryMonitor/1.0'})
            response=connection.getresponse()
            if response.status in (301,302,303,307,308):
                url=urljoin(url,response.getheader('Location',''));continue
            if response.status!=200:raise ValueError('Сайт вернул HTTP '+str(response.status))
            raw=response.read(2_000_001)
            if len(raw)>2_000_000:raise ValueError('Страница превышает лимит 2 МБ')
            return raw,response.headers.get_content_charset() or 'utf-8',response.headers.get_content_type()
        finally:connection.close()
    raise ValueError('Слишком много перенаправлений')


def load():
    return json.loads(FILE.read_text(encoding='utf-8')) if FILE.exists() else []


def add(name,url,kind):
    if not isinstance(name,str) or not 2<=len(name.strip())<=100:raise ValueError('Название: от 2 до 100 символов')
    if not isinstance(url,str) or len(url)>2000:raise ValueError('Слишком длинный адрес')
    if kind not in ('rss','page'):raise ValueError('Выберите RSS или веб-страницу')
    public_url(url)
    values=load()
    if len(values)>=30:raise ValueError('Достигнут лимит 30 дополнительных источников')
    if any(v['url'].rstrip('/')==url.rstrip('/') for v in values):raise ValueError('Этот адрес уже добавлен')
    record={'id':hashlib.sha256(url.encode()).hexdigest()[:16],'name':name.strip(),'url':url,'kind':kind,'added':datetime.now(timezone.utc).isoformat()}
    values.append(record);tmp=FILE.with_suffix('.tmp');tmp.write_text(json.dumps(values,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(FILE)
    return record


def html_text(raw,charset):
    from material_analysis import Text
    markup=raw.decode(charset,errors='replace')
    main=re.search(r'<(?:main|article)\b[^>]*>(.*?)</(?:main|article)>',markup,re.I|re.S)
    parser=Text();parser.feed(main[1] if main else markup)
    return '\n'.join(line.strip() for line in ''.join(parser.parts).splitlines() if line.strip())


def collect():
    documents=[];report=[]
    for source in load():
        try:
            raw,charset,mime=fetch(source['url'])
            if source['kind']=='rss':
                items=parse_rss(raw,'custom-rss-'+source['id'],source['name'])[:20]
                if not items:raise ValueError('RSS не содержит элементов item; Atom пока не поддерживается')
                for item in items:
                    if urlparse(item.url).hostname!=urlparse(source['url']).hostname:continue
                    item.body='';item.in_perimeter=True;documents.append(item)
            else:
                if mime not in ('text/html','text/plain'):raise ValueError('Для страницы нужен HTML или обычный текст')
                text=html_text(raw,charset)
                if len(text)<120:raise ValueError('Недостаточно текста; возможно, сайт требует JavaScript')
                digest=hashlib.sha256(text.encode()).hexdigest()[:16]
                documents.append(Document(key='custom-page:'+source['id']+':'+digest,source='custom-page',source_title=source['name'],external_id=digest,
                    title='Снимок изменений страницы: '+source['name'],body=text,url=source['url'],in_perimeter=True))
            count=sum(d.source_title==source['name'] for d in documents)
            report.append({'name':source['name'],'url':source['url'],'status':'ok','detail':f'Материалов в окне: {count}'})
        except Exception as error:
            report.append({'name':source['name'],'url':source['url'],'status':'error','detail':type(error).__name__+': '+str(error)[:150]})
    return documents,report

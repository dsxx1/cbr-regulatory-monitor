"""Durable bounded backlog worker. Runs on GitHub, never sends chat messages."""
import argparse
import json
import time
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from pathlib import Path

from material_analysis import fetch_text, analyze_material

FOCUS=['sro:/1000018365.html','sro:/1000018351.html','sro:/1000018312.html']


def read(path,default):
    p=Path(path)
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else default


def save(path,value):
    p=Path(path);tmp=p.with_suffix(p.suffix+'.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(p)


def catalog():
    records={d['key']:d for d in read('news-catalog.json',[])}
    cloud=read('cloud-state.json',{})
    for field in ('queue','needs_full_text'):
        for doc in cloud.get(field,{}).values(): records[doc['key']]=doc
    return records


def retryable(record,now):
    if record.get('state')=='verified':return False
    if record.get('state')=='needs_operator':return False
    return not record.get('retry_at') or record['retry_at']<=now


def order(doc):
    key=doc['key']
    if key in FOCUS:return (0,FOCUS.index(key),'')
    stamp=doc.get('published') or doc.get('modification','')
    ordinal=0
    for fmt in ('%Y-%m-%d','%d.%m.%Y'):
        try:ordinal=datetime.strptime(stamp[:10],fmt).toordinal();break
        except ValueError:pass
    # Editorial priority only orders work. It never sets published importance.
    relevant=any(t in doc['title'].lower() for t in ('отчет','отчёт','пск','клейм','приказ','цифров','учет','учёт'))
    return (1 if relevant else 2,-ordinal,key)


def process(doc,cached,model_config=None):
    item=dict(doc)
    try:
        if cached.get('body'):item['body']=cached['body']
        if len(item.get('body',''))<120:item['body']=fetch_text(item['url'])
    except Exception as exc:
        return item,None,'source',type(exc).__name__+': '+str(exc)[:180]
    try:
        if model_config is None:
            from dashboard_export import settings
            model_config=settings()
        result=analyze_material(item,model_config['generator'],model_config['reviewer'])
        return item,result,'ok',''
    except Exception as exc:
        return item,None,'model',type(exc).__name__+': '+str(exc)[:180]


def main():
    p=argparse.ArgumentParser();p.add_argument('--limit',type=int,default=6);p.add_argument('--workers',type=int,default=2)
    p.add_argument('--hydrate-only',action='store_true');p.add_argument('--focus-only',action='store_true')
    p.add_argument('--checkpoint-git',action='store_true');args=p.parse_args()
    if args.checkpoint_git and os.environ.get('GITHUB_REPOSITORY')!='dsxx1/cbr-regulatory-monitor':
        raise ValueError('Git checkpoints are allowed only in this project Actions runner')
    now=datetime.now(timezone.utc).isoformat();docs=catalog()
    from dashboard_export import settings
    model_config=settings()
    queue=read('analysis-queue.json',{'items':{}});items=queue['items']
    cache=read('source-cache.json',{});briefs=read('material-briefs.json',{})
    cache={k:v for k,v in cache.items() if v.get('extracted') or len(v.get('body',''))>=120}
    for key in docs:
        record=items.setdefault(key,{'state':'pending','attempts':0})
        if briefs.get(key,{}).get('brief_verified'):record['state']='verified'
    todo=[d for d in sorted(docs.values(),key=order) if retryable(items[d['key']],now)]
    if args.focus_only:todo=[d for d in todo if d['key'] in FOCUS]
    if args.hydrate_only:
        todo=[d for d in docs.values() if not cache.get(d['key'],{}).get('body') and not briefs.get(d['key'],{}).get('body')][:args.limit]
    else:todo=todo[:max(0,min(args.limit,12))]
    queue['last_started']=now
    save('analysis-queue.json',queue);save('source-cache.json',cache);save('material-briefs.json',briefs)
    def work(doc):
        if not args.hydrate_only:return process(doc,cache.get(doc['key'],{}),model_config)
        item=dict(doc)
        try:
            if len(item.get('body',''))<120:item['body']=fetch_text(item['url'])
            return item,None,'hydrated',''
        except Exception as exc:return item,None,'source',type(exc).__name__+': '+str(exc)[:180]
    with ThreadPoolExecutor(max_workers=max(1,min(args.workers,4))) as pool:
        futures={pool.submit(work,d):d['key'] for d in todo}
        for task in as_completed(futures):
            key=futures[task];doc,result,stage,error=task.result();record=items[key]
            record['last_attempt']=datetime.now(timezone.utc).isoformat()
            if doc.get('body') and stage!='source':cache[key]={'body':doc['body'],'extracted':True,'fetched':record['last_attempt'],'url':doc['url']}
            if result:
                briefs[key]=result;record.update(state='verified',error='',retry_at=None)
            elif stage!='hydrated':
                record['attempts']+=1;record['error']=error;record['failure_stage']=stage
                # Failed extraction and exhausted model retries remain visible; never silently disappear.
                record['state']='needs_operator' if record['attempts']>=5 else 'retry'
                record['retry_at']=(datetime.now(timezone.utc)+timedelta(minutes=min(1440,30*2**(record['attempts']-1)))).isoformat()
            print(json.dumps({'key':key,'stage':stage,'state':record['state'],'error':error},ensure_ascii=False),flush=True)
            save('source-cache.json',cache);save('material-briefs.json',briefs);save('analysis-queue.json',queue)
            if args.checkpoint_git:
                subprocess.run(['git','add','source-cache.json','material-briefs.json','analysis-queue.json'],check=True)
                changed=subprocess.run(['git','diff','--staged','--quiet']).returncode
                if changed:
                    subprocess.run(['git','commit','-q','-m','Backlog checkpoint: '+key],check=True)
                    subprocess.run(['git','push','-q','origin','HEAD:main'],check=True)
    queue['last_finished']=datetime.now(timezone.utc).isoformat()
    queue['counts']={state:sum(r['state']==state for r in items.values()) for state in ('pending','retry','verified','needs_operator')}
    queue['total']=len(items)
    save('analysis-queue.json',queue)
    print(json.dumps(queue['counts'],ensure_ascii=False))


if __name__=='__main__':main()

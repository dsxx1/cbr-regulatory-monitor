// Built-in fetch only. Public document in stdin; no credentials or paid fallback.
import {mkdirSync, writeFileSync} from 'node:fs';
import {randomUUID} from 'node:crypto';
let eventCount=0,requestedModel='catalog',requestStarted=Date.now();
function record(route,status,started,reason='') {
  eventCount++;
  const event={id:randomUUID(),at:new Date().toISOString(),route,status,ms:Date.now()-started,reason};
  mkdirSync('out/llm-events',{recursive:true});
  writeFileSync(`out/llm-events/${event.id}.json`,JSON.stringify(event));
}
let input = '';
for await (const part of process.stdin) input += part;
try {
  const {_strict_model=false,...payload} = JSON.parse(input);
  requestedModel=payload.model;
  if (!['kilo-auto/free','inclusionai/ling-3.0-flash-vl:free','poolside/laguna-s-2.1:free'].includes(payload.model)) throw new Error('Model not allowed');
  const catalogReply = await fetch('https://api.kilo.ai/api/gateway/models', {signal: AbortSignal.timeout(20000)});
  if (!catalogReply.ok) throw new Error(`Catalog HTTP ${catalogReply.status}`);
  const catalog = await catalogReply.json();
  const routes=_strict_model?[payload.model]:[...new Set([payload.model,'poolside/laguna-s-2.1:free','inclusionai/ling-3.0-flash-vl:free'])];
  const attempts=[];let envelope;
  for(const id of routes){
    const started=Date.now();
    const model=catalog.data?.find(m=>m.id===id);
    if(!model || !['prompt','completion'].every(k=>/^0(?:\.0+)?$/.test(String(model.pricing?.[k]))) || Object.values(model.pricing).some(v=>!/^0(?:\.0+)?$/.test(String(v)))){record(id,'failed',started,'price_unknown');attempts.push({route:id,error:'price not verified'});continue;}
    try{
      const response=await fetch('https://api.kilo.ai/api/gateway/v1/chat/completions',{
        method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...payload,model:id}),signal:AbortSignal.timeout(45000)});
      if(!response.ok)throw new Error(`HTTP ${response.status}`);
      const result=await response.json();
      if(result.usage?.cost!=null && Number(result.usage.cost)!==0)throw new Error('NONZERO_COST');
      if(result.error || !result.choices?.[0]?.message?.content)throw new Error('empty response');
      if(result.choices[0].finish_reason==='length')throw new Error('truncated response');
      record(id,'response',started);
      envelope={result,pricing:model.pricing,route:id,attempts};break;
    }catch(error){record(id,'failed',started,error.message==='NONZERO_COST'?'cost':/429/.test(error.message)?'rate_limit':error.name==='TimeoutError'?'timeout':error.message==='truncated response'?'truncated':'provider_error');if(error.message==='NONZERO_COST')throw error;attempts.push({route:id,error:error.name+': '+error.message});}
  }
  if(!envelope)throw new Error('Free routes unavailable: '+JSON.stringify(attempts));
  process.stdout.write(JSON.stringify(envelope));
} catch (error) {
  if(!eventCount)record(requestedModel,'failed',requestStarted,'catalog_or_request_error');
  process.stderr.write(`Free provider failure: ${error.name}: ${error.message}`);
  process.exitCode = 1;
}

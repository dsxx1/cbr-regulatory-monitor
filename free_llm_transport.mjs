// Built-in fetch only. Public document in stdin; no credentials or paid fallback.
let input = '';
for await (const part of process.stdin) input += part;
try {
  const payload = JSON.parse(input);
  if (!['kilo-auto/free','inclusionai/ling-3.0-flash-vl:free'].includes(payload.model)) throw new Error('Model not allowed');
  const catalogReply = await fetch('https://api.kilo.ai/api/gateway/models', {signal: AbortSignal.timeout(20000)});
  if (!catalogReply.ok) throw new Error(`Catalog HTTP ${catalogReply.status}`);
  const catalog = await catalogReply.json();
  const model = catalog.data?.find(m => m.id === payload.model);
  if (!model || String(model.pricing?.prompt) !== '0' || String(model.pricing?.completion) !== '0' || Object.values(model.pricing).some(v => !/^0(?:\.0+)?$/.test(String(v)))) throw new Error('Price unknown or nonzero');
  const response = await fetch('https://api.kilo.ai/api/gateway/v1/chat/completions', {
    method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload),
    signal: AbortSignal.timeout(90000)});
  if (!response.ok) throw new Error(`Completion HTTP ${response.status}`);
  const result = await response.json();
  process.stdout.write(JSON.stringify({result, pricing: model.pricing}));
} catch (error) {
  process.stderr.write(`Free provider failure: ${error.name}: ${error.message}`);
  process.exitCode = 1;
}

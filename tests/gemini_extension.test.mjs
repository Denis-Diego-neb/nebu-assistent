import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
const source = fs.readFileSync(new URL('../browser_extension/background.js', import.meta.url), 'utf8');
const job = {job_id:'sprint_test',fingerprint:'v1',content_sha256:'a'.repeat(64),prompt:'prompt'};
function boot(store = {}, opts = {}) {
    let listener;
    let injections = 0;
    let deliveries = 0;
    let created = 0;
    let removed = 0;
    const chrome = {
        storage:{local:{get:async key=>structuredClone(store),set:async data=>Object.assign(store,structuredClone(data)),setAccessLevel:async()=>{}}},
        tabs:{create:async()=>{created++;return {id:99};},get:async id=>opts.closedTab ? Promise.reject(new Error('Closed')) : {id,url:'https://gemini.google.com/app'},remove:async()=>{removed++;},query:async()=>opts.noTab ? [] : [{id:7,active:true}],sendMessage:async(id,msg)=>{deliveries++;if(opts.deliveryFails || (opts.missingReceiver && deliveries === 1)) throw new Error('Receiving end does not exist');if(msg.type==='NEBULA_AUTO_STEP') { assert.equal(id,99); return opts.autoResult || {accepted:true}; }return msg.type === 'NEBULA_PING' ? {ok:true} : {accepted:true};}},
        scripting:{executeScript:async()=>{injections++;}},
        runtime:{id:'extension',getURL:path=>'chrome-extension://extension/'+path,onMessage:{addListener:fn=>listener=fn},onInstalled:{addListener(){}},onStartup:{addListener(){}}},
        alarms:{get:async()=>true,create:async()=>{},onAlarm:{addListener(){}}}
    };
    let submissions = 0;
    const fetch = async(url, req)=> {
        if (url.endsWith('/gemini/result')) {submissions++; if(opts.offline) throw new Error('Offline');if(opts.resultStatus && opts.resultStatus!==200) return {ok:false,status:opts.resultStatus,json:async()=>({error:opts.resultError||'erro'})};return {ok:true,status:200,json:async()=>({ok:true})};}
        const next = opts.jobs?.[submissions] || job;
        return {ok:true,status:opts.empty || (opts.jobs && !opts.jobs[submissions]) ? 204 : 200,json:async()=>structuredClone(next)};
    };
    vm.runInNewContext(source,{chrome,fetch,AbortSignal,console});
    return {
        call:(message,sender={id:'extension',url:'chrome-extension://extension/popup.html'})=>new Promise(resolve=>listener(message,sender,resolve)),
        store, opts, count:()=>submissions, injections:()=>injections, created:()=>created, removed:()=>removed
    };
}
test('token and prompt never returned to foreign senders',async()=>{
    const app = boot();
    const reply = await app.call({type:'CONFIGURE',token:'t'.repeat(40)});
    assert.equal(reply.ok,true); assert.equal(reply.token,undefined);
    assert.equal((await app.call({type:'STATE'},{id:'extension',tab:{id:7},url:'https://gemini.google.com/app'})).ok,false);
});
test('no tab does not consume queue; later delivery succeeds',async()=>{
    const app=boot({}, {noTab:true});
    let reply=await app.call({type:'CONFIGURE',token:'t'.repeat(40)});
    assert.equal(reply.job,null);
    app.opts.noTab=false;
    reply=await app.call({type:'POLL'});
    assert.equal(reply.job.job_id,job.job_id);
});
test('pending response survives worker restart and is retried',async()=>{
    const app=boot({}, {offline:true});
    await app.call({type:'CONFIGURE',token:'t'.repeat(40)});
    let reply=await app.call({type:'RESULT',job,response:'{"summary":"response"}'});
    assert.equal(reply.pending,true);
    const restarted=boot(app.store,{empty:true});
    await restarted.call({type:'POLL'});
    reply=await restarted.call({type:'STATE'});
    assert.equal(reply.pending,false); assert.equal(reply.job,null);
    assert.equal(restarted.count(),1);
});
test('mismatched content never submitted',async()=>{
    const app=boot();
    await app.call({type:'CONFIGURE',token:'t'.repeat(40)});
    const reply=await app.call({type:'RESULT',job:{...job,content_sha256:'old'},response:'{}'});
    assert.equal(reply.ok,false); assert.equal(app.count(),0);
});
test('draft persists and reset clears only local state',async()=>{
    const app=boot();
    await app.call({type:'CONFIGURE',token:'t'.repeat(40)});
    await app.call({type:'DRAFT',job,response:'partial JSON'});
    assert.equal((await app.call({type:'STATE'})).draft,'partial JSON');
    const result=await app.call({type:'RESET'});
    assert.equal(result.job,null); assert.equal(result.draft,'');assert.equal(app.count(),0);
});
test('injects content script when Gemini receiver is missing',async()=>{
    const app=boot({}, {missingReceiver:true,empty:true});
    const reply=await app.call({type:'CONFIGURE',token:'t'.repeat(40)});
    assert.equal(reply.ok,true); assert.equal(reply.error,''); assert.equal(app.injections(),1);
});

test('automatic review reuses its conversation and posts each captured response',async()=>{
    const second = {...job,job_id:'sprint_second',fingerprint:'v2'};
    const app=boot({}, {noTab:true,jobs:[job,second]});
    await app.call({type:'CONFIGURE',token:'t'.repeat(40)});
    let result=await app.call({type:'AUTO',enabled:true});
    assert.equal(result.auto,true);
    assert.equal(app.store.nebulaBridgeState.autoTabId,99);
    app.opts.autoResult={response:'{"verdict":"revise"}'};
    result=await app.call({type:'POLL'});
    assert.equal(result.pending,false);
    assert.equal(app.count(),1);
    assert.equal(app.created(),1);
    assert.equal(app.removed(),0);
    app.opts.autoResult={accepted:true};
    result=await app.call({type:'POLL'});
    assert.equal(result.job.job_id,second.job_id);
    assert.equal(app.created(),1);
    app.opts.autoResult={response:'{"verdict":"approved"}'};
    await app.call({type:'POLL'});
    assert.equal(app.count(),2);
    assert.equal(app.removed(),0);
});

test('a single automatic DOM error keeps retrying and keeps the candidate',async()=>{
    // Um erro isolado nao pode derrubar o automatico: com dezenas de jobs
    // pendentes, uma falha passageira (aba recarregando, campo mudou) parava
    // a fila inteira ate alguem reabrir o popup e ligar de novo a mao.
    const app=boot();
    await app.call({type:'CONFIGURE',token:'t'.repeat(40)});
    await app.call({type:'AUTO',enabled:true});
    app.opts.autoResult={error:'Campo mudou'};
    const result=await app.call({type:'POLL'});
    assert.equal(result.auto,true);
    assert.equal(result.job.job_id,job.job_id);
    assert.equal(result.error,'Campo mudou');
    assert.equal(app.count(),0);
});

test('automatic mode gives up only after several consecutive failures',async()=>{
    const app=boot();
    await app.call({type:'CONFIGURE',token:'t'.repeat(40)});
    await app.call({type:'AUTO',enabled:true});
    app.opts.autoResult={error:'Campo mudou'};
    let result;
    for(let i=0;i<4;i++){
        result=await app.call({type:'POLL'});
        assert.equal(result.auto,true,`ainda deveria tentar na falha ${i+1}`);
    }
    result=await app.call({type:'POLL'});
    assert.equal(result.auto,false,'desliga na quinta falha seguida');
});

test('a success between failures resets the streak',async()=>{
    const app=boot();
    await app.call({type:'CONFIGURE',token:'t'.repeat(40)});
    await app.call({type:'AUTO',enabled:true});
    app.opts.autoResult={error:'Campo mudou'};
    for(let i=0;i<4;i++) await app.call({type:'POLL'});
    app.opts.autoResult={accepted:true};
    const recovered=await app.call({type:'POLL'});
    assert.equal(recovered.auto,true);
    app.opts.autoResult={error:'Campo mudou'};
    for(let i=0;i<4;i++){
        const result=await app.call({type:'POLL'});
        assert.equal(result.auto,true,'a sequencia recomecou apos o sucesso');
    }
});

test('a stale job rejected by the bridge (409) is dropped instead of retried forever',async()=>{
    // O bridge devolve 409 quando o fingerprint do job mudou (autopilot
    // reprocessou) ou a resposta ja foi registrada. Sem descartar, o
    // automatico ficaria repetindo o mesmo job morto ate desligar sozinho.
    const app=boot({},{resultStatus:409,resultError:'Resposta pertence a uma versao antiga da sprint.'});
    await app.call({type:'CONFIGURE',token:'t'.repeat(40)});
    await app.call({type:'AUTO',enabled:true});
    app.opts.autoResult={response:'{"verdict":"revise"}'};
    const result=await app.call({type:'POLL'});
    assert.equal(result.auto,true);
    assert.equal(result.job,null);
    assert.equal(result.pending,false);
    assert.match(result.error,/versao antiga/);
});

test('automatic result stays pending when the bridge is offline and retries later',async()=>{
    const app=boot({}, {offline:true});
    await app.call({type:'CONFIGURE',token:'t'.repeat(40)});
    await app.call({type:'AUTO',enabled:true});
    app.opts.autoResult={response:'{"verdict":"revise"}'};
    let result=await app.call({type:'POLL'});
    // A ponte offline e transitoria: o automatico continua tentando sozinho
    // em vez de esperar alguem reabrir o popup.
    assert.equal(result.auto,true);
    assert.equal(result.pending,true);
    assert.equal(result.job.job_id,job.job_id);
    app.opts.offline=false;
    app.opts.empty=true;
    result=await app.call({type:'POLL'});
    assert.equal(result.pending,false);
    assert.equal(app.count(),2);
    assert.equal(app.removed(),0);
});

test('closed tab during a submitted review retries without resending the job',async()=>{
    const app=boot();
    await app.call({type:'CONFIGURE',token:'t'.repeat(40)});
    await app.call({type:'AUTO',enabled:true});
    app.opts.autoResult={phase:'submitted'};
    await app.call({type:'POLL'});
    app.opts.closedTab=true;
    const result=await app.call({type:'POLL'});
    // A aba pode voltar (recriada, extensao recarregada); continuar tentando
    // e mais util do que exigir uma volta ao popup, e nada e reenviado.
    assert.equal(result.auto,true);
    assert.equal(result.job.job_id,job.job_id);
    assert.equal(app.created(),1);
    assert.equal(app.count(),0);
});

test('content script captures only the latest response in a reused conversation',async()=>{
    const content = fs.readFileSync(new URL('../browser_extension/content_gemini.js', import.meta.url), 'utf8');
    let listener;
    let now = 1000;
    let stored = null;
    const responses = [];
    const editor = {innerText:'',focus(){},dispatchEvent(){}};
    const send = {disabled:false,getAttribute:()=> 'Send message',click(){editor.innerText='';}};
    const document = {
        querySelector:()=>editor,
        querySelectorAll:selector=>selector==='button' ? [send] : selector==='model-response-content' ? responses : [],
        execCommand:(_, __, value)=>{editor.innerText=value;}
    };
    const chrome = {runtime:{id:'extension',onMessage:{addListener:fn=>listener=fn},sendMessage:()=>Promise.resolve()}};
    const sessionStorage = {getItem:()=>stored,setItem:(_,value)=>{stored=value;}};
    const location = {href:'https://gemini.google.com/app/chat-1'};
    vm.runInNewContext(content,{chrome,document,sessionStorage,Date:{now:()=>now},InputEvent:class {},setTimeout,location});
    const step = request=>new Promise(resolve=>listener({type:'NEBULA_AUTO_STEP',job:request},{id:'extension'},resolve));
    const response = verdict=>({innerText:JSON.stringify({verdict,summary:'ok',rewards:{worker_4b:1,reviewer_9b:1}}),querySelectorAll:()=>[]});
    assert.equal((await step(job)).phase,'submitted');
    responses.push(response('revise'));
    assert.equal((await step(job)).phase,'settling');
    now += 6000;
    assert.equal(JSON.parse((await step(job)).response).verdict,'revise');
    const second = {...job,job_id:'sprint_second',fingerprint:'v2'};
    assert.equal((await step(second)).phase,'submitted');
    assert.equal((await step(second)).phase,'waiting');
    responses.push(response('approved'));
    assert.equal((await step(second)).phase,'settling');
    now += 6000;
    assert.equal(JSON.parse((await step(second)).response).verdict,'approved');
    location.href='https://gemini.google.com/app/chat-2';
    assert.match((await step({...job,job_id:'sprint_third'})).error,/conversa do Gemini mudou/);
});

test('content script drops a job abandoned for over 15 minutes instead of blocking the tab',async()=>{
    const content = fs.readFileSync(new URL('../browser_extension/content_gemini.js', import.meta.url), 'utf8');
    let listener;
    let now = 1000;
    let stored = null;
    const editor = {innerText:'',focus(){},dispatchEvent(){}};
    const send = {disabled:false,getAttribute:()=> 'Send message',click(){editor.innerText='';}};
    const document = {
        querySelector:()=>editor,
        querySelectorAll:selector=>selector==='button' ? [send] : [],
        execCommand:(_, __, value)=>{editor.innerText=value;}
    };
    const chrome = {runtime:{id:'extension',onMessage:{addListener:fn=>listener=fn},sendMessage:()=>Promise.resolve()}};
    const sessionStorage = {getItem:()=>stored,setItem:(_,value)=>{stored=value;}};
    const location = {href:'https://gemini.google.com/app/chat-1'};
    vm.runInNewContext(content,{chrome,document,sessionStorage,Date:{now:()=>now},InputEvent:class {},setTimeout,location});
    const step = request=>new Promise(resolve=>listener({type:'NEBULA_AUTO_STEP',job:request},{id:'extension'},resolve));
    assert.equal((await step(job)).phase,'submitted');
    const next = {...job,job_id:'sprint_next',fingerprint:'v2'};
    // Recente: ainda pode estar respondendo, entao a aba protege a conversa.
    now += 60 * 1000;
    assert.match((await step(next)).error,/ainda esta pendente/);
    // Abandonado: o background ja desistiu dele; a aba aceita o job novo.
    now += 15 * 60 * 1000;
    location.href='https://gemini.google.com/app/chat-2';
    assert.equal((await step(next)).phase,'submitted');
    assert.equal(JSON.parse(stored).identity.startsWith('sprint_next:'),true);
});

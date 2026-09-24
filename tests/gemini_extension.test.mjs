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
    const chrome = {
        storage:{local:{get:async key=>structuredClone(store),set:async data=>Object.assign(store,structuredClone(data)),setAccessLevel:async()=>{}}},
        tabs:{create:async()=>({id:99}),remove:async()=>{},query:async()=>opts.noTab ? [] : [{id:7,active:true}],sendMessage:async(id,msg)=>{deliveries++;if(opts.deliveryFails || (opts.missingReceiver && deliveries === 1)) throw new Error('Receiving end does not exist');if(msg.type==='NEBULA_AUTO_STEP') { assert.equal(id,99); return opts.autoResult || {accepted:true}; }return msg.type === 'NEBULA_PING' ? {ok:true} : {accepted:true};}},
        scripting:{executeScript:async()=>{injections++;}},
        runtime:{id:'extension',getURL:path=>'chrome-extension://extension/'+path,onMessage:{addListener:fn=>listener=fn},onInstalled:{addListener(){}},onStartup:{addListener(){}}},
        alarms:{get:async()=>true,create:async()=>{},onAlarm:{addListener(){}}}
    };
    let submissions = 0;
    const fetch = async(url, req)=> {
        if (url.endsWith('/gemini/result')) {submissions++; if(opts.offline) throw new Error('Offline');return {ok:true,status:200,json:async()=>({ok:true})};}
        return {ok:true,status:opts.empty ? 204 : 200,json:async()=>structuredClone(job)};
    };
    vm.runInNewContext(source,{chrome,fetch,AbortSignal,console});
    return {
        call:(message,sender={id:'extension',url:'chrome-extension://extension/popup.html'})=>new Promise(resolve=>listener(message,sender,resolve)),
        store, opts, count:()=>submissions, injections:()=>injections
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

test('automatic review uses dedicated tab and persists response before posting',async()=>{
    const app=boot();
    await app.call({type:'CONFIGURE',token:'t'.repeat(40)});
    let result=await app.call({type:'AUTO',enabled:true});
    assert.equal(result.auto,true);
    assert.equal(app.store.nebulaBridgeState.autoTabId,99);
    app.opts.autoResult={response:'{"verdict":"revise"}'};
    result=await app.call({type:'POLL'});
    assert.equal(result.pending,true);
    assert.equal(app.count(),0);
    app.opts.empty=true;
    result=await app.call({type:'POLL'});
    assert.equal(app.count(),1);
    assert.equal(result.pending,false);
});

test('automatic DOM error stops the loop and keeps the candidate',async()=>{
    const app=boot();
    await app.call({type:'CONFIGURE',token:'t'.repeat(40)});
    await app.call({type:'AUTO',enabled:true});
    app.opts.autoResult={error:'Campo mudou'};
    const result=await app.call({type:'POLL'});
    assert.equal(result.auto,false);
    assert.equal(result.job.job_id,job.job_id);
    assert.equal(result.error,'Campo mudou');
    assert.equal(app.count(),0);
});

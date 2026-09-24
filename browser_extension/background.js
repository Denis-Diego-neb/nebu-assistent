const BRIDGE_URL = 'http://127.0.0.1:8767';
const KEY = 'nebulaBridgeState';
let serial = Promise.resolve();
const exclusive = fn => {
    const next = serial.then(fn);
    serial = next.catch(() => {});
    return next;
};
const read = async () => (await chrome.storage.local.get(KEY))[KEY] || {token: '', job: null, error: ''};
const save = state => chrome.storage.local.set({[KEY]: state});
async function bridge(state, path, payload) {
    const response = await fetch(BRIDGE_URL + path, {
        method: payload ? 'POST' : 'GET', cache: 'no-store',
        signal: AbortSignal.timeout(10000),
        headers: {'Authorization': 'Bearer ' + state.token, 'Content-Type': 'application/json'},
        ...(payload ? {body: JSON.stringify(payload)} : {})
    });
    if (response.status === 204) return null;
    const body = await response.json();
    if (!response.ok) throw new Error(body.error || `HTTP ${response.status}`);
    return body;
}
async function sendToGemini(tab, message) {
    try {
        return await chrome.tabs.sendMessage(tab.id, message);
    } catch (firstError) {
        try {
            await chrome.scripting.executeScript({
                target: {tabId: tab.id},
                files: ['content_gemini.js']
            });
            return await chrome.tabs.sendMessage(tab.id, message);
        } catch (secondError) {
            throw new Error('Nao consegui ativar a ponte na aba do Gemini. Recarregue a extensao e a aba.');
        }
    }
}
async function poll() {
    const state = await read();
    if (!state.token) return;
    try {
        if (state.pending) {
            await bridge(state, '/gemini/result', {...identity(state.job), response: state.pending});
            state.job = null;
            state.pending = null;
            state.draft = '';
            state.error = '';
            if (state.autoTabId) {
                await chrome.tabs.remove(state.autoTabId).catch(() => {});
                state.autoTabId = null;
            }
            await save(state);
        }
        const tabs = await chrome.tabs.query({url: ['https://gemini.google.com/*']});
        const tab = tabs.find(t => t.active) || tabs[0];
        if (!tab) throw new Error('Abra uma aba do Gemini.');
        const ping = await sendToGemini(tab, {type: 'NEBULA_PING'});
        if (!ping?.ok) throw new Error('Recarregue a aba do Gemini.');
        if (!state.job) {
            state.job = await bridge(state, '/gemini/next');
            if (state.job) {
                state.draft = '';
                // Persiste antes da entrega: suspensao do worker nao perde o job.
                await save(state);
            }
        }
        if (state.auto && state.job) {
            if (!state.autoTabId) {
                const created = await chrome.tabs.create({url: 'https://gemini.google.com/app', active: false});
                state.autoTabId = created.id;
                state.autoStartedAt = Date.now();
                await save(state);
                return;
            }
            if (Date.now() - (state.autoStartedAt || Date.now()) > 16 * 60 * 1000) {
                throw new Error('Tempo limite da avaliacao; confira a aba do Gemini.');
            }
            const result = await sendToGemini({id: state.autoTabId}, {
                type: 'NEBULA_AUTO_STEP', job: {...identity(state.job), prompt: state.job.prompt}
            });
            if (result?.error) throw new Error(result.error);
            if (result?.response) {
                state.pending = result.response;
                state.draft = result.response;
            }
            state.error = '';
            await save(state);
            return;
        }
        if (state.job) {
            const result = await sendToGemini(tab, {type: 'NEBULA_GEMINI_JOB', job: identity(state.job)});
            if (!result?.accepted) throw new Error('Aba do Gemini nao aceitou o job.');
        }
        state.error = '';
    } catch (error) {
        state.error = error.message;
        if (state.auto) state.auto = false;
    }
    await save(state);
}
function identity(job) {
    return {job_id: job.job_id, fingerprint: job.fingerprint, content_sha256: job.content_sha256};
}
function sameJob(a, b) {
    return a && b && ['job_id', 'fingerprint', 'content_sha256'].every(k => a[k] === b[k]);
}
function popupSender(sender) {
    return sender.id === chrome.runtime.id && !sender.tab && sender.url === chrome.runtime.getURL('popup.html');
}
async function handle(message, sender) {
    if (message.type === 'NEBULA_CONTENT_READY') {
        if (sender.id !== chrome.runtime.id || sender.frameId !== 0 ||
            !sender.tab || !sender.url?.startsWith('https://gemini.google.com/')) throw new Error('Origem invalida.');
        await poll();
        return {ok: true};
    }
    if (!popupSender(sender)) throw new Error('Origem invalida.');
    let state = await read();
    switch (message.type) {
        case 'STATE': break;
        case 'CONFIGURE':
            if (typeof message.token !== 'string' || !/^[\x21-\x7e]{32,}$/.test(message.token)) throw new Error('Token invalido.');
            state.token = message.token;
            await save(state);
            await poll();
            state = await read();
            break;
        case 'POLL':
            await poll(); state = await read(); break;
        case 'AUTO':
            state.auto = Boolean(message.enabled);
            if (state.auto && !state.token) throw new Error('Configure a ponte primeiro.');
            if (state.auto && !state.pending && !state.autoTabId) state.job = null;
            await save(state);
            await poll(); state = await read(); break;
        case 'DRAFT':
            if (!sameJob(state.job, message.job)) throw new Error('Job mudou. Atualize o popup.');
            if (typeof message.response !== 'string' || message.response.length > 1000000) throw new Error('Resposta muito grande.');
            state.draft = message.response; await save(state); break;
        case 'RESULT':
            if (!sameJob(state.job, message.job)) throw new Error('Job mudou. Atualize o popup.');
            if (typeof message.response !== 'string' || !message.response.trim() || message.response.length > 1000000) throw new Error('Resposta invalida.');
            state.pending = message.response;
            state.draft = message.response;
            await save(state);
            await poll(); state = await read(); break;
        case 'RESET':
            state.auto = false;
            state.autoTabId = null;
            state.job = null; state.pending = null; state.draft = ''; state.error = '';
            await save(state); break;
        default: throw new Error('Mensagem desconhecida.');
    }
    return {ok: true, configured: Boolean(state.token), job: state.job,
        draft: state.draft || '', pending: Boolean(state.pending), error: state.error,
        auto: Boolean(state.auto)};
}
chrome.runtime.onMessage.addListener((message, sender, respond) => {
    exclusive(() => handle(message, sender)).then(respond, error => respond({ok: false, error: error.message}));
    return true;
});
async function start() {
    // Tokens e prompts ficam acessiveis apenas a paginas da extensao.
    await chrome.storage.local.setAccessLevel({accessLevel: 'TRUSTED_CONTEXTS'});
    if (!(await chrome.alarms.get('nebulaGeminiPoll'))) {
        await chrome.alarms.create('nebulaGeminiPoll', {periodInMinutes: 0.5});
    }
}
chrome.alarms.onAlarm.addListener(alarm => {
    if (alarm.name === 'nebulaGeminiPoll') exclusive(poll).catch(console.error);
});
chrome.runtime.onInstalled.addListener(() => exclusive(start).catch(console.error));
chrome.runtime.onStartup.addListener(() => exclusive(start).catch(console.error));
exclusive(start).catch(console.error);

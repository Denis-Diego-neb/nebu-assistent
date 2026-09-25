// A aba automatica permanece na mesma conversa entre avaliacoes.
if (!globalThis.__nebulaGeminiBridgeLoaded) {
    globalThis.__nebulaGeminiBridgeLoaded = true;
    let currentJob = null;
    let stable = '';
    let stableSince = 0;
    const storageKey = 'nebulaAutoReview';
    async function autoStep(job) {
        if (!job?.job_id || !job.fingerprint || !job.content_sha256 || typeof job.prompt !== 'string') {
            throw new Error('Pedido automatico invalido.');
        }
        const identity = job.job_id + ':' + job.fingerprint + ':' + job.content_sha256;
        let saved = JSON.parse(sessionStorage.getItem(storageKey) || 'null');
        let conversationUrl = null;
        if (saved && saved.identity !== identity) {
            // Um job enviado ha mais de 15 min ja foi abandonado pelo background
            // (que desiste aos 16). Sem isto a aba guardava o "submitted" dele
            // para sempre e recusava todo job novo: o automatico parava de vez.
            const abandoned = saved.phase !== 'captured' && Date.now() - (saved.sentAt || 0) > 15 * 60 * 1000;
            if (saved.phase !== 'captured' && !abandoned) throw new Error('A avaliacao anterior ainda esta pendente nesta aba.');
            if (!abandoned && saved.conversationUrl && saved.conversationUrl !== location.href.split(/[?#]/)[0]) {
                throw new Error('A conversa do Gemini mudou. Confira a aba antes de retomar.');
            }
            conversationUrl = abandoned ? null : (saved.conversationUrl || null);
            saved = null;
            stable = '';
            stableSince = 0;
        }
        const editor = document.querySelector('[contenteditable="true"][role="textbox"]');
        if (!editor) return {accepted: true, phase: 'loading'};
        if (!saved) {
            if (editor.innerText.trim()) throw new Error('Campo do Gemini contem texto; confira a aba antes de retomar.');
            const responseCount = document.querySelectorAll('model-response-content').length;
            saved = {identity, sentAt: Date.now(), responseCount, conversationUrl, phase: 'preparing'};
            sessionStorage.setItem(storageKey, JSON.stringify(saved));
            editor.focus();
            document.execCommand('insertText', false, job.prompt);
            editor.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText'}));
            await new Promise(resolve => setTimeout(resolve, 600));
            const send = [...document.querySelectorAll('button')].find(b =>
                /^(Enviar mensagem|Send message)$/i.test(b.getAttribute('aria-label') || '') && !b.disabled);
            if (!send || !editor.innerText.includes(job.prompt.slice(0,60))) {
                throw new Error('Campo ou botao do Gemini mudou; envio interrompido.');
            }
            // Persistir antes do clique impede reenvio em caso de resultado ambiguo.
            saved.phase = 'submitted';
            sessionStorage.setItem(storageKey, JSON.stringify(saved));
            send.click();
            return {accepted: true, phase: 'submitted'};
        }
        if (saved.phase === 'captured') return {accepted: true, response: saved.response};
        if (saved.phase !== 'submitted') throw new Error('Envio anterior incompleto; confira a aba antes de retomar.');
        if (saved.conversationUrl && saved.conversationUrl !== location.href.split(/[?#]/)[0]) {
            throw new Error('A conversa do Gemini mudou durante a avaliacao.');
        }
        if (Date.now() - saved.sentAt > 15 * 60 * 1000) {
            throw new Error('Gemini sem resposta valida ha 15 minutos; automatico interrompido.');
        }
        const responses = [...document.querySelectorAll('model-response-content')];
        if (responses.length <= saved.responseCount) return {accepted: true, phase: 'waiting'};
        const latest = responses[responses.length - 1];
        const blocks = [...latest.querySelectorAll('code')];
        const text = (blocks.length === 1 ? blocks[0].innerText : latest.innerText).trim();
        let parsed;
        try { parsed = JSON.parse(text.replace(/^```json\s*/i, '').replace(/\s*```$/, '')); }
        catch { return {accepted: true, phase: 'waiting'}; }
        if (!parsed || typeof parsed !== 'object' || !parsed.rewards || !parsed.summary || !['approved','revise'].includes(parsed.verdict)) {
            return {accepted: true, phase: 'waiting'};
        }
        if (stable !== text) { stable = text; stableSince = Date.now(); return {accepted: true, phase: 'settling'}; }
        if (Date.now() - stableSince < 5000) return {accepted: true, phase: 'settling'};
        saved.phase = 'captured';
        saved.response = JSON.stringify(parsed);
        saved.conversationUrl = location.href.split(/[?#]/)[0];
        sessionStorage.setItem(storageKey, JSON.stringify(saved));
        return {accepted: true, response: saved.response};
    }
    chrome.runtime.onMessage.addListener((message, sender, respond) => {
        if (sender.id !== chrome.runtime.id) return;
        if (message.type === 'NEBULA_PING') respond({ok: true, page: location.href, job: currentJob});
        if (message.type === 'NEBULA_GEMINI_JOB') {
            currentJob = message.job;
            respond({accepted: true});
        }
        if (message.type === 'NEBULA_AUTO_STEP') {
            autoStep(message.job).then(respond, error => respond({error: error.message}));
            return true;
        }
    });
    chrome.runtime.sendMessage({type: 'NEBULA_CONTENT_READY'}).catch(() => {});
}

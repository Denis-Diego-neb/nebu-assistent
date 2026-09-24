// Esta etapa confirma a aba e a entrega do job. O Gemini continua sob controle do usuario.
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
        if (saved && saved.identity !== identity) throw new Error('Esta aba pertence a outra avaliacao.');
        const editor = document.querySelector('[contenteditable="true"][role="textbox"]');
        if (!editor) return {accepted: true, phase: 'loading'};
        if (!saved) {
            if (editor.innerText.trim() || document.querySelector('model-response-content')) {
                throw new Error('Aba nao esta vazia; nao vou misturar conversas.');
            }
            saved = {identity, sentAt: Date.now(), phase: 'preparing'};
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
        if (saved.phase !== 'submitted') throw new Error('Envio anterior incompleto; confira a aba antes de retomar.');
        if (Date.now() - saved.sentAt > 15 * 60 * 1000) {
            throw new Error('Gemini sem resposta valida ha 15 minutos; automatico interrompido.');
        }
        const responses = [...document.querySelectorAll('model-response-content')];
        if (responses.length !== 1) return {accepted: true, phase: 'waiting'};
        const block = responses[0].querySelector('code');
        const text = (block ? block.innerText : responses[0].innerText).trim();
        let parsed;
        try { parsed = JSON.parse(text.replace(/^```json\s*/i, '').replace(/\s*```$/, '')); }
        catch { return {accepted: true, phase: 'waiting'}; }
        if (!parsed.rewards || !parsed.summary || !['approved','revise'].includes(parsed.verdict)) {
            return {accepted: true, phase: 'waiting'};
        }
        if (stable !== text) { stable = text; stableSince = Date.now(); return {accepted: true, phase: 'settling'}; }
        if (Date.now() - stableSince < 5000) return {accepted: true, phase: 'settling'};
        return {accepted: true, response: JSON.stringify(parsed)};
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

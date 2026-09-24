const element = id => document.getElementById(id);
let current = null;
let automatic = false;
const call = message => Promise.race([
    chrome.runtime.sendMessage(message),
    new Promise((_, reject) => setTimeout(
        () => reject(new Error('A extensao nao respondeu. Recarregue-a em brave://extensions.')),
        12000
    ))
]);
function render(state) {
    if (!state.ok) throw new Error(state.error);
    current = state.job;
    automatic = Boolean(state.auto);
    element('auto').textContent = automatic ? 'Parar avaliações automáticas' : 'Iniciar avaliações automáticas';
    element('status').textContent = state.error || (!state.configured ? 'Cole o token para conectar.' : current ? 'Job recebido. Aguardando resposta.' : 'Conectado. Nenhum job recebido.');
    element('job').hidden = !current;
    element('jobName').textContent = current ? `Job: ${current.job_id}` : '';
    element('response').value = state.draft || '';
}
function action(id, run) {
    element(id).addEventListener('click', async () => {
        element(id).disabled = true;
        try { await run(); } catch (error) { element('status').textContent = error.message; }
        finally { element(id).disabled = false; }
    });
}
action('save', async () => {
    render(await call({type: 'CONFIGURE', token: element('token').value.trim()}));
    element('token').value = '';
});
action('refresh', async () => render(await call({type: 'POLL'})));
action('auto', async () => render(await call({type: 'AUTO', enabled: !automatic})));
action('copy', async () => {
    await navigator.clipboard.writeText(current.prompt);
    element('status').textContent = 'Prompt copiado. Cole e envie no Gemini.';
});
action('submit', async () => render(await call({type: 'RESULT', job: current, response: element('response').value})));
action('reset', async () => render(await call({type: 'RESET'})));
element('response').addEventListener('input', () => {
    call({type: 'DRAFT', job: current, response: element('response').value}).catch(() => {});
});
call({type: 'STATE'}).then(render).catch(error => {element('status').textContent = error.message;});

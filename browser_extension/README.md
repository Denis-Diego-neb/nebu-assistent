# Nebula ↔ Brave ↔ Gemini Web — ponte local 0.3

## Avaliacao automatica (21/09/2026)

Recarregue a extensao existente no Brave e use **Iniciar avaliações automáticas**
no popup. A ponte abre uma aba exclusiva por job, envia o prompt, aguarda JSON
estavel e registra a resposta autenticada com fingerprint/hash. Depois fecha
somente a aba que ela criou. Uma falha de interface, login ou timeout interrompe
novos envios e preserva o job para inspecao. **Parar avaliações automáticas**
interrompe novos envios; uma resposta ja pendente ainda pode ser registrada.

O modo manual descrito abaixo continua disponivel. Nenhuma permissao nova foi
adicionada. A etapa automatica foi testada com APIs simuladas; a validacao real
depende de recarregar/ativar a extensao no navegador do usuario. A primeira nota
real desta rodada foi obtida e registrada por operacao assistida do navegador.

## O que esta etapa entrega

- Servidor em `127.0.0.1:8767`, com `/health`, `/gemini/next` e `/gemini/result`.
- Autenticação por token e origem restrita ao ID da extensão; sem CORS aberto.
- Gateway usa o contrato Gemini, incluindo `worker_4b` e `reviewer_9b`, com deltas inteiros entre -10 e +10.
- Gravação atômica, bloqueio entre processos, conferência de fingerprint e hash do conteúdo e reenvio idempotente.
- Extensão guarda job, rascunho e resultado pendente até confirmação do servidor.
- O usuário copia o prompt, envia no Gemini e cola o JSON final no popup.

Os rewards ficam registrados no review e o autopilot os acumula no placar,
inclusive em rejeicoes. A extensao nao faz commit, merge nem aplica o patch.

## Iniciar

1. Em `brave://extensions`, recarregue a extensão existente da pasta `browser_extension`. Se necessário, habilite o modo de desenvolvedor e carregue essa pasta como extensão sem compactação.
2. Copie o ID da extensão exibido pelo Brave.
3. No PowerShell, na raiz da Nebula, execute:

```powershell
.\.venv\Scripts\python.exe .\ai_sprints\gemini_bridge_server.py --extension-id ID_DA_EXTENSAO
```

4. O servidor exibe um token. Cole-o no campo do popup e clique em **Conectar ponte**. O token fica apenas no armazenamento local da extensão, restrito aos contextos da extensão.
5. Abra ou recarregue a aba autenticada do Gemini. Clique em **Atualizar / testar** no popup.
6. Com um job disponível, clique em **Copiar prompt**, cole e envie no Gemini. Espere a resposta terminar.
7. Cole somente o JSON completo no popup e clique em **Registrar resposta na Nebula**. Blocos ```json também são aceitos pelo parser.
8. Execute novamente seu comando habitual do autopilot para consumir o resultado.

O servidor permanece ativo enquanto esse terminal estiver aberto. Ctrl+C encerra. Por padrão, cada reinício gera um token novo; reconecte o popup. Opcionalmente use a variável `NEBULA_GEMINI_BRIDGE_TOKEN` com um token aleatório de pelo menos 32 caracteres. Não salve tokens no repositório.

## Recuperação e limites

- Sem aba Gemini ou conexão, o popup mostra o erro; **Atualizar / testar** tenta novamente.
- O envio de resultado pendente é tentado novamente nos alarmes, inclusive após reinício do worker. JSON inválido permanece visível para correção; corrigir e registrar substitui a tentativa pendente.
- Se o job ficou antigo, copie seu rascunho caso queira preservá-lo, use **Liberar job local** e depois **Atualizar / testar**. Isso não apaga arquivos da Nebula.
- A fila é consultada em ordem de nome. Arquivos malformados, maiores que 2 MiB ou com conteúdo sensível detectado são ignorados. O filtro de segredos é heurístico; revise o prompt antes de enviá-lo ao Gemini.
- Use uma instalação/perfil da extensão para essa fila. Não há reserva distribuída entre perfis.
- Resultados antigos sem rewards/hash não são aceitos. Gere novamente a revisão com o autopilot; não adicione campos artificialmente ao resultado antigo.
- Um resultado existente e diferente não é sobrescrito. Reenvios idênticos retornam sucesso sem nova gravação.
- O modo automatico depende da interface atual do Gemini Web e para se ela mudar.

## Validação

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_gemini_bridge_server.py -v
node --test tests/gemini_extension.test.mjs
```

Resultado nesta entrega: 12 testes HTTP/gateway e 5 testes do background passaram; sintaxe dos três scripts verificada. Os testes JavaScript usam APIs simuladas do navegador; não houve teste real no Brave/Gemini.

A suíte do autopilot usa o contrato atual `_parse_supervisor_guidance` e roda junto dos testes da ponte Gemini.

Os alarmes usam o intervalo mínimo de 30 segundos e o estado fica em `chrome.storage.local`, conforme a documentação oficial:
- https://developer.chrome.com/docs/extensions/reference/api/alarms
- https://developer.chrome.com/docs/extensions/develop/migrate-to-service-workers

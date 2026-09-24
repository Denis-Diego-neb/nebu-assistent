# Exercicios de estruturacao MCP

Esta trilha cria mudancas pequenas para o worker 4B implementar, o reviewer 9B
revisar e o Gemini avaliar. Cada item deve virar um candidato e um job somente
quando os arquivos reais e os testes de base estiverem definidos. Nao coloque
todos na fila: avance na ordem e mantenha uma unica sprint ativa por dispositivo.

## Regras de cada exercicio

- Alterar apenas arquivos declarados no job.
- Uma tool faz uma acao observavel e recebe argumentos estruturados; ela nao
  interpreta frases do usuario.
- O host descobre, escolhe rota e chama tools; o servidor somente registra e
  executa tools autorizadas.
- Toda dependencia de rede, hardware, tempo ou processo externo entra por
  injecao e ganha fake nos testes.
- Cada sprint precisa de teste unitario e de um teste de contrato no catalogo.
- Se a revisao final rejeitar, registrar o motivo no proximo candidato em vez de
  ampliar o escopo do patch atual.

## Fundamentos locais

1. Documentar o contrato comum de uma tool: `name`, `description`,
   `inputSchema` e resultado JSON.
2. Criar validador de argumentos que rejeita campos extras e tipos errados.
3. Registrar uma tool de exemplo sem hardware no `core.registry`.
4. Listar tools registradas de forma deterministica.
5. Chamar uma tool pelo nome com argumentos ja validados.
6. Definir erros de tool: entrada invalida, indisponivel e falha de execucao.
7. Garantir que excecoes internas nao vazem stack trace pelo contrato.
8. Criar teste que confirma que o dispatcher nunca interpreta linguagem natural.

## Abajur e IoT

9. Extrair `abajur_ligar` para `modules/iot/lights.py` com dependencia Tuya
   injetada.
10. Extrair `abajur_desligar` no mesmo modulo, preservando mensagens atuais.
11. Criar `abajur_status` somente leitura e simular dispositivo offline.
12. Registrar as tres tools em uma unica funcao de bootstrap IoT.
13. Padronizar schemas vazios como objeto vazio, sem argumento textual falso.
14. Separar descoberta do dispositivo da execucao do comando.
15. Adicionar timeout controlado ao adaptador Tuya, testado sem rede.
16. Criar contrato de idempotencia: ligar duas vezes permanece sucesso seguro.

## Servidor MCP de dispositivo

17. Criar adaptador MCP Server que transforma o catalogo local em `tools/list`.
18. Implementar `tools/call` para uma tool IoT com validacao antes do handler.
19. Testar que o servidor nao importa Qwen, prompts nem regras de roteamento.
20. Expor identificacao do servidor e capacidades em endpoint de health.
21. Converter erros internos em resultado MCP estruturado.
22. Bloquear tools nao registradas e argumentos extras no transporte.
23. Adicionar lista de allowlist por servidor sem codificar nomes no host.
24. Testar uma chamada fim a fim com transporte local falso.

## Descoberta e roteamento

25. Criar descricao de dispositivo: id, nome, LAN endpoint e tools anunciadas.
26. Implementar cache curto de `tools/list` com invalidacao explicita.
27. Criar `device_manager` que mescla catalogos de varios servidores.
28. Resolver colisao de tool por namespace, por exemplo `pc.open_app` e
   `iot.abajur_ligar`.
29. Criar roteador que escolhe somente entre tools descobertas.
30. Testar dispositivo LAN indisponivel sem impedir tools dos demais.
31. Adicionar rota remota como fallback abstrato, sem SSH e sem credenciais no
   codigo.
32. Testar que o host pede descoberta antes de tentar uma tool nova.

## Host e Qwen

33. Fazer o host entregar a Qwen apenas o catalogo descoberto e schemas.
34. Validar a tool call da Qwen antes de enviá-la ao roteador.
35. Separar decisao da Qwen de execucao: a Qwen devolve nome e argumentos JSON.
36. Retornar o resultado da tool à Qwen como contexto estruturado.
37. Criar limite de tentativas para uma tool indisponivel.
38. Testar que uma tool de codigo encaminha para o canal Codex, sem executar no
   servidor do dispositivo.
39. Registrar auditoria sem gravar tokens, cookies ou argumentos sensiveis.
40. Criar simulador com PC, notebook e servidor de casa para testar descoberta.

## Operacao e qualidade

41. Criar health checks independentes para host e cada servidor MCP.
42. Medir latencia de descoberta e chamada sem incluir dados privados.
43. Definir versao de schema e teste de compatibilidade entre host e servidor.
44. Criar modo dry-run que mostra rota e schema sem executar hardware.
45. Criar fixture de catalogo antigo para garantir migracao sem quebra.
46. Fazer Gemini avaliar um patch MCP com evidencia de contrato e teste fim a
   fim.
47. Usar o placar para comparar worker 4B e reviewer 9B depois de pelo menos
   cinco sprints validas; nao use uma unica nota para mudar o fluxo.
48. Consolidar os contratos aprovados em `ARQUITETURA.md` e remover adaptadores
   de compatibilidade que nao tenham mais consumidores.

## Ordem recomendada para esta madrugada

Comece pelos exercicios 1 a 8, depois 9 a 16. Pare ao terminar cada bloco para
ver o placar e os reviews. Os exercicios 17 a 24 so entram quando o catalogo IoT
local estiver coberto por testes; descoberta distribuida (25 a 32) vem depois.

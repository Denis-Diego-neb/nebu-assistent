# Nebula: referência para o novo frontend

Este pacote contém uma seleção dos fontes atuais para desenvolver a interface.
Não é um instalador nem uma distribuição completa das integrações nativas.
O fluxo atualizado, contratos de tools e limites desta migração estão em
[ARQUITETURA.md](ARQUITETURA.md).

## Por onde começar

- `gui.py`: interface desktop atual em Tkinter; referência de funcionalidades.
- `remote_server.py`: interface web existente e handlers HTTP; referência real
  dos contratos de login, estado, comandos, conversa e controle dos dispositivos.
- `main.py`: classe `Nebula` e coordenação atual das funcionalidades.
- `device_presets.py`: modos, dispositivos, validações e presets.
- `android/app/src/`: interface Android atual e consumo dos serviços.
- `modules/iot/lights.py`: primeira extração da lógica do abajur.
- `tests/test_lights.py`: contrato do módulo, incluindo falhas parciais.
- `test_control_panel.py`: exemplos de uso e testes do painel/API.

Antes de implementar chamadas, consulte os handlers `do_GET` e `do_POST` de
`remote_server.py` e os testes. A API atual inclui `/api/login`, `/api/state`,
`/api/control`, `/api/device`, `/api/conversation` e `/api/nebula`. Os métodos,
payloads e requisitos de autenticação variam por rota. O login atual usa PIN;
preserve a autenticação ao integrar o frontend.

## Direção da arquitetura

```text
main.py                  inicialização (objetivo; ainda contém orquestração)
core/                    dispatcher, registry, config e composição (implementados)
modules/
  iot/lights.py          comandos do abajur (já extraído)
  iot/tuya.py            driver Tuya (migração futura)
  computer/             apps, áudio, sistema (futuro)
  media/                Spotify, YouTube (futuro)
  voice/                STT e TTS (futuro)
integrations/            cliente Qwen e encaminhamento Codex; MCP ainda futuro
services/                servidor genérico de tools e cliente LAN/remoto
tests/                   novos testes; os antigos ainda estão na raiz
```

A migração é incremental. `abajur_tuya.py` e `abajur_wifi.py` continuam na raiz.
Há registro de tools e rotas HTTP `/api/tools` e `/api/tools/call`. O adaptador
MCP e a união automática dos catálogos de vários dispositivos ainda não estão
implementados. `integracoes/` contém as integrações anteriores.

O objetivo deste envio é criar um frontend para a Nebula, preservando os contratos
existentes e mantendo lógica de dispositivos fora dos componentes visuais.
O framework e o desenho final da nova interface ainda não foram definidos.
Para desenvolver sem hardware, use dados simulados através de uma camada de API
substituível e indique na interface quando os dados forem simulados.

## Conteúdo e execução

O ZIP exclui `.git`, `.venv`, executáveis, caches, capturas de versões antigas,
backups de Minecraft, arquivos de credenciais Tuya e configurações locais.
Os fontes Android estão incluídos como referência; o pacote não inclui todos os
arquivos de build Android. Scripts de implantação e binários nativos também
ficam fora. `ARQUIVOS.txt` lista o conteúdo exato do ZIP.

Para o backend Python, siga a instalação no `README.md`. A aplicação depende
de Windows e certas funcionalidades exigem configuração e hardware locais.
Esses requisitos não devem impedir a criação da interface com dados simulados.

Os testes em `tests/` cobrem o abajur, o executor genérico, encaminhamento de
código, seleção de rede e chamadas HTTP. Os testes anteriores continuam na raiz.
Não houve teste físico do abajur nem de 4G nesta etapa. A referência ao módulo
`piadas.py`, que já estava excluído, foi removida para permitir a inicialização.

No projeto original, gere novamente o pacote com:

```powershell
.\.venv\Scripts\python.exe scripts/export_manus.py
```

Saída: `dist/manus/nebula-manus.zip`.

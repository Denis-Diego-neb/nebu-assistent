# MCP da Nebula

`server.py` transforma o `Dispatcher` local em um servidor MCP 2.x. O catálogo,
os schemas e a execução continuam pertencendo aos módulos; o adaptador apenas
converte `tools/list` e `tools/call`.

O servidor por stdio pode ser iniciado com:

```powershell
.\.venv\Scripts\python.exe -m scripts.run_mcp_server
```

Para inspecionar as tools em um terminal humano no próprio PC:

```powershell
.\.venv\Scripts\python.exe -m scripts.mcp_console
```

O Home Hub do notebook possui o botão **Terminal MCP (SSH)**. Ele abre uma
sessão em `Nebullar@192.168.15.12` e inicia o console no PC. O destino e a pasta
podem ser alterados com `NEBULA_MCP_SSH_DESTINATION` e
`NEBULA_MCP_REMOTE_PROJECT` no notebook.

O PC precisa do OpenSSH Server uma única vez. Em um PowerShell elevado, execute:

```powershell
.\scripts\configure_mcp_ssh_server.ps1
```

Cada chamada grava somente nome, resultado, duração e mensagem curta em
`%LOCALAPPDATA%\Nebula\logs\mcp-events.jsonl`. Argumentos não são gravados. O
relator das sprints envia os últimos eventos no heartbeat autenticado e o Home
Hub os mostra no log sem duplicar entradas.

Referências do protocolo e do SDK: [Model Context Protocol](https://modelcontextprotocol.io/)
e [MCP Python SDK](https://py.sdk.modelcontextprotocol.io/).

"""Worker MCP do notebook: executa jobs pequenos e tipados, sem conhecer o objetivo global.

Implementa o primeiro marco do ``MCP_GOAL.md`` (secoes 24 e 32): o PC principal
envia um ``JobEnvelope`` assinado, o notebook valida protocolo e capacidade,
entrega somente aquele prompt isolado ao Qwen Edge (Ollama local) e devolve um
``JobResult`` tipado. Nao ha shell, sistema de arquivos remoto, IoT nem
navegador. O pacote ``protocol`` e compartilhado com o PC para que os dois lados
nunca divirjam no contrato.
"""

WORKER_VERSION = "1.0.0"

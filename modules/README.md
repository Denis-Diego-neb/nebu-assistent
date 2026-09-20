# Organização incremental

A estrutura de destino separa `core/` (dispatcher, registry e configuração),
`modules/` (IoT, computador, mídia e voz), `integrations/` (MCP, Codex e LLM),
`services/` (dispositivos e rede) e `tests/`. O `main.py` deverá ficar responsável
pela inicialização. Essas áreas serão migradas em etapas.

## Primeira etapa: abajur

- `modules/iot/lights.py`: contrato do controle, execução dos pedidos e resultado
  com mensagem e indicação de falha. Não depende de `main.py`, GUI ou voz.
- `main.py`: interpreta o texto com o parser existente, coordena os efeitos,
  delega os pedidos ao módulo, apresenta a resposta e mantém a repetição.
- `abajur_tuya.py`: driver LAN existente, ainda na raiz. A conexão compartilhada
  e a reconfiguração continuam no host nesta etapa.
- `abajur_wifi.py`: parser e tipos existentes, compartilhados com o driver.

O ponto de entrada do módulo é `executar_pedidos_abajur(pedidos, obter_controle)`.
A função recebe uma fábrica para reutilizar a conexão existente ou um controle
simulado nos testes. Executa os pedidos em ordem e, em caso de falha, informa
também o que já foi aplicado. O host decide como apresentar e repetir o comando.

O registro e o dispatcher genérico agora ficam em `core/`. O servidor HTTP
recebe chamadas explícitas sem interpretar texto. `pedido_da_tool` converte os
argumentos validados diretamente em pedidos do driver. Veja
[ARQUITETURA.md](../ARQUITETURA.md) para o fluxo completo e limites atuais.
O driver ainda pode ser migrado para `modules/iot/tuya.py`, preservando os imports
antigos enquanto os demais consumidores migram. O transporte MCP ainda é futuro.

Teste isolado, sem acionar o abajur:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_lights.py
```

## Segunda etapa: Ambilight

- `modules/iot/ambilight.py` registra as tools `modo_ambilight_iniciar`,
  `modo_ambilight_parar` e `modo_ambilight_status` com callbacks tipados. O
  dispatcher nao converte essas chamadas em frases para o parser legado.
- O modulo escolhe a saida do teclado por capacidade. O driver USB usa RGB
  uniforme porque o firmware aplica o frame Custom de 126 LEDs em blocos; o
  driver OpenRGB pode manter a saida multizona.
- O ciclo de vida dos dispositivos ainda permanece em `Nebula` e entra no
  modulo por callbacks. Ele pode ser extraido depois que o contrato de estado
  estiver estabilizado.

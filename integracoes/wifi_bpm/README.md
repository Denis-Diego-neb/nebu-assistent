# Laboratório de BPM por Wi-Fi

Esta implementação calcula **periodicidade de amplitudes CSI**, expressa em BPM.
Ainda não identifica nem valida clinicamente batimentos humanos: movimentos,
ventiladores e harmônicos da respiração podem produzir falsos positivos mesmo
quando os filtros aceitam o sinal. Valide cada experimento contra um sensor de
referência. Não use este valor para decisões de saúde.

O Wi-Fi comum do celular, RSSI e ping não fornecem as amostras necessárias.
É preciso um receptor/firmware que exporte CSI, por exemplo um experimento baseado
no [ESP-CSI oficial da Espressif](https://github.com/espressif/esp-csi).
O projeto não instala firmware nem transforma automaticamente qualquer roteador
em sensor. Os resultados de pesquisa dependem de hardware e processamento
específicos; consulte o [estudo experimental sobre sinais vitais por CSI](https://pmc.ncbi.nlm.nih.gov/articles/PMC11013971/).

## Preparar uma captura real

1. Prepare emissor e receptor CSI com canal e posição fixos, uma pessoa imóvel e
   tráfego Wi-Fi consistente. Consulte os exemplos do ESP-CSI para sua placa.
2. Configure o exportador para pelo menos 10 amostras por segundo, de preferência
   20, mantendo a mesma sequência de subportadoras e antena durante a coleta.
3. Converta a saída do firmware em JSONL no formato abaixo. Remova subportadoras
   nulas e palavras inválidas conforme o firmware; preserve a mesma seleção.
   Não envie o CSV bruto do ESP-CSI ao encaminhador. Faça a conversão da ordem
   imaginário/real do firmware para `[real, imaginário]`.
4. Use timestamps UNIX em segundos do instante da captura, com o relógio
   sincronizado ao PC. Não renomeie RSSI como CSI e não atualize timestamps de
   arquivos antigos para fazê-los passar por uma captura ao vivo.
5. Abra a Nebula 1.23 no PC e encaminhe o fluxo. A credencial é a do hub,
   disponibilizada ao encaminhador pela variável `NEBULA_POWER_TOKEN`.

Formato de cada linha, com `timestamp` substituído pelo instante real da captura:

```json
{"source":"esp32-sala","layout":"canal6-ant0-lltf","timestamp":0,"csi":[[24,-12],[19,7],[22,-4],[18,8]]}
```

O valor zero acima é apenas um marcador de formato, recusado pelo servidor.
Também se aceita `{source, layout, samples:[{timestamp,csi},...]}` com até 512
amostras, respeitando 100 KB por requisição. Cada amostra deve ter 4–256 pares.

```powershell
# Seu exportador precisa escrever uma linha JSON por captura e descarregar stdout.
python seu_exportador_csi.py | python integracoes/wifi_bpm/forward_csi.py --url http://127.0.0.1:8765
```

Endpoints autenticados com `X-Nebula-Power-Token` ou sessão Nebula:

- `POST /api/wifi-bpm/ingest`: recebe capturas reais.
- `GET /api/wifi-bpm/status`: leitura e motivo de indisponibilidade.
- `POST /api/wifi-bpm/reset` com `{}`: reinicia antes de mudar receptor ou layout.

São necessários pelo menos 24 segundos de captura; a janela móvel guarda até
30 segundos. O estimador limita processamento a seis subportadoras e 20 Hz,
remove tendência, analisa concentração espectral e consistência entre metades
e subportadoras. Rejeita sinal plano, lacunas, movimento intenso e alguns
harmônicos respiratórios. `quality` é uma heurística espectral, não probabilidade
de acerto nem confiança clínica. A faixa experimental é 45–180 BPM.

Sem receptor: `hardware_required`, `bpm: null`. Durante coleta: `collecting`.
Sinal recusado: `poor_signal`. Após cinco segundos sem amostras: `stale` e
`bpm: null`. Sinal aceito: `experimental_estimate`, ainda sujeito a falsos
positivos. Não há dados simulados na interface. Os testes sintéticos verificam
o algoritmo; não constituem validação com pessoas.

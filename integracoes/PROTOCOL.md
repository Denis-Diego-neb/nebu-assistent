# Protocolo local de telemetria Nebula v2

- Destino: `127.0.0.1:29876`
- Transporte: um objeto JSON UTF-8 por datagrama UDP
- `seq`: inteiro sem sinal de 32 bits, com retorno natural a zero
- `valid=false`: informa que não há um veículo local utilizável

RPM genérico:

```json
{"v":2,"seq":42,"source":"assetto_corsa","metric":"rpm","valid":true,"rpm":6123,"min_rpm":0,"redline_rpm":8000,"max_rpm":8000,"gas":0.8,"gear":4,"shifting":false,"drag":false,"speed_kmh":115,"turbo_bar":1.2,"oil_pressure":3.5,"oil_temp":108,"fuel_percent":62,"water_temp":91,"engine_map":2}
```

Os campos apÃ³s `drag` sÃ£o opcionais. O display FuelTech da Nebula deixa como
indisponÃ­vel qualquer mÃ©trica que o jogo/SimHub nÃ£o fornecer.

Boost do Rocket League, normalizado entre zero e um:

```json
{"v":2,"seq":43,"source":"rocket_league","metric":"boost","valid":true,"value":0.75}
```

O receptor aceita pacotes somente da interface de loopback, rejeita valores
não finitos/fora da faixa e neutraliza a saída após 750 ms sem dados.

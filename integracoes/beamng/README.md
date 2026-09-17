# Manômetro de turbo do BeamNG

O mod usa a API de protocolos UDP conferida nos arquivos locais do BeamNG
0.39.4: `lua/vehicle/protocols.lua`, `protocols/outgauge.lua` e
`powertrain/turbocharger.lua`. Ele lê `electrics.values.turboBoost` e
`turboBoostMax`, em PSI, e converte para bar dividindo por 14,503773773.
Não deduz a pressão a partir de RPM, acelerador ou áudio.

Com o jogo fechado, execute:

```powershell
python integracoes/beamng/install.py --user-folder "$env:LOCALAPPDATA\BeamNG\BeamNG.drive\current"
```

O instalador cria `mods/nebula_turbo.zip`, sem modificar arquivos da instalação
Steam ou o mod do SimHub. Protocolos adicionais já vêm habilitados no 0.39.4;
se estiverem explicitamente desabilitados, o instalador faz backup de
`settings/settings.json` antes de habilitá-los.

Na próxima vez que abrir o jogo, use um veículo com turbo. Na Nebula do A71,
abra **Turbo → Mostrador em tela cheia**. A tela fica horizontal, com fundo
`#000000`, ponteiro e pressão em laranja. Toque para voltar. O manômetro funciona
independentemente dos efeitos de iluminação. A coleta para no celular quando
o aplicativo fica em segundo plano.

O jogo envia a 20 Hz exclusivamente para `127.0.0.1:29878`. A Nebula do PC
abre o receptor ao consultar `GET /api/beamng/turbo`; esse endpoint exige a
autenticação normal da Nebula. O celular consulta a 4 Hz, com suavização visual
do ponteiro. O número exibe a última leitura real, sem suavização.

Sem jogo, fora de um veículo ou após um segundo sem pacote: pressão indisponível.
Veículo sem turbo: indicação específica, sem inventar `0 bar`. A pressão zero
só aparece quando enviada por um veículo com turbo. A escala parte de 3 bar e
acompanha o limite informado pelo veículo, até 20 bar. Não existe modo de
simulação de pressão na interface.

Formato binário little-endian, 28 bytes: `4s III fff` — assinatura `NBTG`,
versão 1, sequência uint32, flags (1 = dados válidos, 2 = tem turbo), pressão
em bar, limite de pressão em bar, RPM. Entradas inválidas, repetidas e atrasadas
são rejeitadas. O protocolo não interfere nas portas RPM/SimHub existentes.

A preparação e os testes locais podem ser feitos sem iniciar o BeamNG.
A validação final de pressão com um veículo real exige executar o jogo.

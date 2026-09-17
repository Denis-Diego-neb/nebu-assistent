# NebulaBoost para Rocket League

O `NebulaBoost.dll` é um plugin local do BakkesMod para treino/offline com o
Easy Anti-Cheat desativado. Ele lê somente o boost do carro local pela API do
BakkesMod e envia um datagrama UDP para `127.0.0.1:29876` a cada 50 ms. Não
escreve estado no jogo. Para partidas com o anti-cheat ativo, use o leitor
visual padrão da Nebula.

Para compilar e instalar:

```powershell
.\native\nebula_boost\build.ps1 -Deploy
```

O instalador acrescenta `plugin load nebulaboost` ao `plugins.cfg`. Antes de
abrir a Nebula na mesma sessão offline, selecione a fonte do plugin:

```powershell
$env:NEBULA_BOOST_SOURCE = "rocket_league"
```

Depois, abra o BakkesMod, o Rocket League e diga: “Nebu, ative o modo boost”. A
cor ou temperatura atual da lâmpada é preservada; somente o brilho varia de 1%
a 100%.

Pacote enviado:

```json
{"v":2,"seq":42,"source":"rocket_league","metric":"boost","valid":true,"value":0.75}
```

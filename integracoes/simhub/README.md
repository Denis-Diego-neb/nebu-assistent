# RPM genérico via SimHub

Não existe uma API universal compartilhada por todos os jogos de corrida.
Esta ponte usa os dados normalizados do SimHub. O perfil foi preparado para
**BeamNG.drive** e **Assetto Corsa**, além dos outros jogos compatíveis que
exponham RPM, limite de giro e acelerador.

1. Instale e configure o SimHub para o jogo desejado.
2. Feche o SimHub.
3. Compile e instale a ponte:

   ```powershell
   .\integracoes\simhub\build.ps1 -Deploy
   ```

4. Abra o SimHub, habilite **Nebula RPM Telemetry** em **Settings > Plugins** e
   diga “Nebu, ative o modo RPM”.

## BeamNG.drive

No SimHub, abra a página do BeamNG.drive, entre em **Game config** e aplique a
configuração sugerida. No jogo, confirme em **Options > Other > Protocols** que
o **OutGauge UDP protocol** está habilitado. Entre em um veículo antes de testar.

## Assetto Corsa

No SimHub, abra a página do Assetto Corsa e aplique **Game config**. Se usar o
Content Manager, escolha o modo de inicialização **Official** ou **AppId**. Se o
Content Manager executar como administrador, execute o SimHub como administrador
também. No primeiro teste, use um carro e uma pista oficiais para descartar mods
que alterem a memória compartilhada.

Em ambos os jogos, a lightbar do DualShock 4 por USB e o abajur recebem a mesma
faixa: amarelo-claro em baixa, laranja no meio e vermelho em alta. No limitador,
os dois piscam vermelho em ciclos de 250 ms.

O plugin envia somente telemetria para `127.0.0.1:29876`. Jogos que não
fornecem RPM ao SimHub ainda precisam de um adaptador próprio.

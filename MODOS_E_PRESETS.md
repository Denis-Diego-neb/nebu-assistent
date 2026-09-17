# Modos por dispositivo

Em **Modos → Efeitos**, escolha separadamente o efeito de cada dispositivo.
No Android, abra **Modos** e toque em **Aplicar neste dispositivo**.

| Dispositivo | Modos |
| --- | --- |
| Abajur | Manual, Ambilight, música do navegador, tocha, RPM, Boost |
| Kumara | Manual, Ambilight em três regiões, Boost |
| PS4 por USB | Manual, Ambilight, RPM, Boost |
| Telefone | Manual, RPM/FuelTech, pressão do turbo |

Alterar a cor, brilho ou energia do abajur coloca somente o abajur em controle
manual. Os outros dispositivos continuam nos modos escolhidos. Se dois
dispositivos compartilham o mesmo produtor, ele é reconfigurado ao mudar seus
participantes; pode ocorrer uma breve retomada da iluminação nesse grupo.

## Presets

Configure os dispositivos, informe um nome e clique em **Salvar configuração**.
São salvos os modos, flashes, cor do Boost e ajustes de cor, temperatura, brilho
e energia do abajur feitos na Nebula. **Aplicar** reproduz essa configuração.
Salvar novamente com o mesmo nome atualiza o preset; **Excluir** remove somente
o preset salvo. Os nomes não diferenciam maiúsculas de minúsculas.

Comandos: **“Nebula, ative o preset Corrida”**, **“troque para o preset Noite”**
ou **“salve o preset Corrida”**. Os presets ficam no PC que executa os modos,
em `%LOCALAPPDATA%\Nebula\device_presets.json`, com gravação atômica.
Reiniciar a Nebula mantém os presets; os efeitos só começam quando você aplica
uma configuração. Um dispositivo indisponível exibe erro sem desligar os demais.

O APK controla os presets do PC. Deixe a Nebula aberta no PC para captura de
tela, música e telemetria. Abra **Painel → Tela cheia** no telefone: trocar o
modo pelo PC ou por preset muda o mostrador aberto. Android em segundo plano
não abre uma Activity automaticamente. Sem dados recentes, o painel mostra
que está aguardando telemetria; não simula RPM ou pressão.

## Flash do escape — BeamNG

A opção **Flash do escape** é independente no Kumara e PS4 e fica salva no
preset. Sobrepõe um pulso quente de aproximadamente 220 ms e restaura o efeito
mais recente. Em manual, a base fica apagada entre os pulsos. Eventos muito
próximos são agrupados para respeitar a cadência do USB do Kumara.

O instalador do mod pode gerar uma cópia instrumentada do módulo térmico do
BeamNG instalado. Ele acrescenta um contador imediatamente após as três
chamadas de som de afterfire, preservando os arquivos originais do jogo.
O contador segue no protocolo local Nebula, versão 2; a versão 1 continua
aceita pelo receptor. Não há detecção por microfone nem por queda de RPM.

```powershell
.\.venv\Scripts\python.exe integracoes\beamng\install.py --user-folder "$env:LOCALAPPDATA\BeamNG\BeamNG.drive\current" --game-folder "C:\Program Files (x86)\Steam\steamapps\common\BeamNG.drive"
```

Essa integração foi inspecionada no BeamNG 0.39.4. Após atualizar o jogo,
gere novamente o mod com o jogo fechado. O instalador recusa versões sem as
três chamadas esperadas. Mods que substituem o mesmo módulo térmico podem
conflitar. Outros jogos precisam oferecer um evento equivalente. A sincronia
física dos flashes deve ser conferida ao dirigir um veículo com afterfire.

# Modos independentes e celulares

## Iluminação

O motor em `main.py` e os presets em `device_presets.py` já separam abajur,
teclado, controle e painel móvel. No Android: **Modos > dispositivo > Aplicar
neste dispositivo**. A compatibilidade varia:

| Dispositivo | Modos |
| --- | --- |
| Abajur | Manual, Ambilight, Música, Tocha, RPM, Boost |
| Teclado | Manual, Ambilight, Boost |
| Controle PS4 | Manual, Ambilight, RPM, Boost |
| Painel móvel | Manual, RPM, Turbo |

Os sete testes de `test_device_presets.py` passaram em 14/09/2026, incluindo
abajur em Música, teclado em Ambilight e painel em RPM simultaneamente.
A API do executável antigo não expunha `devices`; por isso foi iniciada uma
nova compilação do desktop. O painel móvel ainda representa um destino lógico
compartilhado: cadastro e funções independentes por telefone são uma extensão
separada, ainda não implementada.

## A71 e iPhone 7

### Atualização USB / FuelTech / Kumara — 14/09/2026

- A71 voltou ao USB autorizado (`RQ8NA0AXH8M`). APK atualizado e painel
  FuelTech aberto com `deviceLocked=1`, sem dispensar o bloqueio do Android.
- `SHOW_GAUGE` abre somente o mostrador. Os controles e a assinatura de
  desbloqueio do Windows continuam no fluxo protegido de autenticação.
- `phone_usb_panel.py`, iniciado pelo agente do PC, detecta conexão USB a cada
  cinco segundos. Se o celular estiver em RPM ou Turbo, configura `adb reverse`
  na porta 8765 e abre o mostrador uma vez por conexão. Requer ADB previamente
  autorizado; não altera as permissões USB nem desbloqueia o aparelho.
- RPM e boost compartilham a entrada UDP através de `telemetry_udp.py`.
  Cada consumidor recebe os mesmos datagramas e interpreta seu próprio formato;
  parar um modo não fecha a telemetria do outro.
- Kumara 320F:5000: comparação física confirmou apagão no quadro Custom
  (~135 ms) e ausência dele ao atualizar o parâmetro RGB do modo estático
  (~12 ms). Ambilight usa uma cor média da região inferior da tela, com mudança
  do parâmetro RGB sem reiniciar o modo a cada atualização. A barra por tecla
  de boost e a função explícita de três zonas conservam Custom, ainda sujeito
  ao apagão do firmware. Quadros idênticos não são regravados.
- Referência do protocolo:
  https://github.com/CalcProgrammer1/OpenRGB/tree/master/Controllers/EVisionKeyboardController/EVisionKeyboardController

### Recursos de sensores e SSH

- **A71:** SSH é viável com OpenSSH no Termux, preferencialmente autenticado por
  chave e acessado pelo Tailscale. Isso dá acesso ao ambiente do Termux; não
  equivale ao shell ADB nem remove limites de permissão do Android. ADB USB já
  foi autorizado neste PC. Na última verificação o A71 estava fora do USB e
  offline no Tailscale; nenhum servidor SSH novo foi instalado.
- **iPhone 7:** iOS padrão não oferece um servidor SSH de administração do sistema.
  Apps trabalham em sandbox. Para coletar sensores sem modificar o sistema,
  uma opção é phyphox com acesso remoto na rede privada. A versão do iOS e a
  compatibilidade da versão disponível do app precisam ser verificadas no aparelho.
- **Funções possíveis:** painel de telemetria em um telefone; coleta de
  acelerômetro/giroscópio em outro. Esses dados descrevem movimento e orientação
  do telefone. Não são coordenadas precisas de uma pessoa andando no cômodo.

## O significado de “pelo Wi-Fi”

Enviar medidas dos sensores pela rede Wi-Fi é diferente de medir o corpo pelos
reflexos das ondas de rádio. SSH transporta comandos e arquivos; não habilita CSI.

Para presença/movimento por Wi-Fi, ESP-CSI é um caminho experimental com
receptor compatível. Não foi confirmada uma combinação de chipset e firmware
CSI utilizável nos dois celulares. A existência de projetos Nexmon para chips
específicos não confirma suporte ao A71 ou ao iPhone 7.

O laboratório `wifi_bpm.py` estima periodicidade CSI e não é uma medição validada
de batimentos cardíacos. Sem capturas reais compatíveis, BPM deve permanecer
indisponível. Localização de pessoas e batimentos exigem experimentos e validação
distintos; não há promessa de coordenadas ou BPM confiável só com os celulares.

Fontes consultadas:

- https://termux.dev/en/
- https://github.com/termux/termux-packages/tree/master/packages/openssh
- https://support.apple.com/guide/security/security-of-runtime-process-sec15bfe098e/web
- https://support.apple.com/en-ca/111943
- https://phyphox.org/remote-control/
- https://github.com/espressif/esp-csi
- https://github.com/seemoo-lab/nexmon_csi

# Controle universal — Nebula 1.23

No Android, abra **Dispositivos**. O hub do notebook deve estar atualizado para
1.23. A central reúne PC por Wake-on-LAN, TVs Samsung/LG, abajur Tuya e Smart IR
já configurados. **Buscar TVs** faz descoberta na rede local. TVs novas precisam
de **Parear TV** e autorização na tela do aparelho.

Estar na internet não é suficiente para aceitar comandos. Cada marca requer
protocolo e credenciais compatíveis. O catálogo informa apenas controles
integrados; não tenta acessar aparelhos sem configuração.

Para ampliar, configure no usuário Windows que executa o hub:

```powershell
[Environment]::SetEnvironmentVariable('NEBULA_HA_URL', 'http://homeassistant.local:8123', 'User')
# Defina NEBULA_HA_TOKEN no mesmo usuário com seu token de longa duração.
# Reinicie a sessão/hub para que as novas variáveis sejam herdadas.
```

O token é criado no perfil da sua instalação Home Assistant e permanece no
notebook. A implementação usa a [API REST oficial](https://developers.home-assistant.io/docs/api/rest/),
lista entidades configuradas e chama serviços permitidos para a entidade escolhida.
São aceitos luzes, tomadas/switches, ventiladores, input_boolean, cenas, modos
disponíveis de climatização e ações de mídia anunciadas pelo aparelho.
Comandos desconhecidos e entidades indisponíveis são recusados.

O catálogo reutiliza consultas por dez segundos e consulta provedores em paralelo.
Falha no Home Assistant não remove os aparelhos locais. A interface só consulta
a rede quando solicitada; não mantém sondagens em segundo plano.
Wake-on-LAN, infravermelho e algumas APIs confirmam envio, não o estado físico.

Endpoints do hub, com a autenticação existente `X-Nebula-Power-Token`:

- `GET /universal/devices`
- `POST /universal/discover` com `{}`
- `POST /universal/action` com `{"device_id":"local:lamp","action":"turn_on"}`

## Overlay Rocket League

No desktop, clique **Overlay Rocket League** no cabeçalho para mostrar/ocultar.
No Android: **Ferramentas → ♥ BPM → Iniciar / Parar**.
A overlay segue uma faixa horizontal: **barra azul de boost**, nick sobre a
barra e **coração + BPM laranja em cápsula escura semitransparente**. A barra tem
pontas arredondadas, o nick padrão é **Star** e a posição inicial é o centro da
lateral esquerda. O restante é transparente, com
passagem de cliques. O nick é opcional: preencha **Seu nick** e toque **Aplicar nick**;
deixe vazio para ocultar. Não há leitura automática do nick da conta do jogo.
Ela acompanha a posição da janela. Ative o modo **Boost** na Nebula para alimentar
a barra pela leitura real do HUD; sem telemetria, aparece apenas o fundo escuro
da barra. Não há um segundo número de boost nem uma segunda captura do jogo.
Use Rocket League em janela ou sem bordas. O comportamento em tela cheia
exclusiva depende do Windows/jogo e não é garantido.

Para abrir um controlador separado conectado à Nebula já aberta no PC:

```powershell
.\.venv\Scripts\python.exe rocket_overlay.py
```

Quando não existe leitura recente, aparece **♥ —** na cápsula escura.
O pulso depende do [laboratório CSI](wifi_bpm/README.md). A implementação não
injeta código nem lê a memória do jogo. Isso não é garantia de aprovação por
anti-cheat: a [Epic informa que ferramentas de terceiros não têm suporte oficial](https://www.epicgames.com/help/c-37599050/a22460826?lang=en-US).

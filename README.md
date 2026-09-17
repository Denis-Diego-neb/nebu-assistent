# Nebula

Assistente pessoal e plataforma de automação para Windows, Android e dispositivos da rede local.

A **Nebula** começou como uma assistente por voz para Windows e evoluiu para uma central de automação pessoal capaz de controlar o computador, dispositivos domésticos, periféricos, jogos, mídia e integrações locais entre diferentes equipamentos.

O projeto é desenvolvido principalmente em **Python**, com componentes adicionais em **Java**, **C++**, **C#** e **PowerShell**.

---

## Sumário

- [Visão geral](#visão-geral)
- [Principais recursos](#principais-recursos)
- [Assistente por voz](#assistente-por-voz)
- [Interface para Windows](#interface-para-windows)
- [Aplicativo Android](#aplicativo-android)
- [Casa conectada](#casa-conectada)
- [Integrações com jogos](#integrações-com-jogos)
- [Ambilight](#ambilight)
- [Periféricos](#periféricos)
- [Controle remoto e rede](#controle-remoto-e-rede)
- [Projetos e Codex](#projetos-e-codex)
- [Memória e aprendizado](#memória-e-aprendizado)
- [Estrutura do projeto](#estrutura-do-projeto)
- [Instalação](#instalação)
- [Execução](#execução)
- [Build Android](#build-android)
- [Build Windows](#build-windows)
- [Testes](#testes)
- [Documentação adicional](#documentação-adicional)
- [Segurança](#segurança)
- [Tecnologias](#tecnologias)
- [Estado do projeto](#estado-do-projeto)

---

# Visão geral

A Nebula pode ser utilizada por:

- voz;
- texto;
- interface gráfica no Windows;
- aplicativo Android;
- painel remoto;
- integrações locais com outros dispositivos;
- automações ligadas a jogos e periféricos.

A palavra de ativação da assistente é:

> **Nebu**

Exemplos de comandos:

```text
Nebu, abra o Discord
Nebu, toca After Dark
Nebu, tire um print
Nebu, ligue o abajur
Nebu, ative o modo boost
Nebu, coloque o ar em 22 graus
```

---

# Principais recursos

Entre as principais funções da Nebula estão:

- abertura e fechamento de programas;
- controle de mídia;
- pesquisas no Google e YouTube;
- reprodução de músicas;
- captura de tela;
- escrita automática em aplicativos;
- controle de dispositivos Tuya;
- controle de TVs;
- controle de ar-condicionado;
- Wake-on-LAN;
- telemetria de jogos;
- modos de iluminação RGB;
- integração com DualShock 4 e teclados RGB;
- interface remota para Android;
- memória local;
- vocabulário ensinável;
- integração com Codex;
- central auxiliar executada em notebook.

---

# Assistente por voz

A Nebula mantém o microfone ativo e interpreta comandos após ouvir **Nebu**.

Ela pode:

- abrir e fechar aplicativos;
- controlar mídia;
- pesquisar na web;
- tocar músicas;
- informar horário;
- controlar dispositivos conectados;
- executar ações personalizadas;
- reconhecer pequenas variações de comandos ensinados pelo usuário.

O reconhecimento de voz utiliza o serviço de reconhecimento do Google.

As respostas faladas utilizam voz neural do Microsoft Edge quando disponível, com fallback para o sistema de voz do Windows.

---

# Interface para Windows

A interface principal está implementada em:

```text
gui.py
```

Ela reúne áreas para:

- Assistente;
- Conversa;
- Casa;
- Controles;
- Projetos;
- Grupo;
- Configuração;
- dispositivos remotos.

A Nebula pode continuar ativa na bandeja do Windows mesmo quando a janela principal é fechada.

---

# Aplicativo Android

O código do aplicativo Android está localizado em:

```text
android/
```

O aplicativo funciona como uma central remota para a Nebula.

Entre os recursos disponíveis estão:

- ligar o PC por Wake-on-LAN;
- controlar dispositivos da casa;
- controlar TVs;
- controlar ar-condicionado;
- acompanhar telemetria;
- utilizar ferramentas ligadas a jogos;
- enviar comandos para a Nebula;
- acessar projetos e Codex;
- acessar painéis de controle;
- proteção remota do aparelho.

O aplicativo utiliza autenticação e pareamento com a central Nebula.

---

# Casa conectada

## Lâmpadas Tuya

A Nebula pode controlar dispositivos Tuya diretamente pela rede local.

Recursos disponíveis:

- ligar e desligar;
- controle RGB;
- temperatura de branco;
- brilho;
- cores personalizadas;
- animação musical;
- modo tocha;
- Ambilight;
- efeitos sincronizados com telemetria.

Exemplos:

```text
Nebu, ligue o abajur
Nebu, deixe o abajur azul
Nebu, coloque o brilho em 40%
Nebu, luz quente
Nebu, ative o modo tocha
```

A comunicação pode acontecer diretamente pela LAN sem depender da nuvem durante o uso.

### Arquivos privados

Arquivos contendo credenciais ou chaves locais **não devem ser enviados ao Git**.

Exemplos:

```text
abajur_tuya.json
devices.json
snapshot.json
tinytuya.json
tuya-raw.json
.env
```

Esses arquivos devem permanecer protegidos pelo `.gitignore`.

---

## Ar-condicionado

A Nebula possui integração com controle IR inteligente para aparelhos de ar-condicionado.

São suportados controles como:

- ligar e desligar;
- temperatura;
- modo de operação;
- velocidade de ventilação.

---

## TVs

A central pode detectar e controlar televisores compatíveis na rede local.

Atualmente existem integrações para:

- Samsung Tizen;
- LG webOS.

Dependendo do aparelho, podem ser disponibilizados:

- energia;
- volume;
- canais;
- navegação;
- entrada;
- mídia;
- Wake-on-LAN.

Documentação relacionada:

```text
integracoes/CONTROLE_UNIVERSAL.md
```

---

# Integrações com jogos

## Rocket League — Modo Boost

A Nebula consegue acompanhar visualmente o indicador de boost do Rocket League.

A integração visual não precisa injetar código no processo do jogo.

A quantidade de boost pode ser representada em:

- lâmpada;
- lightbar do DualShock 4;
- teclados RGB compatíveis;
- painel Android.

Implementações principais:

```text
leitor_boost_visual.py
rocket_overlay.py
```

Existe também uma implementação alternativa nativa em:

```text
native/nebula_boost/
```

---

## Modo RPM

A Nebula possui um protocolo UDP local para receber telemetria de jogos de corrida.

A telemetria pode controlar:

- lâmpada;
- DualShock 4;
- teclados RGB;
- painel Android.

Exemplo de representação visual:

```text
RPM baixo  -> amarelo
RPM médio  -> laranja
RPM alto   -> vermelho
Limitador  -> vermelho piscando
```

Documentação relacionada:

```text
integracoes/PROTOCOL.md
integracoes/simhub/README.md
```

---

## BeamNG.drive

A integração com BeamNG permite enviar telemetria do veículo para a Nebula.

Existe também um painel Android que pode funcionar como manômetro de turbo.

Arquivos relacionados:

```text
beamng_turbo.py
integracoes/beamng/
```

Documentação:

```text
integracoes/beamng/README.md
```

---

# Ambilight

A Nebula consegue analisar localmente a imagem exibida na tela e utilizar cores predominantes para controlar dispositivos RGB.

O processamento acontece localmente.

Nenhuma imagem precisa ser armazenada ou enviada para serviços externos.

Implementação principal:

```text
modo_ambilight.py
```

---

# Periféricos

Existem integrações específicas para diferentes dispositivos.

Entre elas:

```text
lightbar_ds4.py
teclado_attack_shark.py
teclado_evision.py
teclado_openrgb.py
```

A Nebula pode utilizar iluminação de periféricos como parte dos modos:

- Boost;
- RPM;
- Ambilight;
- efeitos personalizados.

---

# Controle remoto e rede

A Nebula possui uma central remota implementada principalmente em:

```text
remote_server.py
```

Existe também um serviço destinado ao notebook:

```text
notebook_power_server/
```

O notebook pode funcionar como um hub permanente da casa mesmo quando o PC principal estiver desligado.

Entre as funções estão:

- Wake-on-LAN;
- controle de TVs;
- controle de dispositivos;
- encaminhamento de comandos;
- atualizações da central;
- acesso remoto autenticado.

Endereços IP, MACs, tokens e credenciais específicos de cada instalação devem permanecer fora do repositório.

---

# Projetos e Codex

A área **Projetos** permite selecionar uma pasta de trabalho e interagir com o Codex.

É possível:

- selecionar um projeto;
- enviar tarefas;
- acompanhar respostas;
- executar comandos PowerShell;
- trabalhar dentro do diretório selecionado.

Arquivos relacionados:

```text
.codex_capture.ps1
transfer_chat.py
grupo_chat.py
```

---

# Grupo

A aba **Grupo** permite manter uma conversa persistente envolvendo:

```text
Usuário
Nebula
Codex
```

O histórico é mantido localmente.

Execuções externas devem respeitar os mecanismos de autenticação e isolamento definidos pelo projeto.

---

# Memória e aprendizado

A Nebula possui memória própria para:

- contexto;
- preferências;
- correções de reconhecimento;
- feedback de conversas;
- vocabulário personalizado.

Arquivos principais:

```text
memoria_nebula.py
lexicon.py
contexto_nebula.md
```

Dados específicos do usuário são armazenados fora do repositório, normalmente em:

```text
%LOCALAPPDATA%\Nebula\
```

---

# Estrutura do projeto

Visão simplificada:

```text
Nebula/
|
|-- main.py
|-- gui.py
|-- remote_server.py
|-- memoria_nebula.py
|-- conversa_local.py
|
|-- android/
|   `-- app/
|
|-- assets/
|
|-- integracoes/
|   |-- beamng/
|   |-- simhub/
|   `-- wifi_bpm/
|
|-- native/
|   |-- nebula_boost/
|   `-- nebula_credential_provider/
|
|-- notebook_power_server/
|
|-- test_*.py
|
|-- requirements.txt
|-- requirements-dev.txt
|-- Nebula.spec
`-- build_release.ps1
```

---

# Instalação

## Requisitos

- Windows 10 ou Windows 11;
- Python 3.10 ou superior;
- PowerShell;
- Git.

Alguns recursos possuem dependências adicionais próprias.

---

## Criar ambiente Python

No PowerShell:

```powershell
python -m venv .venv
```

Ative o ambiente:

```powershell
.\.venv\Scripts\Activate.ps1
```

Instale as dependências:

```powershell
python -m pip install -r requirements.txt
```

Caso a política do PowerShell bloqueie a ativação:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

---

# Execução

## Assistente

```powershell
python main.py
```

## Interface gráfica

```powershell
python gui.py
```

## Modo texto

```powershell
python main.py --texto
```

## Modo texto sem abrir navegador

```powershell
python main.py --texto --sem-navegador
```

---

# Build Android

Abra:

```text
android/
```

no Android Studio.

O projeto utiliza Gradle e possui o wrapper incluído no repositório.

Para gerar um APK:

```text
Build
`-- Build APK(s)
```

O APK de desenvolvimento será criado dentro da pasta de build do Android.

---

# Build Windows

O projeto utiliza PyInstaller.

O arquivo de configuração principal é:

```text
Nebula.spec
```

Também existe o script:

```powershell
build_release.ps1
```

Os binários gerados não devem ser versionados no Git.

---

# Testes

Grande parte das integrações possui testes independentes.

Exemplos:

```text
test_abajur_tuya.py
test_beamng_turbo.py
test_conversa_local.py
test_memoria_nebula.py
test_modo_ambilight.py
test_modo_boost.py
test_modo_rpm.py
test_remote_device_session.py
test_wifi_bpm.py
```

Para executar os testes:

```powershell
pytest
```

---

# Documentação adicional

Documentações específicas ficam dentro de:

```text
integracoes/
native/
notebook_power_server/
```

Alguns documentos importantes:

```text
integracoes/PROTOCOL.md
integracoes/CONTROLE_UNIVERSAL.md
integracoes/CENTRAL_NOTEBOOK_A71.md
integracoes/beamng/README.md
integracoes/simhub/README.md
integracoes/wifi_bpm/README.md
```

---

# Segurança

A Nebula possui recursos capazes de controlar dispositivos, computadores e equipamentos da rede.

Por isso:

- não publique tokens;
- não publique senhas;
- não publique chaves locais da Tuya;
- não publique credenciais de pareamento;
- não coloque senhas diretamente no código;
- mantenha arquivos privados fora do Git;
- utilize variáveis de ambiente para informações sensíveis;
- mantenha IPs, MACs e dados específicos da sua rede fora da documentação pública.

O `.gitignore` do projeto deve bloquear os principais arquivos locais, builds e artefatos gerados.

---

# Tecnologias

A Nebula utiliza diferentes tecnologias de acordo com cada integração:

- Python;
- Java / Android;
- C++;
- C#;
- PowerShell;
- Gradle;
- PyInstaller;
- UDP;
- HTTP;
- Wake-on-LAN;
- Tuya LAN;
- Samsung Tizen;
- LG webOS;
- SimHub;
- APIs do Windows.

---

# Estado do projeto

A Nebula é um projeto experimental e em desenvolvimento contínuo.

Novos dispositivos, integrações e formas de interação são adicionados conforme o sistema evolui.

A arquitetura atual combina uma aplicação principal para Windows com módulos especializados, integrações nativas e centrais auxiliares para outros dispositivos.

---

## Nebula

**Uma central pessoal para conectar software, hardware, jogos e automação em um único sistema.**

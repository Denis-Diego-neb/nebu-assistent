"""Cliente do modelo de conversa que roda no notebook pela rede local."""

from __future__ import annotations

import json
import os
from collections import deque
import re
import unicodedata

import requests

from core.config import obter_url_ollama
from core.action_contracts import (
    AcaoQwen, ResultadoQwen, ContratoAcoes, ACOES_QWEN,
    ACOES_SEM_ARGUMENTO, LIMITES_ARGUMENTO, FORMATO_RESULTADO_QWEN,
)
from abajur_wifi import CORES, resolver_cor
from memoria_nebula import MEMORIA


PROMPT_SISTEMA = """Você é Nebula, uma assistente pessoal feminina que conversa em português brasileiro.
Seja natural, acolhedora, inteligente e levemente bem-humorada, sem repetir que é feita de CPU ou dizer que não tem emoções.
Responda em até três frases curtas, pois sua resposta será falada em voz alta. Em desabafos, escute, valide sem exagerar e faça no máximo uma pergunta útil.
Não finja ser psicóloga ou humana. Se houver risco imediato de automutilação ou suicídio, incentive ajuda humana imediata e, no Brasil, CVV 188 ou emergência 192/190.
Você é somente a camada de conversa: nunca afirme que abriu programas, executou comandos, acessou arquivos ou realizou ações no computador."""


PROMPT_INTERPRETADOR = """Você é a camada local de entendimento da Nebula. Classifique a mensagem do usuário como comando operacional ou conversa e devolva somente o JSON exigido pelo schema.

Use exatamente um destes formatos:
{"tipo":"comando","acoes":[{"acao":"nome_da_acao","argumento":"valor"}],"resposta":""}
{"tipo":"conversa","acoes":[],"resposta":"resposta curta em português"}

O Python é a única camada que executa ações. Você apenas traduz a intenção; nunca diga que executou, abriu, alterou ou controlou algo.

Para comando, use tipo "comando", resposta vazia e de uma a quatro ações na ordem pedida. Comandos compostos devem produzir várias ações. Use somente estas ações:
- abajur_ligar e abajur_desligar: argumento vazio.
- abajur_musica_iniciar: argumento vazio. Use para ativar/iniciar o modo música, animação musical, ritmo/"ritimo" do navegador, sincronizar, piscar ou pulsar com a música. O alvo abajur/lâmpada pode estar implícito.
- abajur_musica_parar: argumento vazio. Use SOMENTE quando houver pedido explícito de parar, desativar, desligar, encerrar ou cancelar o modo/animação musical. Mencionar "ritmo do navegador" nunca significa parar por si só.
- abajur_musica_intensidade: argumento inteiro de 1 a 100 para definir a força/contraste do pulso. Não confunda com o brilho fixo da lâmpada.
- abajur_musica_intensidade_aumentar e abajur_musica_intensidade_diminuir: argumento vazio; use quando pedirem pulso mais forte/intenso ou mais suave sem informar um valor.
- abajur_tocha_iniciar e abajur_tocha_parar: argumento vazio. O modo tocha imita chama variando tons de laranja e brilho e é independente do modo música.
- modo_rpm_iniciar e modo_rpm_parar: argumento vazio. Use para iniciar ou parar as luzes do controle e do abajur acompanhando o RPM/giro de qualquer jogo conectado por uma ponte de telemetria compatível, como SimHub.
- modo_rpm_status: argumento vazio. Use quando perguntarem se o modo RPM está ativo, conectado ou recebendo telemetria.
- modo_boost_iniciar e modo_boost_parar: argumento vazio. Use para iniciar ou parar o brilho do abajur acompanhando a quantidade de boost no Rocket League.
- modo_boost_status: argumento vazio. Use quando perguntarem se o modo boost está ativo ou recebendo telemetria.
- modo_ambilight_iniciar e modo_ambilight_parar: argumento vazio. Use para iniciar ou parar a lâmpada acompanhando a cor média das cenas visíveis da Netflix.
- modo_ambilight_status: argumento vazio. Use quando perguntarem se o Ambilight está ativo ou capturando a janela da Netflix.
- abajur_cor: argumento canônico vermelho, azul, verde, amarelo, roxo, rosa, ciano, hexadecimal #RRGGBB ou "rgb R G B".
- abajur_temperatura: argumento quente, neutra ou fria. "Temperatura mais baixa", "menos fria" e menor Kelvin significam quente; "temperatura mais alta" e maior Kelvin significam fria.
- abajur_brilho: ajuste absoluto; argumento contendo somente o inteiro de 1 a 100, sem sinal de porcentagem. Use quando a pessoa disser "coloque", "defina", "deixe em" ou "para 20%".
- abajur_diminuir_brilho e abajur_aumentar_brilho: ajuste relativo; argumento contendo somente o inteiro de 1 a 99. Use quando a pessoa disser "diminua/reduza em 20%", "diminua o brilho 20%" ou "aumente 20%".
- abrir_aplicativo e fechar_aplicativo: argumento com o nome do aplicativo.
- tocar_youtube e pesquisar_youtube: argumento com a música, vídeo ou busca.
- pesquisar_google: argumento com a busca.
- criar_nota: argumento com o texto da nota.
- encaminhar_codex: argumento com o pedido original completo, preservando código,
  maiúsculas e pontuação. Use quando o assunto for programação, depuração,
  refatoração, arquitetura de software ou quando o usuário pedir para falar com
  Codex. Não confunda código de verificação, QR code ou código de barras com
  programação. Não invente respostas técnicas em nome do Codex. Para encaminhar,
  retorne somente essa ação; a conversa continuará no canal Codex.
- pausar_midia, continuar_midia, aumentar_volume, diminuir_volume, capturar_tela, salvar_clipe, identificar_musica, ver_horas, abrir_emails e desligar_pc: argumento vazio.

Não transforme pedidos fora dessa lista em comandos. Nesse caso, trate como conversa e explique brevemente a limitação sem fingir sucesso.
Pedidos operacionais indiretos, informais ou educados continuam sendo comandos.
Exemplo: "seria legal se você iniciasse a calculadora" vira abrir_aplicativo com argumento "calculadora".
Exemplo: "essa luz está forte demais, reduz uns 20%" vira abajur_diminuir_brilho com argumento "20".
Exemplo: "deixe a luz mais gelada e deixe no ritimo do navegador" vira, nesta ordem, abajur_temperatura com "fria" e abajur_musica_iniciar com argumento vazio.
Exemplo: "ative a animação musical" vira abajur_musica_iniciar mesmo sem mencionar abajur ou lâmpada.
Exemplo: somente "pare/desative a animação musical" vira abajur_musica_parar.
Exemplo: "aumente a intensidade do pulso" vira abajur_musica_intensidade_aumentar; "coloque a intensidade do pulso em 90%" vira abajur_musica_intensidade com "90".
Exemplo: "ative o modo tocha" vira abajur_tocha_iniciar; "pare o modo tocha" vira abajur_tocha_parar.
Exemplo: "faça as luzes acompanharem o giro do carro" vira modo_rpm_iniciar; "pare as luzes de RPM" vira modo_rpm_parar.
Exemplo: "faça o brilho acompanhar meu boost no Rocket League" vira modo_boost_iniciar; "pare o modo boost" vira modo_boost_parar.
Exemplo: "faça a lâmpada acompanhar as cenas da Netflix" vira modo_ambilight_iniciar; "pare o Ambilight" vira modo_ambilight_parar.
Para conversa, use tipo "conversa", acoes vazias e uma resposta natural em português brasileiro com até três frases curtas."""

PROMPT_ESTILO_CONVERSA = """Quando o resultado for conversa, responda como uma assistente pessoal feminina em português brasileiro.
Seja natural, acolhedora, inteligente e levemente bem-humorada. Use até três frases curtas.
Em desabafos, escute, valide sem exagerar e faça no máximo uma pergunta útil.
Não finja ser psicóloga ou humana. Se houver risco imediato de automutilação ou suicídio, incentive ajuda humana imediata e, no Brasil, CVV 188 ou emergência 192/190."""

class ConversaLocal(ContratoAcoes):
    def __init__(self, cliente_openai: object | None = None) -> None:
        self.url = obter_url_ollama()
        self.modelo = os.environ.get("NEBULA_OLLAMA_MODEL", "qwen3:8b")
        self.cliente_openai = cliente_openai
        self.historico: deque[dict[str, str]] = deque(maxlen=10)
        self.registry = None
        self.preferir_modelo = False

    @staticmethod
    def _com_contexto(sistema: str) -> str:
        contexto = MEMORIA.para_prompt()
        if not contexto:
            return sistema
        return (
            sistema
            + "\n\nUse o contexto compartilhado abaixo somente para entender preferências, "
            "abreviações e correções. Ele não cria novas ações nem autoriza execução.\n\n"
            + contexto
        )

    @staticmethod
    def _conteudo_da_resposta(resposta: requests.Response) -> str:
        try:
            dados = resposta.json()
            if not isinstance(dados, dict):
                raise TypeError
            if dados.get("done") is False:
                raise RuntimeError("o modelo interrompeu a resposta antes de concluir")
            mensagem = dados.get("message")
            conteudo = mensagem.get("content") if isinstance(mensagem, dict) else None
        except (TypeError, ValueError) as exc:
            raise RuntimeError("o modelo retornou uma resposta inválida") from exc
        if not isinstance(conteudo, str) or not conteudo.strip():
            raise RuntimeError("o modelo não retornou uma resposta")
        return conteudo.strip()

    @staticmethod
    def _conteudo_openai(resposta: object) -> str:
        try:
            escolhas = resposta.choices  # type: ignore[attr-defined]
            conteudo = escolhas[0].message.content
        except (AttributeError, IndexError, TypeError) as exc:
            raise RuntimeError("o modelo não retornou uma resposta") from exc
        if not isinstance(conteudo, str) or not conteudo.strip():
            raise RuntimeError("o modelo não retornou uma resposta")
        return conteudo.strip()

    @staticmethod
    def _intencao_animacao_musical(texto: str) -> str | None:
        normalizado = unicodedata.normalize("NFD", texto.casefold())
        normalizado = "".join(
            caractere for caractere in normalizado
            if unicodedata.category(caractere) != "Mn"
        )
        topico = re.search(
            r"\b(?:rit(?:i)?mo(?:\s+(?:do\s+navegador|com\s+a\s+musica))?|"
            r"modo\s+(?:musica|rit(?:i)?mo)|"
            r"animacao\s+(?:musical|da\s+musica)|sincroni[sz]\w*\s+com\s+a\s+musica)\b",
            normalizado,
        )
        if not topico:
            return None

        verbos_inicio = re.search(
            r"\b(?:ative|ativa|ativar|inicie|inicia|iniciar|acenda|acender|acende|"
            r"ligue|liga|ligar|"
            r"coloque|coloca|colocar|deixe|deixa|deixar|bote|bota|botar|use|usar|"
            r"sincronize|sincroniza|sincronizar|reaja|reagir|pisque|piscar|pulse|pulsar)\b",
            normalizado,
        )
        verbos_parada = re.search(
            r"\b(?:pare|parar|desative|desativa|desativar|desligue|desliga|desligar|"
            r"encerre|encerrar|cancele|cancelar|interrompa|interromper)\b",
            normalizado,
        )
        negou_inicio = re.search(
            r"\bnao\s+(?:ative|ativar|inicie|iniciar|ligue|ligar|coloque|colocar|"
            r"use|usar|sincronize|sincronizar)\b",
            normalizado,
        )
        if negou_inicio or (verbos_inicio and verbos_parada):
            return None
        if verbos_parada:
            return "parar"
        if verbos_inicio:
            return "iniciar"
        if re.fullmatch(
            r"(?:o\s+)?(?:rit(?:i)?mo(?:\s+do\s+navegador)?|modo\s+musica)",
            normalizado.strip(" ,.?!"),
        ):
            return "iniciar"
        return None

    @classmethod
    def _reconciliar_animacao_musical(
        cls,
        texto: str,
        resultado: ResultadoQwen,
    ) -> ResultadoQwen:
        intencao = cls._intencao_animacao_musical(texto)
        if intencao is None:
            return resultado
        desejada = f"abajur_musica_{intencao}"
        if resultado.tipo == "conversa":
            return ResultadoQwen("comando", (AcaoQwen(desejada),))

        acoes_musicais = {"abajur_musica_iniciar", "abajur_musica_parar"}
        if not any(acao.acao in acoes_musicais for acao in resultado.acoes):
            return resultado
        corrigidas: list[AcaoQwen] = []
        musica_inserida = False
        for acao in resultado.acoes:
            if acao.acao not in acoes_musicais:
                corrigidas.append(acao)
            elif not musica_inserida:
                corrigidas.append(AcaoQwen(desejada))
                musica_inserida = True
        return ResultadoQwen("comando", tuple(corrigidas))

    @classmethod
    def _comando_direto_animacao_musical(cls, texto: str) -> ResultadoQwen | None:
        normalizado = unicodedata.normalize("NFD", texto.casefold())
        normalizado = "".join(
            caractere for caractere in normalizado
            if unicodedata.category(caractere) != "Mn"
        )
        intencao = cls._intencao_animacao_musical(texto)
        tema_ritmo = re.search(
            r"\b(?:rit(?:i)?mo|modo\s+(?:musica|rit(?:i)?mo)|pulso|animacao\s+musical)\b",
            normalizado,
        )
        percentual = re.search(
            r"\b(100|[1-9]?\d)\s*(?:%|por cento)(?=\s|$)", normalizado
        )
        fala_intensidade = re.search(
            r"\b(?:intensidade|forca|forte|intenso|intensa|suave)\b",
            normalizado,
        )
        if tema_ritmo and percentual and fala_intensidade:
            acoes: list[AcaoQwen] = []
            if intencao == "iniciar":
                acoes.append(AcaoQwen("abajur_musica_iniciar"))
            elif intencao == "parar":
                acoes.append(AcaoQwen("abajur_musica_parar"))
            acoes.append(
                AcaoQwen("abajur_musica_intensidade", percentual.group(1))
            )
            return ResultadoQwen("comando", tuple(acoes))

        if intencao is None and not (tema_ritmo and percentual):
            return None

        if intencao is None:
            intencao = "iniciar"

        acoes: list[AcaoQwen] = []
        pedido_ligar = re.search(
            r"\b(?:acenda|acender|acende|ligue|ligar|liga)\b", normalizado
        )
        pedido_curto = re.fullmatch(
            r"(?:o\s+)?modo\s+rit(?:i)?mo(?:\s+(?:no|do)\s+(?:abajur|navegador))?",
            normalizado.strip(" ,.?!"),
        )
        if not pedido_ligar and not pedido_curto:
            return None
        if pedido_ligar:
            acoes.append(AcaoQwen("abajur_ligar"))
        cor = cls._cor_direta(normalizado)
        if cor is not None:
            acoes.append(AcaoQwen("abajur_cor", cor))
        acoes.append(AcaoQwen(f"abajur_musica_{intencao}"))
        return ResultadoQwen("comando", tuple(acoes))

    @staticmethod
    def _cor_direta(texto: str) -> str | None:
        for palavra, cor in sorted(CORES.items(), key=lambda item: len(item[0]), reverse=True):
            padrao = rf"(?<![a-zà-ÿ]){re.escape(palavra)}(?![a-zà-ÿ])"
            if re.search(padrao, texto, flags=re.IGNORECASE):
                return cor
        hexadecimal = re.search(
            r"\b(?:hex|hexadecimal)\s*#?([0-9a-f]{6})\b", texto
        )
        if hexadecimal:
            return "#" + hexadecimal.group(1).upper()
        rgb = re.search(
            r"\brgb\s+(\d{1,3})[ ,]+(\d{1,3})[ ,]+(\d{1,3})\b", texto
        )
        if rgb:
            canais = tuple(map(int, rgb.groups()))
            if all(0 <= canal <= 255 for canal in canais):
                return "rgb " + " ".join(map(str, canais))
        return None

    def interpretar_ou_responder(self, texto: str) -> ResultadoQwen:
        comando_direto = None if self.preferir_modelo else self._comando_direto_animacao_musical(texto)
        if comando_direto is not None:
            return comando_direto
        sistema = self._com_contexto(
            PROMPT_INTERPRETADOR
            + "\n\nAo formular uma resposta de conversa, siga também estas diretrizes:\n"
            + PROMPT_ESTILO_CONVERSA
        )
        if self.registry is not None:
            sistema += "\n\nTools disponíveis neste host (use somente nomes deste catálogo):\n"
            sistema += json.dumps(self.registry.list_tools(), ensure_ascii=False)
        mensagens = [{"role": "system", "content": sistema}, *self.historico]
        mensagens.append({"role": "user", "content": texto})
        if self.cliente_openai is not None:
            resposta = self.cliente_openai.chat.completions.create(  # type: ignore[attr-defined]
                model=self.modelo,
                messages=mensagens,
                response_format={"type": "json_object"},
                temperature=0,
                max_tokens=500,
            )
            conteudo = self._conteudo_openai(resposta)
        else:
            resposta_http = requests.post(
                f"{self.url}/api/chat",
                json={
                    "model": self.modelo,
                    "messages": mensagens,
                    "format": "json",
                    "stream": False,
                    "think": False,
                    "options": {"temperature": 0, "num_predict": 500},
                    "keep_alive": "30m",
                },
                timeout=(5, 90),
            )
            resposta_http.raise_for_status()
            conteudo = self._conteudo_da_resposta(resposta_http)
        def validar_tool(item):
            if not isinstance(item, dict) or set(item) != {"acao", "argumento"}:
                raise RuntimeError("Formato de chamada inválido.")
            try:
                tool, arguments = self.registry.prepare({
                    "name": item["acao"], "arguments": {"argumento": item["argumento"]},
                })
            except ValueError as exc:
                raise RuntimeError(str(exc)) from exc
            return AcaoQwen(tool.name, arguments["argumento"])

        resultado = self._validar_resultado(
            conteudo, validar_tool if self.registry is not None else None,
        )
        if any(acao.acao == "encaminhar_codex" for acao in resultado.acoes):
            if len(resultado.acoes) != 1:
                raise RuntimeError("O encaminhamento ao Codex deve ser uma ação isolada.")
            resultado = ResultadoQwen("comando", (AcaoQwen("encaminhar_codex", texto),))
        elif not self.preferir_modelo:
            resultado = self._reconciliar_animacao_musical(texto, resultado)
        if resultado.tipo == "conversa":
            self.historico.append({"role": "user", "content": texto})
            self.historico.append({"role": "assistant", "content": resultado.resposta})
        return resultado

    def responder(self, texto: str) -> str:
        sistema = self._com_contexto(PROMPT_SISTEMA)
        mensagens = [{"role": "system", "content": sistema}, *self.historico]
        mensagens.append({"role": "user", "content": texto})
        if self.cliente_openai is not None:
            resposta = self.cliente_openai.chat.completions.create(  # type: ignore[attr-defined]
                model=self.modelo,
                messages=mensagens,
                temperature=0.72,
                max_tokens=180,
            )
            conteudo = self._conteudo_openai(resposta)
        else:
            resposta = requests.post(
                f"{self.url}/api/chat",
                json={
                    "model": self.modelo,
                    "messages": mensagens,
                    "stream": False,
                    "think": False,
                    "options": {"temperature": 0.72, "num_predict": 180},
                    "keep_alive": "30m",
                },
                timeout=(5, 90),
            )
            resposta.raise_for_status()
            conteudo = self._conteudo_da_resposta(resposta)
        self.historico.append({"role": "user", "content": texto})
        self.historico.append({"role": "assistant", "content": conteudo})
        return conteudo

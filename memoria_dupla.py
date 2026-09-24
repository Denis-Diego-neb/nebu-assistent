"""Memória comprimida entregue de uma IA para a outra.

Cada rodada da Dupla é uma instância nova de CLI, sem nenhuma memória das
anteriores. Quando uma esbarra no limite de crédito e a outra segue trabalhando,
a que volta horas depois não faz ideia do que aconteceu na ausência dela — e
recomeça propondo coisa já feita.

A marca d'água não precisa ser guardada em lugar nenhum: o último evento que a
própria agente assinou no diário já diz até onde ela viu. Tudo que veio depois é
exatamente o que ela perdeu. Isso não sai de sincronia e não cria arquivo de
estado para dar manutenção.

O resumo é montado por código, sem chamar modelo nenhum: ele precisa funcionar
justamente quando a agente está sem crédito, que é quando um resumo gerado por
IA seria impossível.
"""

from __future__ import annotations

import re

# O diário guarda muito evento de contabilidade que não ajuda quem volta.
RUIDO = {"tokens_reserved", "tokens_used", "task_claimed", "run_started"}

TITULOS = {
    "user_message": "Denis disse",
    "idea": "Pedido aberto",
    "confirmation": "Confirmação",
    "chat_reply": "Conversa",
    "chat_error": "Falha",
    "code_section": "Seção de código concluída",
    "task_planned": "Tarefa planejada",
    "note": "Recado de coordenação",
    "handoff": "Passagem de bastão",
    "run_finished": "Execução encerrada",
    "coordination": "Coordenação",
}

# "try again at 7:55 PM" / "tente novamente às 19:55"
_HORA = re.compile(r"(?:again at|às|as)\s+(\d{1,2}):(\d{2})\s*(AM|PM)?", re.IGNORECASE)


def sem_cota(texto: object) -> bool:
    """O CLI ficou sem crédito, e não é falha de login ou de rede."""
    baixo = str(texto or "").casefold()
    return any(marca in baixo for marca in (
        "usage limit", "rate limit", "credit balance", "quota", "limite de uso",
    ))


def volta_em(texto: object) -> str:
    """Hora em que a cota volta, extraída da mensagem do próprio CLI."""
    achado = _HORA.search(str(texto or ""))
    if not achado:
        return ""
    hora, minuto, periodo = int(achado.group(1)), achado.group(2), achado.group(3)
    if periodo and periodo.upper() == "PM" and hora < 12:
        hora += 12
    if periodo and periodo.upper() == "AM" and hora == 12:
        hora = 0
    return f"{hora:02d}:{minuto}"


def _linha(evento: dict) -> str:
    dados = evento.get("data") or {}
    titulo = TITULOS.get(evento.get("kind"), str(evento.get("kind")))
    corpo = dados.get("text") or dados.get("summary") or dados.get("title") or ""
    if evento.get("kind") == "code_section":
        # O que a outra fez importa mais que o texto solto: título, arquivos
        # tocados e a prova de que funcionou.
        arquivos = ", ".join(dados.get("paths") or [])
        corpo = f"{dados.get('title', '')} [{arquivos}] — {dados.get('summary', '')}"
        if dados.get("evidence"):
            corpo += f" Verificação: {dados['evidence']}"
    quando = str(evento.get("at", ""))[11:16]
    return f"- {quando} {titulo} ({evento.get('actor')}): {str(corpo).strip()}"


def digerir(estado: dict, agente: str, limite: int = 7000) -> str:
    """Resumo comprimido do que ``agente`` perdeu desde a última vez que falou.

    Vazio quando não há lacuna — na primeira rodada não há o que recuperar, e
    encher o prompt com o diário inteiro só gastaria contexto.
    """
    eventos = estado.get("messages") or []
    vistos = [e.get("seq", 0) for e in eventos if e.get("actor") == agente]
    if not vistos:
        return ""
    corte = max(vistos)
    perdidos = [e for e in eventos
                if e.get("seq", 0) > corte and e.get("kind") not in RUIDO]
    if not perdidos:
        return ""

    # Mais novo primeiro para o corte de tamanho descartar o que já é história.
    linhas, total = [], 0
    for evento in reversed(perdidos):
        linha = _linha(evento)[:900]
        if total + len(linha) > limite:
            linhas.append(f"- (mais {len(perdidos) - len(linhas)} eventos anteriores omitidos)")
            break
        linhas.append(linha)
        total += len(linha)
    linhas.reverse()

    abertas = [t for t in estado.get("tasks") or []
               if t.get("status") in ("queued", "running", "interrupted")]
    fila = [f"- {t['title']} · dono {t['owner']} · {t['status']} · reserva {', '.join(t['paths'])}"
            for t in abertas[:8]]

    partes = [
        f"MEMÓRIA COMPRIMIDA — o que passou desde a sua última rodada "
        f"(eventos {corte + 1} em diante). Você não estava presente; trate como "
        f"fato já ocorrido, não como pedido novo.",
        *linhas,
    ]
    if fila:
        partes += ["", "Ainda em aberto agora:", *fila]
    partes.append("")
    partes.append("Não refaça o que já está concluído acima. Se uma tarefa sua "
                  "ficou pela metade porque você ficou sem crédito, continue de "
                  "onde parou.")
    return "\n".join(partes)


def anotar_falta_de_cota(store, agente: str, motivo: str) -> None:
    """Registra no diário que a agente saiu, e quando volta.

    Sem isto a outra vê só silêncio e não tem como saber se deve assumir o que
    faltou ou se é melhor esperar.
    """
    if not sem_cota(motivo):
        return
    ideias = store.snapshot().get("ideas") or []
    if not ideias:
        return
    hora = volta_em(motivo)
    volta = f" A cota volta por volta de {hora}." if hora else ""
    try:
        store.message(
            ideias[-1]["id"], "system",
            f"{agente} ficou sem crédito e saiu da rodada.{volta} "
            f"A outra assume o que faltou; quando {agente} voltar, recebe a memória "
            f"comprimida do que passou. Motivo do CLI: {str(motivo)[:400]}",
            "handoff",
        )
    except Exception:
        # O diário é registro, não caminho crítico: falhar aqui não pode
        # derrubar a rodada que ainda está de pé.
        pass

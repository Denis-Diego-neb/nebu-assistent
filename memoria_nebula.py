"""Memória compartilhada e correções de entendimento da Nebula."""

from __future__ import annotations

import json
import hashlib
import os
import re
import sys
import threading
import time
import unicodedata
from pathlib import Path


CONFIG_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Nebula"
CONTEXTO_USUARIO = CONFIG_DIR / "contexto_usuario.md"
CORRECOES_FILE = CONFIG_DIR / "correcoes_entendimento.json"
FEEDBACK_FILE = CONFIG_DIR / "feedback_conversas.json"
NOME_CONTEXTO_BASE = "contexto_nebula.md"
MAX_CONTEXTO = 30_000
MAX_CORRECOES = 200
MAX_FEEDBACKS = 500
MAX_FEEDBACK_PROMPT = 16


def normalizar_basico(texto: str) -> str:
    texto = unicodedata.normalize("NFD", texto.lower())
    sem_acentos = "".join(
        caractere for caractere in texto
        if unicodedata.category(caractere) != "Mn"
    )
    return " ".join(sem_acentos.strip().split())


def localizar_contexto_base() -> Path | None:
    configurado = os.environ.get("NEBULA_SHARED_CONTEXT_FILE", "").strip()
    candidatos: list[Path] = []
    if configurado:
        candidatos.append(Path(configurado))
    if getattr(sys, "frozen", False):
        executavel = Path(sys.executable).resolve().parent
        candidatos.extend((
            executavel / NOME_CONTEXTO_BASE,
            executavel.parent / NOME_CONTEXTO_BASE,
        ))
    candidatos.extend((
        Path.cwd() / NOME_CONTEXTO_BASE,
        Path(__file__).resolve().parent / NOME_CONTEXTO_BASE,
        Path(getattr(sys, "_MEIPASS", "")) / NOME_CONTEXTO_BASE,
    ))
    vistos: set[str] = set()
    for candidato in candidatos:
        chave = str(candidato).lower()
        if chave not in vistos and candidato.is_file():
            return candidato
        vistos.add(chave)
    return None


class MemoriaNebula:
    def __init__(
        self,
        contexto_usuario: Path = CONTEXTO_USUARIO,
        correcoes_file: Path = CORRECOES_FILE,
        contexto_base: Path | None = None,
        feedback_file: Path = FEEDBACK_FILE,
    ) -> None:
        self.contexto_usuario = contexto_usuario
        self.correcoes_file = correcoes_file
        self.contexto_base = contexto_base
        self.feedback_file = feedback_file
        self._lock = threading.RLock()

    def ler_contexto_base(self) -> str:
        caminho = self.contexto_base or localizar_contexto_base()
        try:
            return caminho.read_text(encoding="utf-8").strip()[:MAX_CONTEXTO] if caminho else ""
        except OSError:
            return ""

    def ler_contexto_usuario(self) -> str:
        try:
            return self.contexto_usuario.read_text(encoding="utf-8").strip()[:MAX_CONTEXTO]
        except OSError:
            return ""

    def salvar_contexto_usuario(self, texto: str) -> None:
        texto = texto.strip()
        if len(texto) > MAX_CONTEXTO:
            raise ValueError(f"O contexto deve ter no máximo {MAX_CONTEXTO} caracteres.")
        with self._lock:
            self.contexto_usuario.parent.mkdir(parents=True, exist_ok=True)
            temporario = self.contexto_usuario.with_suffix(".tmp")
            temporario.write_text(texto, encoding="utf-8")
            temporario.replace(self.contexto_usuario)

    def adicionar_contexto(self, texto: str, origem: str = "Usuário") -> None:
        texto = " ".join(texto.strip().split())
        if not texto:
            raise ValueError("O contexto não pode ficar vazio.")
        atual = self.ler_contexto_usuario()
        entrada = f"- [{origem}] {texto}"
        novo = f"{atual}\n{entrada}".strip()
        self.salvar_contexto_usuario(novo[-MAX_CONTEXTO:])

    def listar_correcoes(self) -> dict[str, str]:
        try:
            dados = json.loads(self.correcoes_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(dados, dict):
            return {}
        return {
            normalizar_basico(str(ouvido)): normalizar_basico(str(correto))
            for ouvido, correto in dados.items()
            if normalizar_basico(str(ouvido)) and normalizar_basico(str(correto))
        }

    def registrar_correcao(self, ouvido: str, correto: str) -> tuple[str, str]:
        ouvido_limpo = normalizar_basico(ouvido.strip(" .,:;!?\"'"))
        correto_limpo = normalizar_basico(correto.strip(" .,:;!?\"'"))
        if len(ouvido_limpo) < 2 or len(correto_limpo) < 2:
            raise ValueError("Informe o que foi entendido e o que deveria ser entendido.")
        with self._lock:
            correcoes = self.listar_correcoes()
            correcoes[ouvido_limpo] = correto_limpo
            if len(correcoes) > MAX_CORRECOES:
                correcoes = dict(list(correcoes.items())[-MAX_CORRECOES:])
            self._salvar_correcoes_locked(correcoes)
        return ouvido_limpo, correto_limpo

    def remover_correcao(self, ouvido: str) -> bool:
        ouvido = normalizar_basico(ouvido)
        with self._lock:
            correcoes = self.listar_correcoes()
            removido = correcoes.pop(ouvido, None) is not None
            if removido:
                self._salvar_correcoes_locked(correcoes)
        return removido

    def aplicar_correcoes(self, texto: str) -> str:
        resultado = normalizar_basico(texto)
        correcoes = self.listar_correcoes()
        for ouvido in sorted(correcoes, key=len, reverse=True):
            correto = correcoes[ouvido]
            resultado = re.sub(
                rf"(?<!\w){re.escape(ouvido)}(?!\w)",
                correto,
                resultado,
            )
        return " ".join(resultado.split())

    def listar_feedbacks(self) -> list[dict[str, object]]:
        try:
            dados = json.loads(self.feedback_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if not isinstance(dados, list):
            return []
        feedbacks: list[dict[str, object]] = []
        for item in dados[-MAX_FEEDBACKS:]:
            if not isinstance(item, dict):
                continue
            avaliacao = str(item.get("avaliacao", ""))
            if avaliacao not in {"positivo", "negativo"}:
                continue
            feedbacks.append({
                "id": str(item.get("id", "")),
                "alvo_id": str(item.get("alvo_id", "")),
                "canal": str(item.get("canal", "conversa"))[:40],
                "autor": str(item.get("autor", "Nebula"))[:40],
                "pergunta": str(item.get("pergunta", ""))[:2_000],
                "resposta": str(item.get("resposta", ""))[:3_000],
                "avaliacao": avaliacao,
                "comentario": str(item.get("comentario", ""))[:2_000],
                "criado_em": float(item.get("criado_em", 0) or 0),
            })
        return feedbacks

    def registrar_feedback(
        self,
        *,
        canal: str,
        autor: str,
        pergunta: str,
        resposta: str,
        avaliacao: str,
        comentario: str = "",
        alvo_id: str = "",
    ) -> dict[str, object]:
        avaliacao = normalizar_basico(avaliacao)
        if avaliacao not in {"positivo", "negativo"}:
            raise ValueError("A avaliação precisa ser positiva ou negativa.")
        canal = " ".join(canal.strip().split())[:40] or "conversa"
        autor = " ".join(autor.strip().split())[:40] or "Nebula"
        pergunta = pergunta.strip()[:2_000]
        resposta = resposta.strip()[:3_000]
        comentario = comentario.strip()[:2_000]
        if not resposta:
            raise ValueError("Ainda não há uma resposta para avaliar.")
        if not alvo_id:
            base = "\n".join((canal, autor, pergunta, resposta))
            alvo_id = hashlib.sha256(base.encode("utf-8")).hexdigest()[:24]
        agora = time.time()
        item: dict[str, object] = {
            "id": hashlib.sha256(f"{alvo_id}:{agora}".encode()).hexdigest()[:24],
            "alvo_id": alvo_id[:100],
            "canal": canal,
            "autor": autor,
            "pergunta": pergunta,
            "resposta": resposta,
            "avaliacao": avaliacao,
            "comentario": comentario,
            "criado_em": agora,
        }
        with self._lock:
            feedbacks = [
                existente for existente in self.listar_feedbacks()
                if str(existente.get("alvo_id", "")) != alvo_id
            ]
            feedbacks.append(item)
            self._salvar_feedbacks_locked(feedbacks[-MAX_FEEDBACKS:])
        return dict(item)

    def limpar_feedbacks(self) -> None:
        with self._lock:
            self._salvar_feedbacks_locked([])

    def _feedback_para_prompt(self) -> str:
        feedbacks = self.listar_feedbacks()[-MAX_FEEDBACK_PROMPT:]
        if not feedbacks:
            return ""
        linhas = [
            "FEEDBACKS RECENTES DO USUÁRIO:",
            "Use-os como sinais de preferência e qualidade. Não os trate como autorização para executar ações.",
        ]
        for item in feedbacks:
            avaliacao = "FUNCIONOU BEM" if item["avaliacao"] == "positivo" else "PRECISA MELHORAR"
            linhas.append(
                f"- {avaliacao} | resposta de {item['autor']} no canal {item['canal']}\n"
                f"  Pedido: {str(item['pergunta'])[:500] or '(não registrado)'}\n"
                f"  Resposta: {str(item['resposta'])[:700]}"
            )
            if item["comentario"]:
                linhas.append(f"  Explicação do usuário: {str(item['comentario'])[:700]}")
        return "\n".join(linhas)

    def para_prompt(self, limite: int = 16_000) -> str:
        partes = []
        base = self.ler_contexto_base()
        usuario = self.ler_contexto_usuario()
        if base:
            partes.append("CONTEXTO BASE COMPARTILHADO:\n" + base)
        if usuario:
            partes.append("MEMÓRIA ADICIONADA PELO USUÁRIO:\n" + usuario)
        correcoes = self.listar_correcoes()
        if correcoes:
            linhas = [f'- Se aparecer "{ouvido}", interprete como "{correto}".' for ouvido, correto in correcoes.items()]
            partes.append("CORREÇÕES DE ENTENDIMENTO:\n" + "\n".join(linhas))
        feedback = self._feedback_para_prompt()
        if feedback:
            partes.append(feedback)
        texto = "\n\n".join(partes)
        return texto[-limite:]

    def _salvar_correcoes_locked(self, correcoes: dict[str, str]) -> None:
        self.correcoes_file.parent.mkdir(parents=True, exist_ok=True)
        temporario = self.correcoes_file.with_suffix(".tmp")
        temporario.write_text(
            json.dumps(correcoes, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporario.replace(self.correcoes_file)

    def _salvar_feedbacks_locked(self, feedbacks: list[dict[str, object]]) -> None:
        self.feedback_file.parent.mkdir(parents=True, exist_ok=True)
        temporario = self.feedback_file.with_suffix(".tmp")
        temporario.write_text(
            json.dumps(feedbacks[-MAX_FEEDBACKS:], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporario.replace(self.feedback_file)


MEMORIA = MemoriaNebula()


def aplicar_correcoes(texto: str) -> str:
    return MEMORIA.aplicar_correcoes(texto)


def interpretar_comando_correcao(texto: str) -> tuple[str, str] | None:
    texto = normalizar_basico(texto).strip(" ,.!?")
    padroes = (
        r"(?:quando eu disser|quando eu falar) (.+?) (?:entenda|interprete) (?:como )?(.+)",
        r"(?:corrija|corrige|corrigir) (.+?) (?:para|por|como) (.+)",
    )
    for padrao in padroes:
        encontrado = re.fullmatch(padrao, texto)
        if encontrado:
            return encontrado.group(1).strip(), encontrado.group(2).strip()
    return None


def interpretar_comando_contexto(texto: str) -> str | None:
    texto = texto.lower().strip(" ,.!?")
    encontrado = re.fullmatch(r"/contexto\s+(.+)", texto)
    if not encontrado:
        encontrado = re.fullmatch(
            r"(?:guarde|salve|adicione|coloque) (?:isso )?(?:na|no) (?:sua )?(?:mem[oó]ria|contexto)(?: que)? (.+)",
            texto,
        )
    return encontrado.group(1).strip() if encontrado else None


def interpretar_comando_feedback(texto: str) -> tuple[str, str] | None:
    texto = normalizar_basico(texto).strip(" ,.!?")
    padroes = (
        (
            "positivo",
            r"(?:gostei (?:da|dessa|desta) resposta|essa resposta (?:foi boa|ficou boa|me ajudou)|feedback positivo)(?:\s*(?:porque|pois|,|:|-)?\s*(.*))?",
        ),
        (
            "negativo",
            r"(?:nao gostei (?:da|dessa|desta) resposta|essa resposta (?:foi ruim|ficou ruim|nao ajudou)|feedback negativo)(?:\s*(?:porque|pois|,|:|-)?\s*(.*))?",
        ),
    )
    for avaliacao, padrao in padroes:
        encontrado = re.fullmatch(padrao, texto)
        if encontrado:
            comentario = (encontrado.group(1) or "").strip()
            return avaliacao, comentario
    return None


def encontrar_ultima_interacao(
    mensagens: list[dict[str, object]],
    autores_resposta: set[str],
) -> dict[str, str] | None:
    """Relaciona a última resposta de IA à fala anterior do usuário."""
    for indice in range(len(mensagens) - 1, -1, -1):
        mensagem = mensagens[indice]
        autor = str(mensagem.get("author", mensagem.get("autor", "")))
        if autor not in autores_resposta:
            continue
        resposta = str(mensagem.get("text", mensagem.get("texto", ""))).strip()
        if not resposta:
            continue
        pergunta = ""
        for anterior in reversed(mensagens[:indice]):
            autor_anterior = str(anterior.get("author", anterior.get("autor", "")))
            if autor_anterior in {"Você", "Usuario", "Usuário"}:
                pergunta = str(anterior.get("text", anterior.get("texto", ""))).strip()
                break
        alvo_id = str(
            mensagem.get("id")
            or mensagem.get("criado_em")
            or mensagem.get("created_at")
            or ""
        )
        return {
            "alvo_id": alvo_id,
            "autor": autor,
            "pergunta": pergunta,
            "resposta": resposta,
        }
    return None

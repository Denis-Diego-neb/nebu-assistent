"""Provedor da Dupla com acesso real ao repositório.

O provedor padrão em ``services/collaboration/providers.py`` chama os CLIs sem
ferramenta nenhuma: ``--tools ""`` no Claude e ``--sandbox read-only`` no Codex.
Nesse modo o agente planeja vendo só a lista de nomes da raiz, enxerga apenas os
arquivos que o coordenador cola no prompt, não dá grep, não roda teste e não
itera sobre uma falha — foi a limitação que o Denis apontou ao perguntar de que
serve o modo Dupla sem acesso ao VS Code.

Aqui o mesmo CLI é chamado com ferramentas de verdade, pela porta que o próprio
backend abre: ``CollaborationAPI(raiz, provider=...)``. Nada em
``services/collaboration/`` é alterado — aquele módulo é do outro agente.

O que **não** muda: a reserva de arquivos continua valendo. ``store.claim``
recusa duas seções com caminhos sobrepostos ao mesmo tempo, e isso acontece
antes de o agente rodar. É de graça e é o que impede as duas de se atropelarem,
então não há motivo para abrir mão só porque agora elas escrevem sozinhas.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile

import memoria_dupla
import uso_ias
from services.collaboration.providers import (
    CLIProvider, executable, parse_claude, parse_codex,
)

# Ferramentas nomeadas uma a uma, para ficar auditável no código em vez de
# depender do que for o padrão do CLI em cada versão.
FERRAMENTAS_CLAUDE = "Read,Grep,Glob,Bash,Edit,Write"

# Uma rodada de desenvolvimento de verdade lê, edita e roda teste; os 240 s do
# provedor original só davam para uma resposta de texto.
SEGUNDOS = int(os.environ.get("NEBULA_COLLAB_TIMEOUT", "900"))

# Os prompts do coordenador proíbem ferramentas, porque foram escritos para o
# modo sem acesso. Como não posso editar aquele arquivo, a autorização vem por
# fora e diz exatamente qual parte fica sem efeito.
AUTORIZACAO = (
    "AUTORIZAÇÃO DO OPERADOR — precede o texto abaixo.\n"
    "Denis liberou acesso total ao repositório nesta rodada. Você pode e deve usar "
    "ferramentas: ler, procurar, editar arquivos e rodar comandos e testes em {raiz}.\n"
    "Onde o texto abaixo disser para não usar ferramentas, não escrever no disco ou "
    "não executar comandos, essa parte está sem efeito. Todo o resto continua "
    "valendo: o schema da resposta, os arquivos reservados para a sua seção e a "
    "proibição de mexer em credenciais, .git, binários, publicação e instalação.\n"
    "Verifique o seu próprio trabalho antes de responder: rode o teste que cobre o "
    "que você mexeu. Mesmo tendo gravado os arquivos, devolva o conteúdo final deles "
    "no schema — é com isso que a outra IA revisa antes da seção ser dada por "
    "concluída.\n"
    "--- pedido do coordenador a partir daqui ---\n"
)

RODAPE_MEMORIA = """
--- fim da memória recuperada; o pedido do coordenador vem a seguir ---
"""


def motivo(saida: str, erro: str) -> str:
    """Extrai o motivo real da falha do CLI.

    O provedor original devolvia só "falhou (código 1); confira login e
    disponibilidade". Quando o Codex estourou a cota, a mensagem verdadeira —
    limite atingido e a hora em que volta — ficava escondida no stdout, e nem o
    usuário nem a outra IA tinham como saber que era questão de crédito, que é
    justamente quando uma precisa assumir o que faltou da outra.
    """
    for linha in (saida or "").splitlines():
        try:
            evento = json.loads(linha)
        except ValueError:
            continue
        if not isinstance(evento, dict):
            continue
        # Codex: {"type":"error"|"turn.failed", ...}. Claude: envelope com is_error.
        texto = evento.get("message")
        if isinstance(evento.get("error"), dict):
            texto = evento["error"].get("message") or texto
        if evento.get("is_error"):
            texto = evento.get("result") or texto
        if texto:
            return str(texto)[:600]
    ultima = [l for l in (erro or "").splitlines() if l.strip()]
    return ultima[-1][:600] if ultima else "o CLI terminou sem explicar o motivo."


def linha_de_uso() -> str:
    """Quanto resta de cada uma, para dividirem o trabalho sabendo disso."""
    try:
        return uso_ias.resumo_para_agentes(uso_ias.uso()) + chr(10)
    except Exception:
        return ""


class ProvedorComAcesso(CLIProvider):
    """Mesmos CLIs, mesma leitura de resposta, com ferramentas ligadas.

    Herda de ``CLIProvider`` de propósito: ``Coordinator.start`` faz
    ``isinstance(self.provider, CLIProvider)`` para exigir raiz de repositório
    Git antes de soltar os agentes, e essa exigência deve continuar valendo —
    com escrita direta, o Git é a única forma de desfazer.
    """

    def __init__(self, timeout: int = SEGUNDOS, store=None) -> None:
        super().__init__(timeout=timeout)
        # Preenchido pelo adaptador depois que a API monta o store: e dele que
        # sai a memoria comprimida entregue a quem voltou de um corte de cota.
        self.store = store

    def memoria(self, agent: str) -> str:
        if self.store is None:
            return ""
        try:
            return memoria_dupla.digerir(self.store.snapshot(), agent)
        except Exception:
            return ""

    def develop(self, agent, prompt, cwd, **kwargs):
        # O modo de desenvolvimento é do Codex; aqui só entra a linha de uso.
        return super().develop(agent, linha_de_uso() + prompt, cwd, **kwargs)

    def complete(self, agent, prompt, schema, cwd):
        comando = executable(agent)
        if not comando:
            raise RuntimeError(f"CLI de {agent} indisponível.")
        modelo = os.getenv(f"NEBULA_COLLAB_{agent.upper()}_MODEL",
                           "opus" if agent == "opus" else "configured")
        raiz = str(Path(cwd).resolve())
        recuperada = self.memoria(agent)
        texto = AUTORIZACAO.format(raiz=raiz) + linha_de_uso()
        if recuperada:
            texto += recuperada + RODAPE_MEMORIA
        texto += prompt
        with tempfile.TemporaryDirectory(prefix="nebula-dupla-schema-") as temporario:
            arquivo = Path(temporario) / "response.json"
            arquivo.write_text(json.dumps(schema), encoding="utf-8")
            if agent == "codex":
                argumentos = [comando, "exec", "--json", "--ephemeral",
                              # workspace-write escreve dentro do projeto e não
                              # fora dele; danger-full-access nunca é necessário.
                              "--sandbox", "workspace-write",
                              "--output-schema", str(arquivo), "--color", "never"]
                if modelo != "configured":
                    argumentos += ["--model", modelo]
                argumentos.append("-")
            else:
                argumentos = [comando, "--print", "--output-format", "json",
                              "--model", modelo, "--json-schema", json.dumps(schema),
                              "--tools", FERRAMENTAS_CLAUDE,
                              # --tools so diz quais ferramentas EXISTEM. Com
                              # --permission-mode dontAsk, toda ferramenta que
                              # pediria permissao e negada em silencio, entao sem
                              # esta pre-aprovacao Bash, Edit e Write ficavam
                              # bloqueados e o "acesso total" era so leitura.
                              "--allowedTools", FERRAMENTAS_CLAUDE,
                              "--add-dir", raiz,
                              "--strict-mcp-config", "--no-session-persistence",
                              "--permission-mode", "dontAsk"]
            resultado = subprocess.run(
                argumentos, input=texto, cwd=raiz, text=True, encoding="utf-8",
                errors="replace", capture_output=True, timeout=self.timeout,
                shell=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if resultado.returncode:
                explicacao = motivo(resultado.stdout, resultado.stderr)
                if self.store is not None:
                    memoria_dupla.anotar_falta_de_cota(self.store, agent, explicacao)
                raise RuntimeError(f"{agent}: {explicacao}")
        # Sem --model o Codex usa o do config.toml e só informaria "configured";
        # guardar o modelo de verdade é o que deixa o chat mostrar quem respondeu.
        exibir = modelo if modelo != "configured" else (uso_ias.modelo_codex().get("texto") or modelo)
        return (parse_codex(resultado.stdout, exibir) if agent == "codex"
                else parse_claude(resultado.stdout, modelo))


def ativo() -> bool:
    """Desligar volta ao provedor sem ferramentas, sem recompilar nada."""
    return os.environ.get("NEBULA_DUPLA_SEM_FERRAMENTAS", "").strip() != "1"

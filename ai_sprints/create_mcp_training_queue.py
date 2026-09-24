"""Materializa 40 exercicios MCP independentes na fila do autopilot."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = ROOT / "ai_sprints" / "candidates"
QUEUE = ROOT / "ai_sprints" / "queue"


EXERCISES = (
    ("tool_contract", "Modele um contrato imutavel de tool com nome, descricao, inputSchema e resultado JSON."),
    ("strict_arguments", "Crie validacao de argumentos que rejeite campos extras, tipos errados e objetos ausentes."),
    ("registry_example", "Registre uma tool pura de exemplo sem rede, hardware ou estado global."),
    ("deterministic_list", "Produza um catalogo de tools com ordem deterministica e schemas copiados defensivamente."),
    ("named_call", "Execute uma tool pelo nome usando somente argumentos estruturados previamente validados."),
    ("tool_errors", "Modele erros distintos para entrada invalida, tool indisponivel e falha de execucao."),
    ("safe_error", "Converta excecoes internas em resultado seguro sem vazar traceback ou detalhes privados."),
    ("no_natural_language", "Demonstre por teste que o dispatcher rejeita texto livre e nunca interpreta linguagem natural."),
    ("lamp_on", "Modele a tool abajur_ligar com dependencia de dispositivo injetada e argumentos vazios."),
    ("lamp_off", "Modele a tool abajur_desligar preservando idempotencia e retorno estruturado."),
    ("lamp_status", "Modele uma tool abajur_status somente leitura, incluindo o caso de dispositivo offline."),
    ("iot_bootstrap", "Componha tres tools IoT em uma funcao de registro sem importar o host principal."),
    ("empty_schema", "Crie schema de entrada vazio que rejeite qualquer propriedade adicional."),
    ("device_discovery", "Separe descoberta do dispositivo da execucao de comandos usando protocolos injetaveis."),
    ("adapter_timeout", "Modele timeout do adaptador IoT sem acessar rede real e com erro de dominio."),
    ("idempotent_power", "Implemente contrato idempotente para ligar e desligar um dispositivo repetidamente."),
    ("mcp_tools_list", "Adapte um catalogo local para uma resposta MCP tools/list estruturada."),
    ("mcp_tools_call", "Adapte tools/call para validar argumentos antes de chamar o handler."),
    ("server_boundaries", "Demonstre que um servidor executor nao importa modelo, prompts ou roteamento."),
    ("server_health", "Modele health de servidor com identidade e capacidades, sem expor credenciais."),
    ("mcp_error_result", "Converta erros de dominio em resultados MCP estruturados e estaveis."),
    ("server_allowlist", "Aplique allowlist de tools no servidor sem codificar decisoes no dispatcher."),
    ("server_unknown_tool", "Rejeite tools desconhecidas e argumentos extras antes de qualquer efeito."),
    ("local_roundtrip", "Simule um roundtrip tools/list e tools/call inteiramente em memoria."),
    ("device_descriptor", "Modele descritor de dispositivo com id, nome, endpoint LAN e tools anunciadas."),
    ("discovery_cache", "Implemente cache curto de descoberta com relogio injetado e invalidacao explicita."),
    ("catalog_merge", "Mescle catalogos de varios dispositivos preservando a origem de cada tool."),
    ("tool_namespace", "Resolva colisoes por namespace como pc.open_app e iot.abajur_ligar."),
    ("route_discovered", "Escolha uma rota somente entre tools previamente descobertas."),
    ("partial_availability", "Mantenha tools saudaveis quando um dos dispositivos estiver indisponivel."),
    ("remote_fallback", "Modele fallback LAN para rota remota abstrata sem SSH ou segredo no codigo."),
    ("discover_before_call", "Garanta que uma tool nova seja descoberta antes da primeira chamada."),
    ("llm_catalog", "Prepare para a Qwen apenas nomes, descricoes e schemas das tools descobertas."),
    ("validate_llm_call", "Valide nome e argumentos de uma tool call produzida por modelo antes do roteamento."),
    ("decision_execution", "Separe uma decisao de tool call da execucao do handler em componentes distintos."),
    ("structured_result", "Converta resultado de tool em contexto estruturado para o modelo sem concatenar comandos."),
    ("retry_budget", "Implemente limite de tentativas para tool indisponivel usando relogio e sleeper injetados."),
    ("codex_handoff", "Modele encaminhamento de pedidos de codigo para um canal Codex sem executar no servidor."),
    ("safe_audit", "Registre auditoria de chamadas ocultando token e argumentos marcados como sensiveis."),
    ("three_device_sim", "Simule descoberta e roteamento entre PC, notebook e servidor de casa."),
)


def evidence_for(number: int) -> list[dict[str, object]]:
    if number <= 8:
        return [
            {"path": "core/registry.py", "symbols": ["Tool", "Registry.prepare"]},
            {"path": "core/dispatcher.py", "symbols": ["Dispatcher.execute_plan"]},
        ]
    if number <= 16:
        return [
            {"path": "modules/iot/lights.py", "symbols": ["pedido_da_tool", "executar_pedidos_abajur"]},
            {"path": "core/registry.py", "symbols": ["Tool"]},
        ]
    if number <= 24:
        return [
            {"path": "services/tool_server.py", "symbols": ["ToolServer", "ToolHandler.do_POST"]},
            {"path": "core/dispatcher.py", "symbols": ["Dispatcher.call_tool"]},
        ]
    if number <= 32:
        return [
            {"path": "services/network.py", "symbols": ["DeviceEndpoint", "DeviceConnection.discover", "DeviceConnection.call_tool"]},
            {"path": "core/registry.py", "symbols": ["Registry.list_tools"]},
        ]
    return [
        {"path": "core/bootstrap.py", "symbols": ["criar_dispatcher"]},
        {"path": "core/dispatcher.py", "symbols": ["Dispatcher.execute_plan"]},
    ]


def write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    for number, (slug, objective) in enumerate(EXERCISES, start=1):
        job_id = f"mcp_train_{number:02d}_{slug}"
        module_path = f"modules/mcp_training_{number:02d}.py"
        test_path = f"tests/test_mcp_training_{number:02d}.py"
        candidate_path = CANDIDATES / f"{job_id}.json"
        write_json(candidate_path, {
            "id": job_id,
            "objective": (
                f"Exercicio MCP {number:02d}/40: {objective} "
                f"Implemente o exemplo isolado em {module_path} e seus testes em {test_path}."
            ),
            "evidence": evidence_for(number),
            "acceptance": [
                "A implementacao usa somente a biblioteca padrao e nao importa main.py, Qwen, Gemini ou Codex.",
                "Entradas e saidas sao objetos estruturados; nenhuma funcao interpreta frases do usuario.",
                "Rede, hardware, relogio e espera, quando necessarios, sao dependencias injetadas.",
                "Os testes usam unittest, nao acessam rede ou hardware e cobrem sucesso e rejeicao.",
                f"Somente {module_path} e {test_path} podem ser criados ou alterados.",
            ],
        })
        write_json(QUEUE / f"{job_id}.json", {
            "id": job_id,
            "candidate": candidate_path.relative_to(ROOT).as_posix(),
            "allowed_paths": [module_path, test_path],
            "tests": [["{python}", "-m", "unittest", "discover", "-s", "tests"]],
            "timeout_seconds": 180,
        })
    print(f"{len(EXERCISES)} exercicios MCP materializados em {QUEUE}.")


if __name__ == "__main__":
    main()

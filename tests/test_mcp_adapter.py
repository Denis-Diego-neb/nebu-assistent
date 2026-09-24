import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from mcp.client import Client

from core.dispatcher import Dispatcher
from core.registry import Registry, Tool
from integrations.mcp.audit import MCPAuditLog, read_recent_audit_events
from integrations.mcp.server import create_mcp_server


def make_dispatcher(handler) -> Dispatcher:
    registry = Registry()

    def validate(arguments):
        if set(arguments) != {"argumento"} or not isinstance(arguments["argumento"], str):
            raise ValueError("argumento invalido")
        return {"argumento": arguments["argumento"].strip()}

    registry.register(Tool(
        "example",
        "Tool de teste",
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["argumento"],
            "properties": {"argumento": {"type": "string"}},
        },
        handler,
        validate,
    ))
    return Dispatcher(registry)


class MCPAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_roundtrip_oficial_lista_e_executa_tool(self) -> None:
        handler = Mock(return_value={"ok": True, "message": "executada", "value": 42})
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "mcp.jsonl"
            server = create_mcp_server(make_dispatcher(handler), audit=MCPAuditLog(path))
            async with Client(server) as client:
                catalog = await client.list_tools()
                self.assertEqual([tool.name for tool in catalog.tools], ["example"])
                self.assertFalse(catalog.tools[0].input_schema.get("additionalProperties"))
                result = await client.call_tool("example", {"argumento": " texto "})
            self.assertFalse(result.is_error)
            self.assertEqual(result.structured_content["value"], 42)
            handler.assert_called_once_with({"argumento": "texto"})
            events = read_recent_audit_events(path=path)
            self.assertEqual(events[0]["tool"], "example")
            self.assertTrue(events[0]["ok"])
            self.assertNotIn("texto", str(events[0]))

    async def test_erro_de_validacao_vira_resultado_mcp_e_auditoria(self) -> None:
        handler = Mock()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "mcp.jsonl"
            server = create_mcp_server(make_dispatcher(handler), audit=MCPAuditLog(path))
            async with Client(server) as client:
                result = await client.call_tool("example", {"errado": True})
            self.assertTrue(result.is_error)
            self.assertFalse(result.structured_content["ok"])
            handler.assert_not_called()
            self.assertFalse(read_recent_audit_events(path=path)[0]["ok"])


if __name__ == "__main__":
    unittest.main()

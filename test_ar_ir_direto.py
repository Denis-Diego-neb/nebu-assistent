import base64
import json
from pathlib import Path
import struct
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from ar_ir_direto import (
    ConfiguracaoArIr,
    ControleArDireto,
    codigo_base64_voltas,
    pulsos_voltas,
    quadro_voltas,
    EmissorIrConfirmado,
    ErroAr,
)


class DispositivoFalso:
    ultimo_codigo = ""
    codigo_aprendido = "AQACAAMA"

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def set_socketTimeout(self, _valor: int) -> None:
        pass

    def set_socketPersistent(self, _valor: bool) -> None:
        pass

    def send_button(self, codigo: str) -> None:
        type(self).ultimo_codigo = codigo

    def receive_button(self, _timeout: int) -> str:
        return type(self).codigo_aprendido

    def close(self) -> None:
        pass


class ArIrDiretoTests(unittest.TestCase):
    def setUp(self) -> None:
        DispositivoFalso.ultimo_codigo = ""
        self.config = ConfiguracaoArIr("id", "192.0.2.10", "1234567890abcdef")

    def test_quadros_conhecidos_e_checksum(self) -> None:
        ligado = quadro_voltas(power=True, temperature=17, mode="cool", fan="high")
        desligado = quadro_voltas(power=False, temperature=17, mode="cool", fan="high")
        self.assertEqual(ligado.hex(), "332880113b3b3b110051")
        self.assertEqual(desligado.hex(), "332800113b3b3b1100d1")
        self.assertEqual(ligado[-1], (~sum(ligado[:-1])) & 0xFF)

    def test_codigo_base64_contem_os_pulsos(self) -> None:
        quadro = quadro_voltas(power=True, temperature=22, mode="heat", fan="medium")
        pulsos = pulsos_voltas(quadro)
        bruto = base64.b64decode(codigo_base64_voltas(quadro))
        self.assertEqual(list(struct.unpack("<" + str(len(pulsos)) + "H", bruto)), pulsos)
        self.assertEqual(len(pulsos), 162)

    def test_controle_envia_e_persiste_sem_segredo(self) -> None:
        with TemporaryDirectory() as pasta:
            estado = Path(pasta) / "estado.json"
            controle = ControleArDireto(self.config, estado, DispositivoFalso)
            resposta = controle.executar("temperature", 23)
            self.assertTrue(resposta["ok"])
            self.assertTrue(DispositivoFalso.ultimo_codigo)
            salvo = json.loads(estado.read_text(encoding="utf-8"))
            self.assertEqual(salvo["temperature"], 23)
            self.assertTrue(salvo["power"])
            self.assertNotIn(self.config.local_key, estado.read_text(encoding="utf-8"))
            self.assertEqual(controle.estado()["source"], "Smart IR direto via Wi-Fi")

    def test_aprende_e_reproduz_botoes_de_energia(self) -> None:
        with TemporaryDirectory() as pasta:
            estado = Path(pasta) / "estado.json"
            codigos = Path(pasta) / "codigos.json"
            controle = ControleArDireto(
                self.config, estado, DispositivoFalso, codes_file=codigos
            )
            resultado = controle.aprender("power_on")
            self.assertEqual(resultado["button"], "power_on")
            controle.executar("power", True)
            self.assertEqual(DispositivoFalso.ultimo_codigo, DispositivoFalso.codigo_aprendido)
            self.assertNotIn(self.config.local_key, codigos.read_text(encoding="utf-8"))

    def test_emissor_aguarda_ack_mesmo_quando_helper_pede_nowait(self):
        device = EmissorIrConfirmado("id", "192.0.2.1", "1234567890abcdef", control_type=1, version=3.5)
        def acknowledged(*args, **kwargs):
            self.assertTrue(kwargs["getresponse"])
            device.cmd_retcode = 0
            return None
        with patch.object(device, "_send_receive", side_effect=acknowledged) as send:
            device.send_button("AQACAAMA")
            send.assert_called_once()
        device.close()

    def test_controle_aprendido_nao_mistura_protocolo_gerado(self):
        with TemporaryDirectory() as pasta:
            controle = ControleArDireto(self.config, Path(pasta)/"estado.json", DispositivoFalso, codes_file=Path(pasta)/"codigos.json")
            controle.aprender("power_on")
            for acao, valor in (("temperature", 23), ("mode", "cool"), ("fan", "low"), ("power", False)):
                with self.subTest(acao=acao), self.assertRaises(ErroAr):
                    controle.executar(acao, valor)
            self.assertEqual(controle.estado()["supported_actions"], ["power"])

    def test_emissor_rejeita_erros_e_falta_de_ack(self):
        for response in ({"Error": "offline", "Err": "905"}, None):
            device = EmissorIrConfirmado("id", "192.0.2.1", "1234567890abcdef", control_type=1)
            with patch.object(device, "_send_receive", return_value=response), self.assertRaises(ErroAr):
                device.send_button("AQACAAMA")
            device.close()

    def test_layout_2_envia_campos_juntos(self):
        device = EmissorIrConfirmado("id", "192.0.2.1", "1234567890abcdef", control_type=2)
        with patch.object(device, "generate_payload", return_value=b"payload") as payload, patch.object(device, "_send_receive", return_value={}):
            device.send_button("AQACAAMA")
            self.assertEqual(payload.call_args.args[1], {"1": "study_key", "13": 0, "7": "AQACAAMA"})
        device.close()

    def test_envio_falho_nao_muda_estado(self):
        with TemporaryDirectory() as pasta:
            controle = ControleArDireto(self.config, Path(pasta)/"estado.json", DispositivoFalso)
            with patch.object(controle, "_enviar", side_effect=ErroAr("Sem ACK")), self.assertRaises(ErroAr):
                controle.executar("power", True)
            self.assertFalse(controle.estado()["power"])
            self.assertEqual(controle.estado()["error"], "Sem ACK")


if __name__ == "__main__":
    unittest.main()

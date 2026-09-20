"""Configurações independentes e presets locais, sem comandos de hardware."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re


# ---------------------------------------------------------------------------
# MODOS NATIVOS DO TECLADO
# ---------------------------------------------------------------------------

KEYBOARD_EFFECTS = (
    "static",
    "onda",
    "onda_curta",
    "ciclo",
    "respirar",
    "reativo",
    "ripple",
    "linha",
    "estrelas",
    "florescer",
    "arco_iris_vertical",
    "furacao",
    "acumular",
    "visor",
    "arco_iris_circular",
)


# ---------------------------------------------------------------------------
# MODOS DISPONÍVEIS POR DISPOSITIVO
# ---------------------------------------------------------------------------

MODES = {
    "lamp": (
        "manual",
        "ambilight",
        "music",
        "torch",
        "rpm",
        "boost",
    ),

    "keyboard": (
        "manual",
        "ambilight",
        "boost",

        # Modos executados diretamente pelo firmware do Kumara.
        *KEYBOARD_EFFECTS,
    ),

    "controller": (
        "manual",
        "ambilight",
        "rpm",
        "boost",
    ),

    "mobile": (
        "manual",
        "rpm",
        "turbo",
    ),
}


# ---------------------------------------------------------------------------
# NOMES EXIBIDOS NA INTERFACE
# ---------------------------------------------------------------------------

LABELS = {
    # Modos gerais
    "manual": "Desativado / manual",
    "ambilight": "Ambilight",
    "music": "Música",
    "torch": "Tocha",
    "rpm": "RPM / FuelTech",
    "boost": "Boost",
    "turbo": "Pressão do turbo",

    # Kumara / EVision
    "static": "Estático",
    "onda": "WRGB Wave",
    "onda_curta": "WRGB Wave rápida",
    "ciclo": "Color Cycle",
    "respirar": "Breathing",
    "reativo": "Reactive",
    "ripple": "Ripple",
    "linha": "Linha",
    "estrelas": "Estrelas",
    "florescer": "Florescer",
    "arco_iris_vertical": "Arco-íris vertical",
    "furacao": "Furacão",
    "acumular": "Acumular",
    "visor": "Visor",
    "arco_iris_circular": "Arco-íris circular",
}


# ---------------------------------------------------------------------------
# CONFIGURAÇÕES PADRÃO
# ---------------------------------------------------------------------------

def defaults():
    """Cria a configuração inicial de todos os dispositivos."""

    return {
        device: {
            "mode": "manual",
        }
        for device in MODES
    }


def is_keyboard_effect(mode: str) -> bool:
    """Retorna True quando o modo é executado pelo firmware do teclado."""

    return mode in KEYBOARD_EFFECTS


# ---------------------------------------------------------------------------
# VALIDAÇÃO
# ---------------------------------------------------------------------------

def _validar_cor(cor: object) -> str:
    if not isinstance(cor, str):
        raise ValueError("Cor inválida no preset.")

    cor = cor.strip()

    if not re.fullmatch(
        r"#[0-9a-fA-F]{6}|azul|amarelo|vermelho|verde|roxo",
        cor,
    ):
        raise ValueError("Cor inválida no preset.")

    return cor


def validate(value):
    """
    Valida e normaliza uma configuração de dispositivos.

    Também converte automaticamente presets antigos que usavam:

        {
            "keyboard": {
                "mode": "manual",
                "effect": "onda"
            }
        }

    para o formato novo:

        {
            "keyboard": {
                "mode": "onda"
            }
        }
    """

    if not isinstance(value, dict):
        raise ValueError(
            "Informe a configuração dos quatro dispositivos."
        )

    if set(value) != set(MODES):
        raise ValueError(
            "Informe a configuração dos quatro dispositivos."
        )

    result = deepcopy(value)

    for device, config in result.items():

        if not isinstance(config, dict):
            raise ValueError(
                f"Configuração inválida para {device}."
            )

        # ---------------------------------------------------------------
        # Compatibilidade com presets antigos do teclado.
        # ---------------------------------------------------------------

        if device == "keyboard" and "effect" in config:
            efeito_antigo = config.pop("effect")

            if efeito_antigo not in KEYBOARD_EFFECTS:
                raise ValueError(
                    "Efeito nativo do teclado inválido."
                )

            modo_atual = config.get("mode", "manual")

            # Antigamente o efeito era separado do modo.
            if modo_atual == "manual":
                config["mode"] = efeito_antigo

            # Também aceitamos o preset se os dois já indicarem
            # exatamente o mesmo efeito.
            elif modo_atual == efeito_antigo:
                pass

            else:
                raise ValueError(
                    "O preset mistura um modo do teclado "
                    "com um efeito nativo incompatível."
                )

        # ---------------------------------------------------------------
        # Modo
        # ---------------------------------------------------------------

        mode = config.get("mode")

        if mode not in MODES[device]:
            raise ValueError(
                f"Modo incompatível com {device}."
            )

        # ---------------------------------------------------------------
        # Campos permitidos
        # ---------------------------------------------------------------

        if device == "lamp":
            allowed = {
                "mode",
                "power",
                "color",
                "temperature",
                "brightness",
                "afterfire",
            }

        elif device == "keyboard":
            allowed = {
                "mode",
                "color",
                "afterfire",
            }

        elif device == "controller":
            allowed = {
                "mode",
                "color",
                "afterfire",
            }

        elif device == "mobile":
            allowed = {
                "mode",
            }

        else:
            raise ValueError(
                f"Dispositivo desconhecido: {device}."
            )

        desconhecidos = set(config) - allowed

        if desconhecidos:
            raise ValueError(
                "Ajuste desconhecido no preset: "
                + ", ".join(sorted(desconhecidos))
            )

        # ---------------------------------------------------------------
        # Flash de escapamento / afterfire
        # ---------------------------------------------------------------

        if "afterfire" in config:
            if type(config["afterfire"]) is not bool:
                raise ValueError(
                    "Estado do flash inválido."
                )

        # ---------------------------------------------------------------
        # Energia
        # ---------------------------------------------------------------

        if "power" in config:
            if type(config["power"]) is not bool:
                raise ValueError(
                    "Estado de energia inválido."
                )

        # ---------------------------------------------------------------
        # Brilho da lâmpada
        # ---------------------------------------------------------------

        if "brightness" in config:
            brightness = config["brightness"]

            if (
                type(brightness) is not int
                or not 1 <= brightness <= 100
            ):
                raise ValueError(
                    "Brilho deve ficar entre 1 e 100%."
                )

        # ---------------------------------------------------------------
        # Cor
        # ---------------------------------------------------------------

        if "color" in config:
            cor = _validar_cor(config["color"])

            if device == "keyboard":
                if not cor.startswith("#"):
                    raise ValueError(
                        "Use uma cor em #RRGGBB para o teclado."
                    )

                if cor.lower() == "#000000":
                    raise ValueError(
                        "Use uma cor visível em #RRGGBB para o teclado."
                    )

            if device == "controller":
                if not cor.startswith("#"):
                    raise ValueError(
                        "Use uma cor em #RRGGBB para o controle."
                    )

            config["color"] = cor

        # ---------------------------------------------------------------
        # Temperatura da lâmpada
        # ---------------------------------------------------------------

        if "temperature" in config:
            if config["temperature"] not in {
                "quente",
                "neutra",
                "fria",
            }:
                raise ValueError(
                    "Temperatura de cor inválida."
                )

    return result


# ---------------------------------------------------------------------------
# PRESETS
# ---------------------------------------------------------------------------

class Presets:
    def __init__(self, path: Path):
        self.path = path
        self.items: dict[str, dict] = {}

        try:
            data = json.loads(
                path.read_text(
                    encoding="utf-8",
                )
            )

            if not isinstance(data, dict):
                raise ValueError(
                    "Arquivo de presets inválido."
                )

            presets = data.get(
                "presets",
                {},
            )

            if not isinstance(presets, dict):
                raise ValueError(
                    "Lista de presets inválida."
                )

            for name, config in presets.items():
                nome = self.name(name)

                self.items[nome] = validate(
                    config
                )

        except (
            OSError,
            json.JSONDecodeError,
            ValueError,
            TypeError,
            AttributeError,
        ):
            self.items = {}

    @staticmethod
    def name(value):
        if not isinstance(value, str):
            raise ValueError(
                "Informe um nome para o preset."
            )

        name = " ".join(
            value.strip().split()
        )

        if not 1 <= len(name) <= 60:
            raise ValueError(
                "Use um nome de 1 a 60 caracteres."
            )

        if any(
            ord(c) < 32
            for c in name
        ):
            raise ValueError(
                "Use um nome de 1 a 60 caracteres."
            )

        return name

    def resolve(self, name):
        name = self.name(name)

        for existing in self.items:
            if existing.casefold() == name.casefold():
                return existing

        raise ValueError(
            f"Preset ‘{name}’ não encontrado."
        )

    def get(self, name):
        resolved = self.resolve(name)

        return deepcopy(
            self.items[resolved]
        )

    def save(self, name, config):
        name = self.name(name)

        try:
            name = self.resolve(name)

        except ValueError:
            pass

        updated = deepcopy(
            self.items
        )

        updated[name] = validate(
            config
        )

        self._write(
            updated
        )

        return name

    def delete(self, name):
        resolved = self.resolve(name)

        updated = deepcopy(
            self.items
        )

        del updated[resolved]

        self._write(
            updated
        )

    def _write(self, items):
        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        temporary = self.path.with_suffix(
            ".tmp"
        )

        data = {
            "version": 2,
            "presets": items,
        }

        temporary.write_text(
            json.dumps(
                data,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        temporary.replace(
            self.path
        )

        self.items = items


# ---------------------------------------------------------------------------
# COMANDOS DE VOZ PARA PRESETS
# ---------------------------------------------------------------------------

def voice_preset(command):
    match = re.fullmatch(
        r"(?:nebula[, ]+)?"
        r"(?:ative?|aplique|use|carregue|troque para|d[eê] play (?:no|em))"
        r"\s+(?:o\s+)?preset\s+(.+)",
        command,
        re.I,
    )

    if match:
        return (
            "preset.apply",
            match[1].strip(" .!?"),
        )

    match = re.fullmatch(
        r"(?:nebula[, ]+)?"
        r"salve?\s+(?:o\s+)?preset\s+(.+)",
        command,
        re.I,
    )

    if match:
        return (
            "preset.save",
            match[1].strip(" .!?"),
        )

    return None
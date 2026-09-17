"""Configurações independentes e presets locais, sem comandos de hardware."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re

MODES = {
    "lamp": ("manual", "ambilight", "music", "torch", "rpm", "boost"),
    "keyboard": ("manual", "ambilight", "boost"),
    "controller": ("manual", "ambilight", "rpm", "boost"),
    "mobile": ("manual", "rpm", "turbo"),
}
KEYBOARD_EFFECTS = (
    "static", "onda", "onda_curta", "ciclo", "respirar", "reativo",
    "ripple", "linha", "estrelas", "florescer", "arco_iris_vertical",
    "furacao", "acumular", "visor", "arco_iris_circular",
)
LABELS = {"manual": "Desativado / manual", "ambilight": "Ambilight",
          "music": "Música", "torch": "Tocha", "rpm": "RPM / FuelTech",
          "boost": "Boost", "turbo": "Pressão do turbo"}


def defaults():
    return {device: {"mode": "manual"} for device in MODES}


def validate(value):
    if not isinstance(value, dict) or set(value) != set(MODES):
        raise ValueError("Informe a configuração dos quatro dispositivos.")
    result = deepcopy(value)
    for device, config in result.items():
        if not isinstance(config, dict) or config.get("mode") not in MODES[device]:
            raise ValueError(f"Modo incompatível com {device}.")
        allowed = {"mode"} | ({"power", "color", "temperature", "brightness"} if device == "lamp" else {"color", "effect"} if device == "keyboard" else {"color"} if device == "controller" else set()) | ({"afterfire"} if device in {"lamp", "keyboard", "controller"} else set())
        if set(config) - allowed:
            raise ValueError("Ajuste desconhecido no preset.")
        if "afterfire" in config and type(config["afterfire"]) is not bool:
            raise ValueError("Estado do flash inválido.")
        if "brightness" in config and (type(config["brightness"]) is not int or not 1 <= config["brightness"] <= 100):
            raise ValueError("Brilho deve ficar entre 1 e 100%.")
        if "power" in config and type(config["power"]) is not bool:
            raise ValueError("Estado de energia inválido.")
        if "color" in config and (not isinstance(config["color"], str) or not re.fullmatch(r"#[0-9a-fA-F]{6}|azul|amarelo|vermelho|verde|roxo", config["color"])):
            raise ValueError("Cor inválida no preset.")
        if device == "keyboard" and "color" in config and (not config["color"].startswith("#") or config["color"] == "#000000"):
            raise ValueError("Use uma cor visível em #RRGGBB para o teclado.")
        if device == "controller" and "color" in config and not config["color"].startswith("#"):
            raise ValueError("Use uma cor em #RRGGBB para o controle.")
        if device == "keyboard" and config.get("effect", "static") not in KEYBOARD_EFFECTS:
            raise ValueError("Efeito nativo do teclado inválido.")
        if "temperature" in config and config["temperature"] not in {"quente", "neutra", "fria"}:
            raise ValueError("Temperatura de cor inválida.")
    return result


class Presets:
    def __init__(self, path: Path):
        self.path = path
        self.items = {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for name, config in data.get("presets", {}).items():
                self.items[self.name(name)] = validate(config)
        except (OSError, ValueError, TypeError, AttributeError):
            self.items = {}

    @staticmethod
    def name(value):
        if not isinstance(value, str):
            raise ValueError("Informe um nome para o preset.")
        name = " ".join(value.strip().split())
        if not 1 <= len(name) <= 60 or any(ord(c) < 32 for c in name):
            raise ValueError("Use um nome de 1 a 60 caracteres.")
        return name

    def resolve(self, name):
        name = self.name(name)
        for existing in self.items:
            if existing.casefold() == name.casefold():
                return existing
        raise ValueError(f"Preset ‘{name}’ não encontrado.")

    def get(self, name):
        return deepcopy(self.items[self.resolve(name)])

    def save(self, name, config):
        name = self.name(name)
        try:
            name = self.resolve(name)
        except ValueError:
            pass
        updated = deepcopy(self.items)
        updated[name] = validate(config)
        self._write(updated)
        return name

    def delete(self, name):
        updated = deepcopy(self.items)
        del updated[self.resolve(name)]
        self._write(updated)

    def _write(self, items):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"version": 1, "presets": items}, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)
        self.items = items


def voice_preset(command):
    match = re.fullmatch(r"(?:nebula[, ]+)?(?:ative?|aplique|use|carregue|troque para|d[eê] play (?:no|em))\s+(?:o\s+)?preset\s+(.+)", command, re.I)
    if match:
        return "preset.apply", match[1].strip(" .!?")
    match = re.fullmatch(r"(?:nebula[, ]+)?salve?\s+(?:o\s+)?preset\s+(.+)", command, re.I)
    return ("preset.save", match[1].strip(" .!?")) if match else None

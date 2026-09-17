"""Gera os ícones estáticos da esfera usados pelo Windows e pela bandeja."""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image


def gerar_esfera(tamanho: int) -> Image.Image:
    escala = 4
    lado = tamanho * escala
    centro = lado / 2
    raio = lado * 0.34
    imagem = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
    pixels = imagem.load()
    for y in range(lado):
        for x in range(lado):
            dx, dy = x + 0.5 - centro, y + 0.5 - centro
            distancia = math.hypot(dx, dy)
            # Halo azul suave fora da esfera.
            if distancia > raio:
                halo = max(0.0, 1.0 - (distancia - raio) / (raio * 0.42))
                if halo:
                    pixels[x, y] = (39, 140, 245, int(80 * halo * halo))
                continue

            # Degradê radial deslocado para criar o brilho no canto inferior direito.
            bx, by = centro + raio * 0.24, centro + raio * 0.22
            brilho = min(1.0, math.hypot(x - bx, y - by) / (raio * 1.18))
            borda = min(1.0, distancia / raio)
            mistura = max(0.0, min(1.0, 1.0 - brilho))
            vermelho = int(18 + 131 * mistura)
            verde = int(110 + 100 * mistura)
            azul = int(209 + 46 * mistura)
            alfa = int(255 * min(1.0, (1.0 - borda) * 18))
            pixels[x, y] = (vermelho, verde, azul, alfa)
    return imagem.resize((tamanho, tamanho), Image.Resampling.LANCZOS)


if __name__ == "__main__":
    pasta = Path(__file__).resolve().parent / "assets"
    pasta.mkdir(exist_ok=True)
    principal = gerar_esfera(256)
    principal.save(pasta / "nebula.png")
    principal.save(
        pasta / "nebula.ico",
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"Ícones gerados em {pasta}")

"""Captura o áudio de saída do Windows e identifica músicas pela AudD."""

from __future__ import annotations

import os
import tempfile
import wave
from pathlib import Path


def capturar_audio_sistema(segundos: float = 10) -> Path:
    try:
        import pyaudiowpatch as pyaudio
    except ImportError as exc:
        raise RuntimeError("PyAudioWPatch não está instalado.") from exc

    audio = pyaudio.PyAudio()
    descritor, nome_temporario = tempfile.mkstemp(prefix="nebula-musica-", suffix=".wav")
    os.close(descritor)
    caminho = Path(nome_temporario)
    stream = None
    try:
        dispositivo = audio.get_default_wasapi_loopback()
        taxa = int(dispositivo["defaultSampleRate"])
        canais = max(1, min(int(dispositivo["maxInputChannels"]), 2))
        tamanho_bloco = 1024
        stream = audio.open(
            format=pyaudio.paInt16,
            channels=canais,
            rate=taxa,
            input=True,
            input_device_index=dispositivo["index"],
            frames_per_buffer=tamanho_bloco,
        )
        quadros = [
            stream.read(tamanho_bloco, exception_on_overflow=False)
            for _ in range(int(taxa / tamanho_bloco * segundos))
        ]
        with wave.open(str(caminho), "wb") as arquivo:
            arquivo.setnchannels(canais)
            arquivo.setsampwidth(audio.get_sample_size(pyaudio.paInt16))
            arquivo.setframerate(taxa)
            arquivo.writeframes(b"".join(quadros))
        return caminho
    except Exception:
        caminho.unlink(missing_ok=True)
        raise
    finally:
        if stream is not None:
            stream.stop_stream()
            stream.close()
        audio.terminate()


def identificar_musica(segundos: float = 10) -> dict[str, str] | None:
    try:
        import requests
    except ImportError as exc:
        raise RuntimeError("A biblioteca requests não está instalada.") from exc

    caminho = capturar_audio_sistema(segundos)
    token = os.environ.get("AUDD_API_TOKEN", "test").strip() or "test"
    try:
        with caminho.open("rb") as audio:
            resposta = requests.post(
                "https://api.audd.io/",
                data={"api_token": token},
                files={"file": (caminho.name, audio, "audio/wav")},
                timeout=25,
            )
        resposta.raise_for_status()
        dados = resposta.json()
        if dados.get("status") != "success":
            erro = dados.get("error") or {}
            raise RuntimeError(str(erro.get("error_message") or "resposta inválida da AudD"))
        resultado = dados.get("result")
        if not resultado:
            return None
        return {
            "titulo": str(resultado.get("title") or "").strip(),
            "artista": str(resultado.get("artist") or "").strip(),
            "album": str(resultado.get("album") or "").strip(),
        }
    finally:
        caminho.unlink(missing_ok=True)

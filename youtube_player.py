"""Resolve uma pesquisa do YouTube para o primeiro vídeo reproduzível."""

from __future__ import annotations


def primeiro_video(pesquisa: str) -> str | None:
    try:
        import yt_dlp
    except ImportError:
        return None

    opcoes = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": True,
        "playlistend": 1,
        "socket_timeout": 12,
    }
    with yt_dlp.YoutubeDL(opcoes) as ydl:
        dados = ydl.extract_info(f"ytsearch1:{pesquisa}", download=False)
    entradas = dados.get("entries") or []
    if not entradas:
        return None
    video_id = entradas[0].get("id")
    return f"https://www.youtube.com/watch?v={video_id}&autoplay=1" if video_id else None

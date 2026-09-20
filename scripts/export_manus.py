"""Exporta os fontes relevantes ao frontend, sem builds e dados locais."""

from pathlib import Path
import subprocess
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "dist" / "manus" / "nebula-manus.zip"
SOURCE_DIRS = {"core", "modules", "integrations", "services", "tests", "notebook_power_server", "integracoes", "android", "scripts"}
SOURCE_EXTENSIONS = {".py", ".md", ".kt", ".java", ".xml", ".kts", ".gradle", ".pro"}
ROOT_FILES = {"README.md", "MODOS_E_PRESETS.md", "MANUS.md", "ARQUITETURA.md", "requirements.txt", "requirements-dev.txt"}


def incluir(path: Path) -> bool:
    if path.name == "export_manus.py":
        return False  # A exportação depende do Git e roda no projeto original.
    if len(path.parts) == 1:
        return path.suffix == ".py" or path.name in ROOT_FILES
    if path.parts[0] == "assets":
        return path.suffix in {".png", ".ico"}
    if path.parts[0] == "android" and path.suffix == ".png":
        return "res" in path.parts
    return path.parts[0] in SOURCE_DIRS and path.suffix in SOURCE_EXTENSIONS


def main() -> None:
    candidates = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
    ).decode("utf-8").split("\0")
    selected = sorted({
        name for name in candidates
        if name and incluir(Path(name)) and (ROOT / name).is_file()
        and not (ROOT / name).is_symlink()
    })
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(OUTPUT, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for name in selected:
            archive.write(ROOT / name, arcname="nebula/" + name)
        archive.writestr("nebula/ARQUIVOS.txt", "\n".join(selected) + "\n")
    with ZipFile(OUTPUT) as archive:
        bad_file = archive.testzip()
        if bad_file:
            raise RuntimeError(f"Arquivo corrompido: {bad_file}")
    print(f"{OUTPUT}\n{len(selected)} fontes; {OUTPUT.stat().st_size / 1024:.1f} KiB")


if __name__ == "__main__":
    main()

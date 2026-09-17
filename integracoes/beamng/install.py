"""Instala o protocolo de turbo como mod, com o BeamNG fechado."""
from pathlib import Path
import argparse
import datetime
import json
import shutil
import zipfile


def afterfire_patch(source):
    """Instrumenta somente as três emissões de som de afterfire desta versão."""
    lines = source.splitlines(keepends=True)
    hits = 0
    result = []
    for line in lines:
        result.append(line)
        if line.lstrip().startswith('obj:playSFXOnceCT(afterFire.'):
            hits += 1
            result.append('            electrics.values.nebulaAfterfire = ((electrics.values.nebulaAfterfire or 0) + 1) % 4294967296\n')
    if hits != 3:
        raise ValueError('Versão do escape não reconhecida; nenhum arquivo do jogo foi alterado.')
    return ''.join(result)


def install(user_folder, game_folder=None):
    root = Path(user_folder).resolve()
    settings = root / 'settings' / 'settings.json'
    if not settings.is_file():
        raise ValueError('Selecione a pasta de usuario existente do BeamNG.')
    data = json.loads(settings.read_text(encoding='utf-8-sig'))
    timestamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    mods = root / 'mods'
    mods.mkdir(exist_ok=True)
    destination = mods / 'nebula_turbo.zip'
    if destination.exists():
        backup = root / 'backups' / 'nebula_turbo'
        backup.mkdir(parents=True, exist_ok=True)
        shutil.copy2(destination, backup / (timestamp+'.zip'))
    source = Path(__file__).parent / 'lua' / 'vehicle' / 'protocols' / 'nebulaTurbo.lua'
    patched = None
    thermal_path = 'lua/vehicle/powertrain/combustionEngineThermals.lua'
    if game_folder is not None:
        patched = afterfire_patch((Path(game_folder) / thermal_path).read_text(encoding='utf-8'))
    staged = destination.with_suffix('.tmp')
    with zipfile.ZipFile(staged, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(source, 'lua/vehicle/protocols/nebulaTurbo.lua')
        if patched is not None:
            archive.writestr(thermal_path, patched)
    staged.replace(destination)
    # O padrao confirmado no BeamNG 0.39.4 ja e true; so altera quando
    # o usuario tiver desativado expressamente protocolos adicionais.
    if data.get('protocols_others_enabled') is False:
        shutil.copy2(settings, settings.with_name('settings.nebula-backup-'+timestamp+'.json'))
        data['protocols_others_enabled'] = True
        settings.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--user-folder', required=True)
    parser.add_argument('--game-folder', help='Gera localmente o mod de flashes, sem editar os arquivos originais.')
    args = parser.parse_args()
    print(install(args.user_folder, args.game_folder))

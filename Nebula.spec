# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [
    ('assets/nebula.png', 'assets'),
    ('contexto_nebula.md', '.'),
    # Front espacial servido em /espaco pelo painel local.
    ('nebula_front', 'nebula_front'),
]
binaries = []
hiddenimports = ['win32com.client', 'pythoncom', 'pywintypes', 'front_assets', 'front_window']
# O backend da colaboracao NAO entra no pacote de proposito: ele e mantido
# pelo outro agente e e lido do disco, ao lado do executavel. Empacotado, ele
# ficava congelado na data do build e o painel respondia 404 em rotas que ja
# existiam na fonte.
hiddenimports += [
    'winrt.windows.media.control', 'winrt._winrt_windows_media_control',
    'winrt.windows.storage.streams', 'winrt._winrt_windows_storage_streams',
]
tmp_ret = collect_all('pyaudiowpatch')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pystray')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('edge_tts')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('requests')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('tinytuya')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pycaw')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('yt_dlp')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('hid')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('openrgb')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

a = Analysis(['gui.py'], pathex=[], binaries=binaries, datas=datas,
    hiddenimports=hiddenimports, hookspath=[], hooksconfig={}, runtime_hooks=[],
    # Fora do pacote de proposito: o backend da colaboracao e mantido pelo outro
    # agente, e a cola da Dupla importa ele no topo. Sem excluir aqui, o
    # PyInstaller segue esse import e congela o backend de novo - tirar do
    # hiddenimports nao bastava, a analise e transitiva.
    excludes=['services.collaboration', 'colaboracao_ferramentas', 'memoria_dupla'],
    noarchive=False, optimize=0)
pyz = PYZ(a.pure)

exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='Nebula',
    icon='assets/nebula.ico', debug=False, bootloader_ignore_signals=False,
    strip=False, upx=True, upx_exclude=[], runtime_tmpdir=None, console=False,
    disable_windowed_traceback=False, argv_emulation=False, target_arch=None,
    codesign_identity=None, entitlements_file=None)

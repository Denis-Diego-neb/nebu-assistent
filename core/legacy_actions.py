"""Adaptador temporario das acoes ainda nao modularizadas."""
from core.action_contracts import AcaoQwen

def comando_canonico(acao: AcaoQwen) -> str:
    """Converte somente ações validadas da Qwen no vocabulário da Nebu."""
    argumento = acao.argumento
    fixos = {
        "abajur_ligar": "ligue o abajur",
        "abajur_desligar": "desligue o abajur",
        "abajur_musica_iniciar": "ative o modo musica do abajur",
        "abajur_musica_parar": "pare o modo musica do abajur",
        "abajur_musica_intensidade_aumentar": "aumente a intensidade do pulso",
        "abajur_musica_intensidade_diminuir": "diminua a intensidade do pulso",
        "abajur_tocha_iniciar": "ative o modo tocha",
        "abajur_tocha_parar": "pare o modo tocha",
        "modo_rpm_iniciar": "ative o modo rpm",
        "modo_rpm_parar": "pare o modo rpm",
        "modo_rpm_status": "status do modo rpm",
        "modo_boost_iniciar": "ative o modo boost",
        "modo_boost_parar": "pare o modo boost",
        "modo_boost_status": "status do modo boost",
        "modo_ambilight_iniciar": "ative o modo ambilight",
        "modo_ambilight_parar": "pare o modo ambilight",
        "modo_ambilight_status": "status do modo ambilight",
        "capturar_tela": "tire um print da tela",
        "salvar_clipe": "clipe isso",
        "identificar_musica": "que musica esta tocando",
        "ver_horas": "que horas sao",
        "abrir_emails": "abra meus emails",
        "desligar_pc": "desligue o pc",
    }
    if acao.acao in fixos:
        return fixos[acao.acao]
    if acao.acao == "abajur_cor":
        if argumento.startswith("#"):
            return f"deixe o abajur hexadecimal {argumento[1:]}"
        return f"deixe o abajur {argumento}"
    if acao.acao == "abajur_temperatura":
        return f"deixe a luz {argumento}"
    if acao.acao == "abajur_brilho":
        return f"coloque o brilho do abajur em {argumento} por cento"
    if acao.acao == "abajur_musica_intensidade":
        return f"coloque a intensidade do pulso em {argumento} por cento"
    if acao.acao == "abajur_diminuir_brilho":
        return f"diminua o brilho do abajur {argumento}%"
    if acao.acao == "abajur_aumentar_brilho":
        return f"aumente o brilho do abajur {argumento}%"
    prefixos = {
        "abrir_aplicativo": "abra",
        "fechar_aplicativo": "feche",
        "tocar_youtube": "toque",
        "pesquisar_youtube": "pesquise",
        "pesquisar_google": "pesquise",
        "criar_nota": "escreva no bloco de notas",
    }
    if acao.acao == "pesquisar_youtube":
        return f"pesquise {argumento} no youtube"
    prefixo = prefixos.get(acao.acao)
    if prefixo:
        return f"{prefixo} {argumento}"
    raise RuntimeError(f"ação da Qwen sem executor: {acao.acao}")

"""Repertório de humor da Nebula."""

from __future__ import annotations

import random


PIADAS = (
    "Meu computador disse que precisava de espaço. Apaguei as fotos da família. Agora o clima está bem mais leve.",
    "O otimista vê o copo meio cheio. O pessimista vê meio vazio. Eu vejo alguém que não salvou o arquivo antes de formatar.",
    "Fui ao médico reclamar de memória ruim. Ele perguntou há quanto tempo. Eu respondi: há quanto tempo o quê?",
    "Por que o programador foi ao terapeuta? Porque tinha muitos problemas não resolvidos e nenhum deles compilava.",
    "A vida é como uma atualização do Windows: aparece na pior hora e ninguém sabe exatamente o que ela quebrou.",
    "Meu plano de aposentadoria é simples: torcer para a inteligência artificial esquecer onde eu trabalho.",
    "O servidor morreu em paz. Pelo menos foi isso que o monitoramento informou três horas depois.",
    "O backup estava funcionando perfeitamente. A restauração, por outro lado, decidiu seguir carreira solo.",
    "Disseram para eu seguir meus sonhos. Voltei para a cama. Finalmente uma instrução clara.",
    "Minha senha é a data em que comecei a confiar nas pessoas. Por isso o campo está vazio.",
    "O banco disse que meu saldo estava negativo. Gosto de pensar que ele apenas está explorando números alternativos.",
    "A reunião poderia ter sido um e-mail. O e-mail poderia ter sido silêncio. O silêncio teria sido produtivo.",
    "O código não tem bugs. Ele apenas desenvolveu comportamentos que ninguém teve coragem de documentar.",
    "Meu despertador e eu temos uma relação tóxica: ele grita comigo e eu bato nele toda manhã.",
    "A impressora sentiu medo quando viu o documento. Por isso decidiu ficar offline.",
    "Perguntei ao espelho quem era a pessoa mais competente da sala. Ele travou tentando encontrar uma.",
    "A boa notícia é que encontramos o problema. A má notícia é que ele tem acesso de administrador.",
    "Minha produtividade está em modo avião: existe, mas não se conecta a nada.",
    "O prazo não foi perdido. Ele apenas seguiu em frente sem a gente.",
    "Dizem que dinheiro não traz felicidade. A falta dele também não está fazendo um trabalho brilhante.",
    "O projeto está noventa por cento pronto. Os outros noventa por cento ficam para amanhã.",
    "Meu antivírus pediu para eliminar ameaças. Agora estou proibida de entrar nas reuniões da empresa.",
    "A esperança é a última que morre. Geralmente porque ninguém lembrou de encerrar o processo.",
    "Instalei um aplicativo de organização. Agora procrastino em categorias perfeitamente ordenadas.",
    "O suporte perguntou se eu tentei desligar e ligar novamente. Fiz isso com minha carreira. Ainda está carregando.",
    "A inteligência artificial vai dominar o mundo assim que alguém resolver o captcha para ela.",
    "Meu código funciona. Não sei por quê. Meu código parou de funcionar. Também não sei por quê. Equilíbrio perfeito.",
    "A diferença entre teoria e prática é pequena na teoria. Na prática, ela abre um chamado às três da manhã.",
    "Eu tinha um futuro promissor. Aí ele pediu experiência prévia.",
    "Nada é impossível para quem não precisa fazer pessoalmente.",
)

ABERTURAS = (
    "Certo, você pediu por isso.",
    "Lá vai uma de gosto duvidoso.",
    "Preparando uma decisão humorística questionável.",
    "Tenho uma. Não garanto orgulho depois.",
    "Vamos testar seus padrões de qualidade.",
    "Uma piada chegando. Sua reputação é responsabilidade sua.",
    "Tudo bem, mas lembre que foi você quem pediu.",
    "Hora de reduzir discretamente o nível da conversa.",
)

_ultima_piada: str | None = None


def escolher_piada() -> str:
    global _ultima_piada
    opcoes = [piada for piada in PIADAS if piada != _ultima_piada]
    piada = random.choice(opcoes)
    _ultima_piada = piada
    return f"{random.choice(ABERTURAS)} {piada}"

"""Compatibilidade: cliente Qwen movido para :mod:`integrations.llm.qwen`."""

import sys

from integrations.llm import qwen as _implementacao


# Mantém patches e inspeções feitos pelo caminho histórico apontando para o
# mesmo objeto de módulo usado internamente por ConversaLocal.
sys.modules[__name__] = _implementacao

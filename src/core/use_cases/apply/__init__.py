"""Preenchimento e envio de formulários de candidatura.

O antigo ``job_application_handler`` era uma classe de 837 linhas e 24 métodos
misturando quatro responsabilidades sem relação: primitivas de DOM, prompt de
LLM, cache de perguntas/respostas e o ciclo de vida do modal do LinkedIn.

Aqui cada uma tem seu módulo, e o orquestrador (``EasyApplyHandler``) compõe as
três em vez de herdar tudo:

- ``FormAnswerer``  — decide o que responder (cache → LLM). Sem DOM.
- ``FieldFiller``   — sabe escrever num elemento e ler seu rótulo. Sem LLM.
- ``ModalDriver``   — abre, espera e fecha o modal do Easy Apply.
- ``EasyApplyHandler`` — o loop de passos do formulário.
"""

from src.core.use_cases.apply.easy_apply import EasyApplyHandler
from src.core.use_cases.apply.field_filler import FieldFiller
from src.core.use_cases.apply.form_answerer import FormAnswerer
from src.core.use_cases.apply.modal_driver import ModalDriver

__all__ = ["EasyApplyHandler", "FieldFiller", "FormAnswerer", "ModalDriver"]

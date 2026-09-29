"""Textos ao lead. Todo valor numérico em dinheiro vem da resposta da API (dict `quote`).

Regra de ouro: nenhum preço é escrito à mão ou gerado por LLM. As funções daqui
recebem a resposta da /quote e só formatam.
"""

from __future__ import annotations

from datetime import date
from typing import Any

NOMES_CAMPOS = {
    "veiculo_ano": "o ano do carro",
    "idade": "sua idade",
    "cep": "o CEP onde o carro dorme",
    "plano_id": "o plano",
    "data_inicio": "a data de início",
}
COBERTURAS = {
    "colisao": "colisão",
    "roubo": "roubo",
    "furto": "furto",
    "terceiros": "danos a terceiros",
    "vidros": "vidros",
    "carro_reserva": "carro reserva",
    "assistencia_24h": "assistência 24h",
}


def brl(v: float | int) -> str:
    s = f"{float(v):,.2f}"
    return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")


def valores_permitidos(quotes: list[dict[str, Any]]) -> set[str]:
    """Todos os valores em R$ que podem aparecer numa resposta: só os que vieram da API."""
    vals: set[str] = set()
    for q in quotes:
        vals.add(brl(q["premio_mensal"]))
        vals.add(brl(q["franquia"]))
        if pr := q.get("primeiro_pagamento_pro_rata"):
            vals.add(brl(pr["valor_primeiro_pagamento"]))
    return vals


def saudacao() -> str:
    return "Oi! Aqui é o assistente da AutoSeguro. Vou te ajudar a cotar o seguro do seu carro. "


def perguntar(campo: str, planos: list[dict[str, Any]] | None = None) -> str:
    match campo:
        case "veiculo_ano":
            return "Qual é o modelo e o ano do seu carro?"
        case "idade":
            return "E qual é a sua idade?"
        case "cep":
            return "Qual o CEP de onde o carro fica à noite?"
        case "plano_id":
            linhas = [
                f"- *{p['nome']}*: {', '.join(COBERTURAS.get(c, c) for c in p['coberturas'])}"
                for p in planos or []
            ]
            if not linhas:
                return "Qual plano você quer cotar: Essencial, Completo ou Premium?"
            return "Temos 3 planos:\n" + "\n".join(linhas) + "\nQual deles você quer cotar?"
        case "data_inicio":
            return "A partir de quando você quer o seguro? Pode ser hoje ou uma data (ex.: 15/10)."
    return "Pode me passar " + NOMES_CAMPOS.get(campo, campo) + "?"


def confirmar(slots: dict[str, Any], cep_prefixo: str | None) -> str:
    di = slots.get("data_inicio")
    if isinstance(di, str):
        di = date.fromisoformat(di)
    di_txt = di.strftime("%d/%m/%Y") if isinstance(di, date) else str(di)
    return (
        "Só pra confirmar antes de cotar:\n"
        f"- Carro ano {slots['veiculo_ano']}\n"
        f"- Idade {slots['idade']} anos\n"
        f"- CEP da região {cep_prefixo or '??'}xxx\n"
        f"- Plano {str(slots['plano_id']).capitalize()}\n"
        f"- Início em {di_txt}\n"
        "Está certo? (sim / não)"
    )


def apresentar(quote: dict[str, Any]) -> str:
    cob = ", ".join(COBERTURAS.get(c, c) for c in quote["coberturas"])
    txt = (
        f"Cotação pronta! Plano *{quote['plano_nome']}*: {brl(quote['premio_mensal'])} por mês.\n"
        f"Coberturas: {cob}. Franquia de {brl(quote['franquia'])}."
    )
    car = quote.get("carencia") or {}
    if car.get("coberturas"):
        nomes = " e ".join(COBERTURAS.get(c, c) for c in car["coberturas"])
        txt += f"\nAtenção: {nomes} só passam a valer depois de {car['dias']} dias de carência."
    if pr := quote.get("primeiro_pagamento_pro_rata"):
        txt += (
            f"\nComo o início é no meio do mês, o primeiro pagamento é proporcional: "
            f"{brl(pr['valor_primeiro_pagamento'])} ({pr['dias_cobrados']} de {pr['dias_no_mes']} dias). "
            "Os meses seguintes são integrais."
        )
    return txt + "\nQuer fechar com esse plano ou prefere ver outro?"


def recusa(motivo: str | None) -> str:
    return (
        "Obrigado pelas informações! Pelas regras da seguradora, não consigo concluir essa cotação "
        f"automaticamente ({(motivo or 'perfil fora das regras de aceitação').rstrip('.')}). "
        "Vou passar seu atendimento para um especialista, que vai te chamar por aqui."
    )


HANDOFF = {
    "pedido_humano": (
        "Claro! Vou chamar um atendente pra continuar com você. Ele já recebe o resumo da conversa."
    ),
    "fora_de_escopo": "Esse assunto é com a nossa equipe. Já passei seu atendimento pra um especialista.",
    "midia": (
        "Não consigo abrir arquivos, áudios ou fotos por aqui. Vou passar pra um atendente que consegue."
    ),
    "sem_progresso": "Acho que não estou conseguindo te ajudar direito. Vou chamar um atendente.",
    "objecao_preco": "Entendo. Vou passar pra um consultor, que pode avaliar outras condições com você.",
    "cotacao_indisponivel": (
        "O sistema de cotação está instável agora e eu não vou te passar um valor sem ter certeza. "
        "Já deixei tudo pronto e um atendente vai te mandar a cotação por aqui."
    ),
    "pronto_para_fechar": (
        "Ótimo! Um consultor vai te chamar em seguida pra emitir a apólice e o boleto, "
        "com a cotação que acabamos de fazer."
    ),
}

POS_HANDOFF = "Seu atendimento já está com a nossa equipe. Em breve alguém te responde por aqui."
PEDIR_TEXTO = "Não consigo abrir arquivos, áudios ou fotos por aqui. Pode me mandar por escrito?"
CORRIGIR = "Sem problema. O que está errado? Pode me mandar o dado certo."
FALLBACK_SEGURO = "Desculpa, tive um problema aqui. Pode repetir, por favor?"

AGUARDANDO_COTACAO = (
    "O sistema de cotação está instável agora e eu não vou te passar um valor sem ter certeza. "
    "Já estou tentando de novo e te mando a cotação aqui assim que sair."
)
AINDA_TENTANDO = "Ainda estou tentando cotar com o sistema. Assim que sair, te mando por aqui."
CONSEGUI = "Consegui! "
VOLTEI = "Oi de novo! O atendente me devolveu a conversa. "
ENCERRADO = (
    "Seu atendimento foi encerrado pela nossa equipe. Se quiser uma nova cotação, é só mandar mensagem."
)

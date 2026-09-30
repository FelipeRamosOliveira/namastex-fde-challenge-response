import pytest

from autoseguro.guardrails.pii import PiiKind, PiiVault, contains_pii, cpf_valido, mask, mask_dict, scan


@pytest.mark.parametrize(
    ("texto", "tipo"),
    [
        ("meu cpf 389.083.863-43", PiiKind.CPF),
        ("cpf 38908386343", PiiKind.CPF),
        ("email ursula.souza@gmail.com", PiiKind.EMAIL),
        ("whats +55 21 97224-2584", PiiKind.TELEFONE),
        ("whats 21 97224-2584", PiiKind.TELEFONE),
        ("liga (21) 97224-2584", PiiKind.TELEFONE),
        ("celular 972242584", PiiKind.TELEFONE),
        ("fixo 11 3456-7890", PiiKind.TELEFONE),
        ("a placa é ABC1D23 se precisar", PiiKind.PLACA),
        ("placa abc-1234", PiiKind.PLACA),
        ("CEP 26703-384", PiiKind.CEP),
        ("cep 01310100", PiiKind.CEP),
        ("liga (21) 9 7224-2584", PiiKind.TELEFONE),
        ("zap 21 9 7224 2584", PiiKind.TELEFONE),
        ("fixo 3333-4444", PiiKind.TELEFONE),
        ("cpf 12345678900", PiiKind.CPF),
        ("meu nome é Ana", PiiKind.NOME),
    ],
)
def test_detecta_formatos(texto, tipo):
    kinds = [e.kind for e in scan(texto)]
    assert kinds == [tipo], kinds


@pytest.mark.parametrize(
    "texto",
    [
        "Toyota Corolla 2008",
        "tenho 35 anos",
        "quero começar em 2026-10-15",
        "o plano completo por R$ 209,90",
        "meu carro tem 12 anos",
        "vencimento 15/10/2026",
    ],
)
def test_nao_marca_texto_comum(texto):
    assert not contains_pii(texto), scan(texto)


def test_cpf_valido():
    assert cpf_valido("389.083.863-43")
    assert not cpf_valido("111.111.111-11")
    assert not cpf_valido("123.456.789-00")


def test_mask_tokens_estaveis_por_conversa():
    v = PiiVault()
    a = mask("cpf 389.083.863-43 e cep 26703-384", v).text
    b = mask("repetindo: 38908386343", v).text
    assert a == "cpf [CPF_1] e cep [CEP_1]"
    assert b == "repetindo: [CPF_1]"
    assert v.latest(PiiKind.CEP) == "26703-384"


def test_vault_so_guarda_original_do_cep():
    v = PiiVault()
    mask("cpf 389.083.863-43, email a.b@c.com, cep 26703-384, meu nome é Ana Souza", v)
    guardado = " ".join(v.tokens.values())
    assert "26703-384" in guardado
    for dado in ("389", "a.b@c.com", "Ana", "Souza"):
        assert dado not in guardado
    assert v.reveal("[CPF_1]") is None and v.reveal("[CEP_1]") == "26703-384"


def test_nome_declarado_e_lembrado_nas_mensagens_seguintes():
    v = PiiVault()
    assert mask("oi, meu nome é Ana Souza", v).text == "oi, meu nome é [NOME_1] [NOME_2]"
    assert mask("a Ana aqui de novo", v).text == "a [NOME_1] aqui de novo"


def test_sou_de_nao_vira_nome():
    assert mask("sou de São Paulo").text == "sou de São Paulo"


def test_mask_nao_remascara_tokens():
    v = PiiVault()
    t = mask("cep 26703-384", v).text
    assert mask(t, v).text == t


def test_mask_nomes_conhecidos():
    r = mask("Ola Ursula, tudo otimo!", names=["Ursula Souza"])
    assert r.text == "Ola [NOME_1], tudo otimo!"


def test_mask_dict_recursivo_preserva_ids():
    out = mask_dict({"a": ["email x.y@z.com"], "n": 3, "conversation_id": "5521972242584"})
    assert out == {"a": ["email [EMAIL_1]"], "n": 3, "conversation_id": "5521972242584"}


def test_ids_internos_nao_sao_pii_mas_pii_ao_lado_e():
    assert scan('{"message_id": "msg_2b2c99598446", "event_id": "evt_9081989502b1"}') == []
    assert [e.kind for e in scan("msg_2b2c99598446 cpf 389.083.863-43")] == [PiiKind.CPF]


# Auditoria pós-V1: variações que a máscara não cobria
@pytest.mark.parametrize(
    ("texto", "tipo", "valor"),
    [
        ("cep 01310 100", PiiKind.CEP, "01310 100"),
        ("cep 01.310-100", PiiKind.CEP, "01.310-100"),
        ("cep 01310.100", PiiKind.CEP, "01310.100"),
        ("cnpj 12.345.678/0001-95", PiiKind.CNPJ, "12.345.678/0001-95"),
        ("cnpj 12345678000195", PiiKind.CNPJ, "12345678000195"),
        ("rg 12.345.678-9", PiiKind.RG, "12.345.678-9"),
        ("meu RG: 123456789", PiiKind.RG, "123456789"),
        ("identidade nº 12.345.678-X", PiiKind.RG, "12.345.678-X"),
        ("cartão 4111 1111 1111 1111", PiiKind.CARTAO, "4111 1111 1111 1111"),
        ("cartao 5555-5555-5555-4444", PiiKind.CARTAO, "5555-5555-5555-4444"),
        ("cartao 4111111111111111", PiiKind.CARTAO, "4111111111111111"),
        ("amex 3782 822463 10005", PiiKind.CARTAO, "3782 822463 10005"),
    ],
)
def test_detecta_variacoes_da_auditoria(texto, tipo, valor):
    ents = scan(texto)
    assert [(e.kind, e.value) for e in ents] == [(tipo, valor)], ents


@pytest.mark.parametrize(
    ("texto", "partes"),
    [
        ("me chamo Ana da Silva", {"Ana", "Silva"}),
        ("meu nome é joão de souza", {"joão", "souza"}),
        ("sou a Maria dos Santos", {"Maria", "Santos"}),
        ("me chamo Pedro Paulo das Neves", {"Pedro", "Paulo", "Neves"}),
    ],
)
def test_sobrenome_depois_de_da_de(texto, partes):
    assert {e.value for e in scan(texto) if e.kind is PiiKind.NOME} == partes


@pytest.mark.parametrize(
    "texto",
    [
        "número 4111 1111 1111 1112",  # não passa no Luhn
        "franquia de R$ 3.000,00 e prêmio de R$ 1.234,56",
        "protocolo 1234 5678",
        "início em 01/10/2026, 30 dias de carência",
        "sou de São Paulo",
        "sim-conv_01185-1790708560324",  # id do simulador: passava no Luhn por acaso
        "timestamp 1790708560324 ms",
    ],
)
def test_variacoes_sem_falso_positivo(texto):
    assert not contains_pii(texto), scan(texto)


def test_cep_com_espaco_mascarado_e_cotavel():
    """O vault guarda o CEP como o lead escreveu; a cotação normaliza os dígitos."""
    from autoseguro.tools.quote_client import normalize_payload

    v = PiiVault()
    r = mask("o carro dorme no 01310 100", v)
    assert r.text == "o carro dorme no [CEP_1]"
    assert (
        normalize_payload({"idade": 30, "veiculo_ano": 2020, "cep": v.reveal("[CEP_1]")})["cep"]
        == "01310-100"
    )


def test_pseudonimo_com_hmac_e_compativel_sem_chave():
    """Auditoria: SHA-256 sem chave de telefone/CPF é reversível por força bruta."""
    import hashlib

    from autoseguro.agent.service import conversation_ref
    from autoseguro.guardrails.pii import configurar_chave_pseudonimo, pseudonimo

    tel = "omni:inst:5521972242584"
    try:
        configurar_chave_pseudonimo(None)  # sem chave: o mesmo id de antes (conversas já gravadas)
        assert conversation_ref(tel) == "conv_" + hashlib.sha256(tel.encode()).hexdigest()[:16]
        configurar_chave_pseudonimo("segredo-1")
        com_chave = conversation_ref(tel)
        assert com_chave != "conv_" + hashlib.sha256(tel.encode()).hexdigest()[:16]
        assert com_chave == conversation_ref(tel)  # estável com a mesma chave
        v = PiiVault()
        mask("cpf 389.083.863-43", v)
        assert v.tokens["[CPF_1]"] == "h:" + pseudonimo("38908386343")[:20]
        assert mask("de novo 389.083.863-43", v).text == "de novo [CPF_1]"  # mesmo token
        configurar_chave_pseudonimo("segredo-2")
        assert conversation_ref(tel) != com_chave
    finally:
        configurar_chave_pseudonimo(None)

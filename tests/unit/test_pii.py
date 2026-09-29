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


def test_mask_nao_remascara_tokens():
    v = PiiVault()
    t = mask("cep 26703-384", v).text
    assert mask(t, v).text == t


def test_mask_nomes_conhecidos():
    r = mask("Ola Ursula, tudo otimo!", names=["Ursula Souza"])
    assert r.text == "Ola [NOME_1], tudo otimo!"


def test_mask_dict_recursivo():
    out = mask_dict({"a": ["email x.y@z.com"], "n": 3})
    assert out == {"a": ["email [EMAIL_1]"], "n": 3}

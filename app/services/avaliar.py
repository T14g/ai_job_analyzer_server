import json

from openai import OpenAIError

from app.services.gupy import listar_vagas_salvas
from app.services.tendencias import criar_cliente, perguntar


def titulo_principal(titulo: str) -> str:
    return titulo.splitlines()[0].strip()


def extrair_json(texto: str) -> dict:
    limpo = texto.strip()
    if limpo.startswith("```"):
        limpo = limpo.split("\n", 1)[-1]
        if "```" in limpo:
            limpo = limpo[: limpo.rfind("```")]
    inicio = limpo.find("{")
    fim = limpo.rfind("}")
    if inicio == -1 or fim == -1:
        raise RuntimeError("A OpenAI não devolveu a lista de vagas.")
    try:
        return json.loads(limpo[inicio : fim + 1])
    except json.JSONDecodeError as exc:
        raise RuntimeError("A OpenAI devolveu um JSON inválido.") from exc


def indices_validos(dados: dict, total: int) -> list[int]:
    escolhidos = []
    vistos = set()
    for item in dados.get("indices", []):
        if isinstance(item, bool) or not isinstance(item, int):
            continue
        if item < 0 or item >= total or item in vistos:
            continue
        vistos.add(item)
        escolhidos.append(item)
    return escolhidos


def avaliar_area(area: str) -> dict:
    interesse = area.strip()
    if not interesse:
        raise RuntimeError("Informe a área de interesse.")

    vagas = listar_vagas_salvas()
    if not vagas:
        raise RuntimeError("Nenhuma vaga persistida. Busque as vagas antes de avaliar.")

    lista = [
        {"indice": indice, "titulo": titulo_principal(vaga["title"])}
        for indice, vaga in enumerate(vagas)
    ]
    prompt = (
        f"Área de interesse: {interesse}\n\n"
        "A lista abaixo tem as vagas já salvas. Cada item tem indice e titulo.\n"
        "Escolha só as vagas dessa área. Aceite sinônimos e variações de escrita.\n"
        'Responda somente JSON neste formato: {"indices": [0, 2]}\n'
        'Se nenhuma vaga combinar, responda {"indices": []}.\n'
        "Não invente índices.\n\n"
        f"{json.dumps(lista, ensure_ascii=False)}"
    )

    try:
        texto, _, motivo = perguntar(criar_cliente(), prompt)
    except OpenAIError as exc:
        raise RuntimeError(f"A OpenAI recusou a avaliação: {exc}") from exc

    if motivo == "length":
        raise RuntimeError("A avaliação foi cortada no limite de tokens.")
    if not texto.strip():
        raise RuntimeError("A OpenAI devolveu uma resposta vazia.")

    escolhidos = indices_validos(extrair_json(texto), len(vagas))
    matches = [
        {
            "company": vagas[indice]["company"],
            "title": titulo_principal(vagas[indice]["title"]),
            "url": vagas[indice]["url"],
        }
        for indice in escolhidos
    ]
    return {"area": interesse, "matches": matches}

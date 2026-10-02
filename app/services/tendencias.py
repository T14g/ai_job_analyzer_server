import json
import os
from collections import Counter
from collections.abc import Callable
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from dotenv import load_dotenv
from openai import OpenAI

SERVER_ROOT = Path(__file__).resolve().parents[2]
PASTA_VAGAS = SERVER_ROOT / "data" / "vagas"
PASTA_TENDENCIAS = SERVER_ROOT / "data" / "tendencias"
MODELO = "gpt-5.4-nano"
PRECO_ENTRADA_POR_MILHAO = 0.20
PRECO_CACHE_POR_MILHAO = 0.02
PRECO_SAIDA_POR_MILHAO = 1.25

MAX_TOKENS_SAIDA = 800

PROMPT = """Onde há mais vagas de T.I. e qual a tendência, usando só a lista acima.
Cada linha é "quantidade x título".
Responda em português, só neste formato, sem citar títulos:
- Área ou stack — volume aproximado
Tendência: uma frase."""

PROMPT_DEV = """Quais linguagens de programação backend, frontend e full stack estão em alta, usando só a lista acima.
Responda em português, exatamente nestas 6 linhas, sem citar títulos e sem copiar estas instruções:
- Backend — linguagens com volume aproximado
Tendência: frase sobre backend
- Frontend — linguagens com volume aproximado
Tendência: frase sobre frontend
- Full stack — linguagens com volume aproximado
Tendência: frase sobre full stack"""

load_dotenv(SERVER_ROOT / ".env")

_on_status: ContextVar[Callable[[str], None] | None] = ContextVar("on_status_tendencias", default=None)


def emitir(mensagem: str) -> None:
    texto = mensagem.strip()
    if not texto:
        return
    print(texto, flush=True)
    callback = _on_status.get()
    if callback:
        callback(texto)


def arquivo_mais_recente():
    if not PASTA_VAGAS.exists():
        raise FileNotFoundError(f"Nenhum arquivo vagas-*.json em {PASTA_VAGAS}")
    arquivos = list(PASTA_VAGAS.glob("vagas-*.json"))
    if not arquivos:
        raise FileNotFoundError(f"Nenhum arquivo vagas-*.json em {PASTA_VAGAS}")
    return max(arquivos, key=lambda caminho: caminho.name)


def extrair_titulos(caminho):
    with open(caminho, encoding="utf-8") as arquivo:
        dados = json.load(arquivo)

    titulos = []
    for empresa in dados.values():
        for vaga in empresa.get("vagas", []):
            titulo = (vaga.get("titulo") or "").strip()
            if not titulo:
                continue
            titulos.append(titulo.splitlines()[0].strip())
    return titulos


def resumir_titulos(titulos):
    contagem = Counter(titulos)
    return sorted(contagem.items(), key=lambda item: (-item[1], item[0]))


def montar_prompt(instrucao, titulos):
    lista = "\n".join(f"{qtd}x {titulo}" for titulo, qtd in resumir_titulos(titulos))
    return f"Títulos (quantidade x título):\n{lista}\n\n{instrucao}"


def tokens_em_cache(uso):
    detalhes = getattr(uso, "prompt_tokens_details", None)
    if not detalhes:
        return 0
    return getattr(detalhes, "cached_tokens", 0) or 0


def calcular_custo(uso):
    entrada = uso.prompt_tokens or 0
    saida = uso.completion_tokens or 0
    cache = tokens_em_cache(uso)
    entrada_nova = max(entrada - cache, 0)
    custo = (
        entrada_nova * PRECO_ENTRADA_POR_MILHAO
        + cache * PRECO_CACHE_POR_MILHAO
        + saida * PRECO_SAIDA_POR_MILHAO
    ) / 1_000_000
    return entrada, cache, saida, custo


def limpar_texto(texto):
    return texto.replace("**", "").replace("*", "").strip()


def separar_tendencia(texto):
    minusculo = texto.lower()
    for marcador in ("tendência:", "tendencia:"):
        indice = minusculo.rfind(marcador)
        if indice == -1:
            continue
        frase = texto[indice + len(marcador) :].strip()
        resto = texto[:indice].strip().rstrip(".")
        if frase.lower() in {"uma frase", "frase sobre backend", "frase sobre frontend", "frase sobre full stack"}:
            frase = ""
        return resto, frase
    return texto.strip(), ""


def interpretar_resposta(texto):
    areas = []
    atual = None
    for bruta in texto.splitlines():
        linha = limpar_texto(bruta)
        if not linha:
            continue
        if linha.startswith("- "):
            if atual:
                areas.append(atual)
            corpo = linha[2:].strip()
            nome, volume = corpo, ""
            for separador in (" — ", " – ", " - "):
                if separador in corpo:
                    nome, volume = corpo.split(separador, 1)
                    break
            volume, tendencia = separar_tendencia(volume)
            atual = {
                "nome": nome.strip(),
                "volume": volume.strip(),
                "tendencia": tendencia,
            }
            continue
        if linha.lower().startswith("tendência:") or linha.lower().startswith("tendencia:"):
            _, frase = separar_tendencia(linha)
            if not frase:
                continue
            if atual is None:
                atual = {"nome": "Tendência", "volume": "", "tendencia": frase}
            elif not atual["tendencia"]:
                atual["tendencia"] = frase
    if atual:
        areas.append(atual)
    return areas


def areas_desenvolvimento(texto):
    escolhidas = []
    vistos = set()
    for area in interpretar_resposta(texto):
        nome = area["nome"].lower()
        if nome.startswith("backend") or nome.startswith("back-end"):
            chave = "backend"
        elif nome.startswith("frontend") or nome.startswith("front-end"):
            chave = "frontend"
        elif nome.startswith("full stack") or nome.startswith("fullstack") or nome.startswith("full-stack"):
            chave = "fullstack"
        else:
            continue
        if chave in vistos:
            continue
        vistos.add(chave)
        escolhidas.append(area)
    return escolhidas


def criar_cliente():
    load_dotenv(SERVER_ROOT / ".env")
    api_key = os.getenv("OPEN_AI_API_KEY")
    if not api_key:
        raise RuntimeError("Defina OPEN_AI_API_KEY no arquivo .env")
    return OpenAI(api_key=api_key)


def perguntar(cliente, conteudo):
    resposta = cliente.chat.completions.create(
        model=MODELO,
        max_completion_tokens=MAX_TOKENS_SAIDA,
        messages=[{"role": "user", "content": conteudo}],
    )
    escolha = resposta.choices[0]
    return escolha.message.content or "", resposta.usage, escolha.finish_reason


def somar_usos(usos):
    return SimpleNamespace(
        prompt_tokens=sum(uso.prompt_tokens or 0 for uso in usos),
        completion_tokens=sum(uso.completion_tokens or 0 for uso in usos),
        prompt_tokens_details=SimpleNamespace(cached_tokens=sum(tokens_em_cache(uso) for uso in usos)),
    )


def caminho_json_tendencias() -> Path:
    PASTA_TENDENCIAS.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d-%H-%M")
    return PASTA_TENDENCIAS / f"tendencias-{timestamp}.json"


def salvar_json(dados: dict, caminho: Path) -> None:
    caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")


def carregar_tendencias_salvas() -> dict | None:
    if not PASTA_TENDENCIAS.exists():
        return None
    arquivos = sorted(PASTA_TENDENCIAS.glob("tendencias-*.json"))
    for caminho in reversed(arquivos):
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        if "onde_ha_mais_vagas" in dados:
            return dados
    return None


def analisar_e_salvar(on_status: Callable[[str], None] | None = None) -> dict:
    token = _on_status.set(on_status)
    try:
        emitir("Lendo o JSON de vagas mais recente")
        caminho = arquivo_mais_recente()
        titulos = extrair_titulos(caminho)
        emitir(f"Arquivo: {caminho.name}")
        emitir(f"Total: {len(titulos)}")
        emitir(f"Títulos únicos enviados: {len(resumir_titulos(titulos))}")

        cliente = criar_cliente()
        emitir("Consultando onde há mais vagas")
        texto, uso, motivo = perguntar(cliente, montar_prompt(PROMPT, titulos))
        emitir("Resposta de tendências gerais recebida")

        emitir("Consultando tendências de desenvolvimento")
        texto_dev, uso_dev, motivo_dev = perguntar(cliente, montar_prompt(PROMPT_DEV, titulos))
        emitir("Resposta de desenvolvimento recebida")

        cortada = motivo == "length"
        cortada_dev = motivo_dev == "length"
        if cortada or cortada_dev:
            emitir("Uma resposta foi cortada no limite de tokens.")

        uso_total = somar_usos([uso, uso_dev])
        entrada, cache, saida, custo = calcular_custo(uso_total)
        emitir(f"Modelo: {MODELO}")
        emitir(f"Tokens de entrada: {entrada}")
        if cache:
            emitir(f"Tokens em cache: {cache}")
        emitir(f"Tokens de saída: {saida}")
        emitir(f"Custo estimado: US$ {custo:.6f}")

        avisos = []
        if cortada:
            avisos.append("A seção de tendências gerais foi cortada no limite de tokens.")
        if cortada_dev:
            avisos.append("A seção de desenvolvimento foi cortada no limite de tokens.")

        resultado = {
            "arquivo_vagas": caminho.name,
            "total_vagas": len(titulos),
            "titulos_unicos": len(resumir_titulos(titulos)),
            "onde_ha_mais_vagas": interpretar_resposta(texto),
            "desenvolvimento": areas_desenvolvimento(texto_dev),
            "avisos": avisos,
            "modelo": MODELO,
            "entrada": entrada,
            "cache": cache,
            "saida": saida,
            "custo": custo,
        }
        destino = caminho_json_tendencias()
        salvar_json(resultado, destino)
        emitir(f"Arquivo salvo: {destino.name}")
        emitir("Resultado final")
        for area in resultado["onde_ha_mais_vagas"] + resultado["desenvolvimento"]:
            emitir(area["nome"])
        return resultado
    finally:
        _on_status.reset(token)

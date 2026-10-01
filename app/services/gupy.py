import json
import os
import re
import time
from collections.abc import Callable
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

SERVER_ROOT = Path(__file__).resolve().parents[2]
PASTA_VAGAS = SERVER_ROOT / "data" / "vagas"

load_dotenv(SERVER_ROOT / ".env")

_on_status: ContextVar[Callable[[str], None] | None] = ContextVar("on_status", default=None)


def emitir(mensagem: str) -> None:
    texto = mensagem.strip()
    if not texto:
        return
    print(texto, flush=True)
    callback = _on_status.get()
    if callback:
        callback(texto)

SELETORES_VAGA = [
    "a[href*='/vagas/']",
    "a[href*='/job']",
    "a[href*='jobId']",
    "div[class*='job']",
    "li[class*='job']",
    "[data-testid*='job']",
]


def carregar_empresas_do_env() -> list[dict[str, str]]:
    empresas = []
    indice = 1
    while True:
        nome = os.getenv(f"EMPRESA_{indice}_NOME")
        url = os.getenv(f"EMPRESA_{indice}_URL")
        if not nome or not url:
            break
        empresas.append({"nome": nome, "url": url})
        indice += 1
    return empresas


def criar_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--start-maximized")
    options.add_argument("--disable-blink-features=AutomationControlled")
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)


def obter_total_vagas(driver):
    try:
        elemento = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "[data-testid='job-list-amount']"))
        )
        texto = elemento.text.strip()
        numeros = re.findall(r"\d+", texto)
        if numeros:
            return int(numeros[0]), texto
        return None, texto
    except Exception as exc:
        emitir(f"Não foi possível localizar o contador de vagas: {exc}")
        return None, None


def coletar_vagas_da_pagina_atual(driver, vagas_coletadas: dict[str, str]) -> int:
    ultima_altura = driver.execute_script("return document.body.scrollHeight")
    while True:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1.5)
        nova_altura = driver.execute_script("return document.body.scrollHeight")
        if nova_altura == ultima_altura:
            break
        ultima_altura = nova_altura

    elementos = []
    for seletor in SELETORES_VAGA:
        encontrados = driver.find_elements(By.CSS_SELECTOR, seletor)
        if encontrados:
            elementos = encontrados
            break

    novas = 0
    for elemento in elementos:
        titulo = elemento.text.strip()
        link = elemento.get_attribute("href")
        if titulo and link and link not in vagas_coletadas:
            vagas_coletadas[link] = titulo
            novas += 1
    return novas


def clicar_pagina(driver, numero: int) -> bool:
    xpath = (
        f"//*[self::a or self::button or self::li or self::span or self::div]"
        f"[normalize-space(text())='{numero}']"
    )
    elementos = driver.find_elements(By.XPATH, xpath)
    for elemento in elementos:
        if elemento.is_displayed():
            try:
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", elemento)
                time.sleep(0.5)
                driver.execute_script("arguments[0].click();", elemento)
                return True
            except Exception:
                continue
    return False


def tentar_revelar_mais_paginas(driver) -> bool:
    candidatos = ["›", ">", "...", "próxima", "proxima", "next"]
    elementos = driver.find_elements(By.CSS_SELECTOR, "a, button, li, span")
    for elemento in elementos:
        texto = elemento.text.strip().lower()
        if texto in candidatos and elemento.is_displayed():
            try:
                driver.execute_script("arguments[0].click();", elemento)
                time.sleep(1.5)
                return True
            except Exception:
                continue
    return False


def coletar_vagas_de_empresa(driver, nome: str, url: str, max_paginas: int = 50):
    emitir(f"Coletando vagas de {nome}")
    vagas_coletadas: dict[str, str] = {}

    driver.get(url)
    WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    time.sleep(5)

    total_vagas, texto_contador = obter_total_vagas(driver)
    if total_vagas:
        emitir(f"{nome}: contador da página indica {total_vagas} vagas")
    else:
        emitir(f"{nome}: contador total não encontrado. A coleta segue sem essa validação.")

    coletar_vagas_da_pagina_atual(driver, vagas_coletadas)
    emitir(f"{nome}: {len(vagas_coletadas)} vagas encontradas")

    pagina = 2
    tentativas_sem_sucesso = 0

    while pagina <= max_paginas and tentativas_sem_sucesso < 3:
        if total_vagas and len(vagas_coletadas) >= total_vagas:
            emitir(f"{nome}: {len(vagas_coletadas)} vagas encontradas. Total esperado atingido.")
            break

        emitir(f"{nome}: indo para a página {pagina}")
        clicou = clicar_pagina(driver, pagina)

        if not clicou and tentar_revelar_mais_paginas(driver):
            clicou = clicar_pagina(driver, pagina)

        if not clicou:
            emitir(f"{nome}: página {pagina} não encontrada. Encerrando esta empresa.")
            break

        time.sleep(2)
        novas = coletar_vagas_da_pagina_atual(driver, vagas_coletadas)
        emitir(f"{nome}: {len(vagas_coletadas)} vagas encontradas")

        if novas == 0:
            tentativas_sem_sucesso += 1
        else:
            tentativas_sem_sucesso = 0

        pagina += 1

    vagas = [{"titulo": titulo, "link": link} for link, titulo in vagas_coletadas.items()]
    return vagas, total_vagas


def coletar_resultado(driver, empresas: list[dict[str, str]]) -> dict:
    resultado = {}
    for empresa in empresas:
        if "ciandt.com" in empresa["url"].lower():
            emitir(f"Ignorando {empresa['nome']}: vagas da CI&T fora desta coleta")
            continue

        vagas, total = coletar_vagas_de_empresa(driver, empresa["nome"], empresa["url"])
        resultado[empresa["nome"]] = {
            "total_vagas": total,
            "vagas": [{"titulo": vaga["titulo"], "link": vaga["link"]} for vaga in vagas],
        }
    return resultado


def caminho_json_vagas() -> Path:
    PASTA_VAGAS.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d-%H-%M")
    return PASTA_VAGAS / f"vagas-{timestamp}.json"


def salvar_json(dados: dict, caminho: Path) -> None:
    caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")


def exibir_resultado_final(dados: dict) -> None:
    emitir("Resultado final")
    for nome_empresa, info in dados.items():
        total = info.get("total_vagas")
        vagas = info.get("vagas", [])
        emitir(f"{nome_empresa}: {len(vagas)} vagas encontradas")
        if total is None:
            emitir(f"{nome_empresa}: total esperado não encontrado")
        elif len(vagas) == total:
            emitir(f"{nome_empresa}: todas as vagas esperadas foram salvas")
        elif len(vagas) < total:
            emitir(f"{nome_empresa}: faltaram {total - len(vagas)} vaga(s)")
        else:
            emitir(f"{nome_empresa}: coletadas mais vagas do que o esperado")


def achatar_vagas(dados: dict) -> list[dict[str, str]]:
    vagas = []
    for empresa, info in dados.items():
        for vaga in info.get("vagas", []):
            vagas.append(
                {
                    "company": empresa,
                    "title": vaga["titulo"],
                    "url": vaga["link"],
                }
            )
    return vagas


def listar_vagas_salvas() -> list[dict[str, str]]:
    if not PASTA_VAGAS.exists():
        return []
    arquivos = sorted(PASTA_VAGAS.glob("vagas-*.json"))
    if not arquivos:
        return []
    dados = json.loads(arquivos[-1].read_text(encoding="utf-8"))
    return achatar_vagas(dados)


def coletar_e_salvar(on_status: Callable[[str], None] | None = None) -> list[dict[str, str]]:
    token = _on_status.set(on_status)
    try:
        empresas = carregar_empresas_do_env()
        if not empresas:
            raise RuntimeError(
                "Nenhuma empresa configurada no .env. "
                "Adicione EMPRESA_1_NOME, EMPRESA_1_URL e os pares seguintes."
            )

        emitir("Iniciando o navegador")
        driver = criar_driver()
        try:
            resultado = coletar_resultado(driver, empresas)
        finally:
            driver.quit()

        caminho = caminho_json_vagas()
        salvar_json(resultado, caminho)
        emitir(f"Arquivo salvo: {caminho.name}")
        exibir_resultado_final(resultado)
        return achatar_vagas(resultado)
    finally:
        _on_status.reset(token)

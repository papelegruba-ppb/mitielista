"""Consulta lotes TIE con persistencia parcial, reintentos y fuentes trazables."""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import pathlib
import random
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
import urllib.request

from playwright.async_api import async_playwright

PROVINCES = [
    "A Coruña", "Albacete", "Alicante", "Almería", "Araba/Álava", "Asturias",
    "Ávila", "Badajoz", "Balears (Illes)", "Barcelona", "Burgos", "Cáceres",
    "Cádiz", "Cantabria", "Castellón", "Ceuta", "Ciudad Real", "Córdoba",
    "Cuenca", "Girona", "Granada", "Guadalajara", "Guipúzcoa / Gipuzkoa",
    "Huelva", "Huesca", "Jaén", "La Rioja", "Las Palmas", "León", "Lleida",
    "Lugo", "Madrid", "Málaga", "Melilla", "Murcia", "Navarra", "Ourense",
    "Palencia", "Pontevedra", "Salamanca", "Santa Cruz de Tenerife", "Segovia",
    "Sevilla", "Soria", "Tarragona", "Teruel", "Toledo", "Valencia",
    "Valladolid", "Vizcaya / Bizkaia", "Zamora", "Zaragoza"
]
START = "https://icp.administracionelectronica.gob.es/icpplus/index.html"
START_TIE = "https://icp.administracionelectronica.gob.es/icpplustiem/citar?locale=es"
TRAMITE = "RECOGIDA DE TARJETA DE IDENTIDAD DE EXTRANJERO"
ROOT = pathlib.Path(__file__).parent
DEBUG = ROOT / "debug"
RX = re.compile(r"(?:Ú|U)?LTIMO LOTE RECIBIDO.{0,120}?(\d{4})\s*/\s*(\d+)", re.S | re.I)
MAX_AGE_DAYS = 30
RETRIES = 2
PORTAL_INDEX_URL = "https://portalextranjeria.com/lotes-nie/"

# El portal publica un índice común; cada provincia declara sus alias y el
# marcador HTML de oficina. Las fuentes no verificadas quedan como TODO explícito.
PORTAL_OFFICE_PATTERN = re.compile(
    r"(?:Comisar[ií]a de Polic[ií]a de|Comisar[ií]a de|Oficina de)\s+(.{2,100}?)\s+"
    r"LOTE NIE ACTUAL\s*:\s*(20\d{2})\s*/\s*0*(\d{1,5})\s*"
    r"\(Actualizado\s*:\s*(\d{1,2})/(\d{1,2})/(\d{4})\)",
    re.I,
)
PROVINCE_ALIASES = {
    "Araba/Álava": ("alava", "araba", "araba alava"),
    "Balears (Illes)": ("baleares", "illes balears", "islas baleares"),
    "Guipúzcoa / Gipuzkoa": ("guipuzcoa", "gipuzkoa"),
    "Vizcaya / Bizkaia": ("vizcaya", "bizkaia"),
    "A Coruña": ("la coruna", "coruna"),
    "Santa Cruz de Tenerife": ("tenerife", "santa cruz de tenerife"),
}
FALLBACK_CONFIG = {
    province: {
        "aliases": PROVINCE_ALIASES.get(province, (province,)),
        "sources": {
            "portal_extranjeria": {
                "url": PORTAL_INDEX_URL,
                "office_specs": [{"pattern": PORTAL_OFFICE_PATTERN, "date_format": "dmy"}],
            },
            # TODO: añadir fuentes provinciales solo tras verificar URL, estructura
            # HTML, fecha de publicación y marcador que incluya año explícito.
        },
    }
    for province in PROVINCES
}

def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()

def slug(value: str) -> str:
    return normalize(value).replace(" ", "-")

def parse_date(day, month, year):
    try:
        return dt.date(int(year), int(month), int(day)).isoformat()
    except (TypeError, ValueError):
        return None

def parse_official_lot(text: str):
    match = RX.search(text)
    return (int(match.group(1)), int(match.group(2))) if match else None

def parse_portal_html(html_text: str, province: str, source_url: str, checked: str | None = None):
    """Extrae solo lotes con año explícito; nunca deduce el año desde la fecha publicada."""
    checked = checked or dt.date.today().isoformat()
    parser = _TextExtractor()
    parser.feed(html_text)
    output = []
    source_cfg = FALLBACK_CONFIG.get(province, {}).get("sources", {}).get("portal_extranjeria", {})
    for spec in source_cfg.get("office_specs", []):
        for match in spec["pattern"].finditer(parser.text):
            name = re.sub(r"\s+", " ", match.group(1)).strip(" :-–")
            year, number = int(match.group(2)), int(match.group(3))
            published = parse_date(*match.group(4, 5, 6))
            if not name or not published:
                continue
            output.append({
                "id": slug(province + "-" + name)[:48],
                "prov": province, "name": name, "y": year, "n": number,
                "checked": checked, "published": published,
                "source": "Portal Extranjería", "source_url": source_url,
                "source_type": "public_unofficial",
                "source_checked": dt.datetime.now(dt.timezone.utc).isoformat(),
            })
    return output

class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.links = [], []
        self._link = None
        self._skip = 0
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("script", "style", "noscript", "svg"):
            self._skip += 1
        if tag == "a" and attrs.get("href"):
            self._link = [attrs["href"], []]
        if tag in ("br", "p", "div", "section", "article", "h1", "h2", "h3", "li"):
            self.parts.append(" ")
    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg") and self._skip:
            self._skip -= 1
        if tag == "a" and self._link:
            self.links.append((self._link[0], "".join(self._link[1]).strip()))
            self._link = None
        if tag in ("p", "div", "section", "article", "h1", "h2", "h3", "li"):
            self.parts.append(" ")
    def handle_data(self, data):
        if self._skip:
            return
        self.parts.append(data)
        if self._link:
            self._link[1].append(data)
    @property
    def text(self):
        return re.sub(r"\s+", " ", " ".join(self.parts)).strip()

async def accept(page):
    try:
        await page.get_by_role("button", name=re.compile("Aceptar", re.I)).first.click()
    except Exception:
        # El botón puede no existir si la transición ya se completó.
        pass
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=10000)
    except Exception:
        pass

async def open_province(page, province):
    last_error = None
    for start in (START, START_TIE):
        try:
            await page.goto(start, wait_until="commit", timeout=25000)
            select = page.locator("select").first
            await select.wait_for(state="visible", timeout=20000)
            await select.select_option(label=province)
            await accept(page)
            return
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"no se pudo seleccionar provincia {province}: {last_error}")

async def pick_tramite(page):
    for select in await page.locator("select").all():
        for option in await select.locator("option").all():
            if TRAMITE in ((await option.text_content()) or "").upper():
                value = await option.get_attribute("value")
                await select.select_option(value=value)
                return
    raise RuntimeError("no se encontró el trámite de recogida de TIE")

async def select_office(page, value):
    for select in await page.locator("select").all():
        try:
            if await select.locator(f'option[value="{value}"]').count():
                await select.select_option(value=value)
                return
        except Exception:
            continue
    raise RuntimeError(f"la oficina con identificador {value!r} no aparece tras elegir el trámite")

async def read_lote(page, province, value, province_ready=False):
    # La provincia se abre una vez por lote provincial; para las oficinas
    # siguientes se reutiliza el contexto/página y se vuelve a elegir el trámite.
    if not province_ready:
        await open_province(page, province)
    await pick_tramite(page)
    await accept(page)
    await select_office(page, value)
    await accept(page)
    lot = parse_official_lot(await page.inner_text("body"))
    if not lot:
        body = (await page.inner_text("body")).lower()
        if "captcha" in body or "robot" in body:
            raise RuntimeError("captcha")
        if any(word in body for word in ("bloqueado", "demasiadas solicitudes", "access denied", "forbidden")):
            raise RuntimeError("bloqueo")
        raise RuntimeError("timeout/dato no encontrado: no aparece el último lote")
    return lot

async def snap(page, name):
    DEBUG.mkdir(exist_ok=True)
    try:
        (DEBUG / f"{name}.html").write_text(await page.content(), encoding="utf-8")
    except Exception as exc:
        print(f"[debug] HTML no disponible ({name}): {exc}")
    try:
        await page.screenshot(path=str(DEBUG / f"{name}.png"), full_page=True, timeout=15000)
    except Exception as exc:
        print(f"[debug] captura no disponible ({name}): {exc}")

async def scrape(results: list[dict] | None = None):
    """Añade cada resultado a la lista compartida en cuanto se obtiene."""
    if results is None:
        results = []
    stats = Counter()
    errors = Counter()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            locale="es-ES", timezone_id="Europe/Madrid",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        )
        page = await context.new_page()
        page.set_default_timeout(30000)
        page.set_default_navigation_timeout(20000)
        for province in PROVINCES:
            try:
                await open_province(page, province)
                options = [
                    ((await option.get_attribute("value")) or "",
                     ((await option.text_content()) or "").strip())
                    for option in await page.locator("select").first.locator("option").all()
                ]
                offices = [(value, name) for value, name in options
                           if value.strip() and not name.upper().startswith("SELEC")]
            except Exception as exc:
                stats["province_errors"] += 1
                cause = classify_error(exc)
                errors[cause] += 1
                print(f"[{province}] ERROR ({cause}): {exc}")
                await snap(page, slug(province) + "-provincia")
                continue
            # Cada provincia usa una sesión/página persistente. Si el resultado
            # deja la página en estado no reutilizable, reiniciar el flujo en esa
            # misma pestaña, sin crear un contexto nuevo.
            province_ready = True
            for value, name in offices:
                error = None
                for attempt in range(RETRIES + 1):
                    try:
                        if attempt:
                            await asyncio.sleep(2 ** attempt + random.random())
                            await open_province(page, province)
                            province_ready = True
                        year, number = await read_lote(page, province, value, province_ready=province_ready)
                        results.append({
                            "id": slug(province + "-" + name)[:48], "prov": province,
                            "name": name, "y": year, "n": number,
                            "checked": dt.date.today().isoformat(),
                        })
                        stats["ok"] += 1
                        print(f"[{province}] OK {name}: {year}/{number}")
                        error = None
                        break
                    except Exception as exc:
                        error = exc
                        cause = classify_error(exc)
                        if attempt < RETRIES:
                            print(f"[{province}] REINTENTO {attempt + 1}/{RETRIES} {name} ({cause}): {exc}")
                if error is not None:
                    cause = classify_error(error)
                    stats["errors"] += 1
                    errors[cause] += 1
                    print(f"[{province}] ERROR {name} ({cause}): {error}")
                    await snap(page, slug(province + "-" + name)[:40])
                    # El siguiente intento/oficina debe recuperar el estado del flujo.
                    province_ready = False
                else:
                    province_ready = False
                await asyncio.sleep(random.uniform(0.5, 1.2))
        await browser.close()
    print("Resumen ICP+: " + ", ".join(f"{key}={stats[key]}" for key in ("ok", "errors", "province_errors")))
    print("Causas: " + (", ".join(f"{key}={value}" for key, value in sorted(errors.items())) or "sin errores"))
    return results

def classify_error(exc):
    message = str(exc).lower()
    if "captcha" in message or "robot" in message:
        return "captcha"
    if any(word in message for word in ("bloque", "forbidden", "access denied", "429", "403")):
        return "bloqueo"
    if any(word in message for word in ("timeout", "timed out", "no aparece", "no encontrado")):
        return "timeout"
    return "error"

def merge(prev, results, today):
    old = {office["id"]: office for office in prev.get("offices", [])}
    cutoff = dt.date.fromisoformat(today) - dt.timedelta(days=MAX_AGE_DAYS)
    retained = []
    for office in old.values():
        dates = []
        for field in ("published", "checked"):
            value = office.get(field)
            if not value:
                continue
            try:
                dates.append(dt.date.fromisoformat(str(value)[:10]))
            except (TypeError, ValueError):
                # Una fecha presente pero inválida impide retener el registro.
                dates.append(None)
        # Si cualquiera de las fechas conocidas es antigua (o inválida),
        # descartar. Sin ninguna fecha no se puede acreditar vigencia.
        if dates and all(date is not None and date >= cutoff for date in dates):
            retained.append(office)
    output = []
    for record in results:
        previous = old.get(record["id"], {})
        history = list(previous.get("h", [])) if previous.get("y") == record.get("y") else []
        if record.get("source_type") != "public_unofficial":
            if history and history[-1][0] == today:
                history[-1][1] = record["n"]
            else:
                history.append([today, record["n"]])
        record["h"] = history[-90:]
        output.append(record)
    seen = {record["id"] for record in output}
    output.extend(office for office in retained if office["id"] not in seen)
    return sorted(output, key=lambda office: (office["prov"], office["name"]))

def _fetch_html(url):
    request = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; MiTIELista/1.0; +https://github.com/papelegruba-ppb/mitielista)"
    })
    with urllib.request.urlopen(request, timeout=25) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status}")
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise RuntimeError("respuesta demasiado grande")
    return raw.decode("utf-8", "replace")

async def fallback_public_sources():
    """Consulta fuentes configuradas y exige dos dominios independientes."""
    today = dt.date.today().isoformat()
    candidates = []
    # La configuración por provincia controla URLs, alias y marcadores.
    configs_by_url = defaultdict(list)
    for province, config in FALLBACK_CONFIG.items():
        for source_id, source in config.get("sources", {}).items():
            if source.get("url"):
                configs_by_url[(source_id, source["url"])].append(province)

    fetched_indexes = {}
    for (source_id, index_url), provinces in configs_by_url.items():
        if source_id != "portal_extranjeria":
            # TODO: implementar un parser cuando se verifique la estructura HTML.
            print(f"[fallback:{source_id}] parser pendiente; no se extraen datos")
            continue
        try:
            if index_url not in fetched_indexes:
                index_parser = _TextExtractor()
                index_parser.feed(_fetch_html(index_url))
                links = {}
                for href, label in index_parser.links:
                    absolute = urljoin(index_url, href).split("#", 1)[0]
                    parsed = urlparse(absolute)
                    if parsed.netloc.lower() != "portalextranjeria.com":
                        continue
                    if re.fullmatch(r"/lotes-nie-[a-z0-9-]+/?", parsed.path):
                        links[parsed.path.rstrip("/") + "/"] = absolute
                fetched_indexes[index_url] = links
                print(f"[fallback:{source_id}] páginas de provincia en índice: {len(links)}")
            links = fetched_indexes[index_url]
            for path, url in links.items():
                try:
                    page_parser = _TextExtractor()
                    page_parser.feed(_fetch_html(url))
                    title_match = re.search(r"Lotes NIE\s+(.+?)\s+(?:hoy|actual)", page_parser.text, re.I)
                    if not title_match:
                        continue
                    page_name = normalize(title_match.group(1))
                    matched_province = None
                    for province in provinces:
                        aliases = FALLBACK_CONFIG[province].get("aliases", (normalize(province),))
                        if any(page_name == normalize(alias) for alias in aliases):
                            matched_province = province
                            break
                    if not matched_province:
                        continue
                    records = parse_portal_html(_fetch_html(url), matched_province, url, today)
                    candidates.extend(records)
                    print(f"[fallback:{matched_province}] {len(records)} candidatos ({url})")
                except Exception as exc:
                    print(f"[fallback:{path}] error ({classify_error(exc)}): {exc}")
        except Exception as exc:
            print(f"[fallback:{source_id}] índice no disponible ({classify_error(exc)}): {exc}")

    try:
        from sources import scrape_secondary_sources
        candidates.extend(await asyncio.to_thread(scrape_secondary_sources))
    except Exception as exc:
        print(f"[fallback] fuentes secundarias no disponibles: {exc}")

    grouped = defaultdict(list)
    for item in candidates:
        # Año y fecha de publicación explícitos son requisitos para publicar.
        if not item.get("published") or not item.get("y"):
            continue
        grouped[(normalize(item["prov"]), normalize(item["name"]), item["y"], item["n"])].append(item)

    accepted = []
    for key, records in grouped.items():
        independent = {
            urlparse(record.get("source_url", "")).netloc.lower()
            for record in records
            if record.get("source_url") and urlparse(record["source_url"]).netloc
        }
        if len(independent) < 2:
            continue
        chosen = sorted(records, key=lambda record: (
            record.get("source_type") != "official_public_notice",
            record.get("published") or "",
        ))[0].copy()
        chosen["source"] = " / ".join(sorted({record.get("source", "") for record in records if record.get("source")}))
        chosen["source_url"] = records[0].get("source_url", "")
        chosen["source_type"] = "public_unofficial" if all(
            record.get("source_type") != "official_public_notice" for record in records
        ) else "official_public_notice"
        chosen["sources_count"] = len(independent)
        accepted.append(chosen)
    print(f"[fallback] candidatos={len(candidates)} aceptados con ≥2 fuentes independientes={len(accepted)}")
    return accepted

async def main():
    results = []
    try:
        await asyncio.wait_for(scrape(results), timeout=30 * 60)
    except asyncio.TimeoutError:
        print(f"TIMEOUT global 30 min; se conservan {len(results)} resultados parciales.")
    except Exception as exc:
        print(f"Falló ICP+: {exc}; se conservan {len(results)} resultados parciales.")
    print("Consultando fuentes públicas de respaldo (solo coincidencia de 2 fuentes independientes).")
    fallback = await fallback_public_sources()
    existing = {record["id"] for record in results}
    results.extend(record for record in fallback if record["id"] not in existing)
    if not results:
        sys.exit("Sin resultados verificables: se conserva lotes.json y no se publica nada.")
    data_file = ROOT / "lotes.json"
    previous = json.loads(data_file.read_text(encoding="utf-8")) if data_file.exists() else {}
    if any("ejemplo" in office.get("name", "").lower() for office in previous.get("offices", [])):
        previous = {}
    today = dt.date.today().isoformat()
    merged = merge(previous, results, today)
    data_file.write_text(json.dumps({"updated": today, "offices": merged}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Actualización final: resultados={len(results)}, oficinas publicadas={len(merged)}")

if __name__ == "__main__":
    asyncio.run(main())

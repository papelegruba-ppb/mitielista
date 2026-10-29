"""Lee el último lote TIE publicado en cada oficina (sede de extranjería) y actualiza lotes.json.
Uso: python scrape.py   |   Añade provincias en PROVINCES."""
import asyncio, json, re, sys, unicodedata, datetime, pathlib, random
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
RX = re.compile(r"LTIMO LOTE RECIBIDO.{0,120}?(\d{4})\s*/\s*(\d+)", re.S | re.I)

def slug(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")

async def accept(page):
    await page.get_by_role("button", name=re.compile("Aceptar", re.I)).first.click()
    # Algunas respuestas de la sede mantienen la navegación abierta; no bloquearse
    # esperando DOMContentLoaded si el formulario ya está disponible.
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=15000)
    except Exception:
        pass

async def open_province(page, prov):
    # Empezar en la página inicial sin provincia seleccionada, como hace una persona.
    # La URL /icpplustiem/citar?p=28 es una fase posterior específica de Madrid;
    # nunca se debe reutilizar ese código para otras provincias.
    # La ruta TIE queda como alternativa si la página inicial no ofrece el selector.
    last_error = None
    for start in (START, START_TIE):
        try:
            await page.goto(start, wait_until="commit", timeout=25000)
            await page.locator("select").first.wait_for(state="visible", timeout=20000)
            await page.locator("select").first.select_option(label=prov)
            await accept(page)
            return
        except Exception as e:
            last_error = e
    raise RuntimeError(f"no se pudo abrir ICP+ y seleccionar la provincia {prov}: {last_error}")

async def pick_tramite(page):
    for s in await page.locator("select").all():
        for o in await s.locator("option").all():
            if TRAMITE in (await o.text_content() or "").upper():
                await s.select_option(value=await o.get_attribute("value"))
                return
    raise RuntimeError("no se encontró el trámite de recogida de TIE")

async def read_lote(page, prov, value):
    # El flujo de ICP+ exige primero provincia, después trámite y finalmente oficina.
    await open_province(page, prov)
    await pick_tramite(page)
    await accept(page)

    # Tras elegir el trámite, ICP+ carga el selector de oficinas. No asumir que
    # sigue siendo el primer <select>: localizar el desplegable que contiene la
    # oficina concreta y seleccionarla por value.
    candidates = await page.locator("select").all()
    selected = False
    for select in candidates:
        try:
            option = select.locator("option").filter(has_text=re.compile(
                "^" + re.escape(value) + "$"
            ))
            if await option.count():
                await select.select_option(value=value)
                selected = True
                break
        except Exception:
            continue
    if not selected:
        # Algunos formularios vuelven a poblar el primer selector tras el trámite.
        for select in await page.locator("select").all():
            try:
                if await select.locator(f'option[value="{value}"]').count():
                    await select.select_option(value=value)
                    selected = True
                    break
            except Exception:
                continue
    if not selected:
        raise RuntimeError(f"la oficina con identificador {value!r} no aparece después de elegir el trámite")

    await accept(page)
    m = RX.search(await page.inner_text("body"))
    if not m:
        raise RuntimeError("no aparece el último lote (¿captcha, bloqueo o trámite/oficina no disponibles?)")
    return int(m.group(1)), int(m.group(2))

async def snap(page, name):
    """Guarda lo que se pueda del diagnóstico sin ocultar el error original."""
    DEBUG.mkdir(exist_ok=True)
    try:
        html = await page.content()
        (DEBUG / f"{name}.html").write_text(html, encoding="utf-8")
    except Exception as e:
        print(f"[debug] no se pudo guardar HTML ({name}): {e}")
    try:
        await page.screenshot(path=str(DEBUG / f"{name}.png"), full_page=True, timeout=15000)
    except Exception as e:
        print(f"[debug] no se pudo guardar captura ({name}): {e}")

async def scrape():
    results = []
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        ctx = await b.new_context(locale="es-ES", timezone_id="Europe/Madrid",
              user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")
        page = await ctx.new_page()
        page.set_default_timeout(30000)
        page.set_default_navigation_timeout(20000)
        for prov in PROVINCES:
            try:
                await open_province(page, prov)
                opts = [((await o.get_attribute("value")) or "", ((await o.text_content()) or "").strip())
                        for o in await page.locator("select").first.locator("option").all()]
                offices = [(v, t) for v, t in opts if v.strip() and not t.upper().startswith("SELEC")]
            except Exception as e:
                print(f"[{prov}] error: {e}"); await snap(page, slug(prov) + "-provincia"); continue
            for value, name in offices:
                try:
                    y, n = await read_lote(page, prov, value)
                    results.append({"id": slug(prov + "-" + name)[:48], "prov": prov, "name": name, "y": y, "n": n, "checked": datetime.date.today().isoformat()})
                    print(f"[{prov}] {name}: {y}/{n}")
                except Exception as e:
                    print(f"[{prov}] {name}: error: {e}"); await snap(page, slug(prov + "-" + name)[:40])
                await asyncio.sleep(random.uniform(0.5, 1.2))
        await b.close()
    return results

def merge(prev, results, today):
    old = {o["id"]: o for o in prev.get("offices", [])}
    out = []
    for r in results:
        o = old.get(r["id"], {})
        h = o.get("h", []) if o.get("y") == r["y"] else []
        if r.get("source_type") != "public_unofficial":
            if h and h[-1][0] == today: h[-1][1] = r["n"]
            else: h.append([today, r["n"]])
        r["h"] = h[-90:]; out.append(r)
    seen = {r["id"] for r in results}
    out += [o for o in old.values() if o["id"] not in seen]
    return sorted(out, key=lambda o: (o["prov"], o["name"]))

# Fuentes públicas alternativas. Portal Extranjería publica páginas por provincia
# con lotes por oficina. No se consulta gob.es en esta función.
async def fallback_public_sources():
    import urllib.request
    from html.parser import HTMLParser
    from urllib.parse import urljoin, urlparse

    ROOT_URL = "https://portalextranjeria.com/lotes-nie/"
    HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MiTIELista/1.0; +https://github.com/papelegruba-ppb/mitielista)"}

    class TextExtractor(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts = []
            self.links = []
            self._link = None
            self._skip = 0
        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag in ("script", "style", "noscript"):
                self._skip += 1
            if tag == "a" and attrs.get("href"):
                self._link = [attrs["href"], []]
            if tag in ("br", "p", "div", "section", "article", "h1", "h2", "h3", "li"):
                self.parts.append(" ")
        def handle_endtag(self, tag):
            if tag in ("script", "style", "noscript") and self._skip:
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
            if self._link is not None:
                self._link[1].append(data)
        @property
        def text(self):
            return re.sub(r"\s+", " ", " ".join(self.parts)).strip()

    def fetch(url):
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=25) as response:
            if response.status != 200:
                raise RuntimeError(f"HTTP {response.status}")
            raw = response.read()
        parser = TextExtractor()
        parser.feed(raw.decode("utf-8", "replace"))
        return parser

    def iso_date(match):
        if not match:
            return None
        # Acepta tanto un Match de regex como una tupla de grupos capturados.
        groups = match.groups() if hasattr(match, "groups") else match
        day, month, year = map(int, groups)
        try:
            return datetime.date(year, month, day).isoformat()
        except ValueError:
            return None

    today = datetime.date.today().isoformat()
    found = []
    try:
        index = fetch(ROOT_URL)
        province_pages = []
        for href, label in index.links:
            absolute = urljoin(ROOT_URL, href).split("#", 1)[0]
            path = urlparse(absolute).path.rstrip("/") + "/"
            if urlparse(absolute).netloc != "portalextranjeria.com":
                continue
            if re.fullmatch(r"/lotes-nie-[a-z0-9-]+/", path) and absolute not in province_pages:
                province_pages.append(absolute)
        # La página nacional puede enlazar solo una parte de provincias; se siguen
        # todos los enlaces provinciales encontrados y se informa de errores parciales.
        print(f"[fallback:Portal Extranjería] páginas provinciales detectadas: {len(province_pages)}")
        for url in province_pages:
            try:
                parser = fetch(url)
                text = parser.text
                title_match = re.search(r"Lotes NIE\s+(.+?)\s+(?:hoy|actual)", text, re.I)
                prov = title_match.group(1).strip(" :-") if title_match else ""
                if not prov:
                    slug_match = re.search(r"/lotes-nie-(.+)/$", urlparse(url).path)
                    prov = slug_match.group(1).replace("-", " ").title() if slug_match else "Desconocida"
                # Cada bloque publicado contiene nombre de comisaría, lote y fecha.
                pattern = re.compile(
                    r"(?:Comisar[ií]a de Polic[ií]a de|Comisar[ií]a de|Oficina de)\s+(.{2,100}?)\s+"
                    r"LOTE NIE ACTUAL\s*:\s*0*(\d{1,4})\s*"
                    r"\(Actualizado\s*:\s*(\d{1,2})/(\d{1,2})/(\d{4})\)",
                    re.I
                )
                matches = list(pattern.finditer(text))
                # Algunos listados usan encabezado de oficina seguido directamente del lote.
                if not matches:
                    pattern = re.compile(
                        r"([A-ZÁÉÍÓÚÜÑ][^.!?]{2,90}?)\s+LOTE NIE ACTUAL\s*:\s*0*(\d{1,4})\s*"
                        r"\(Actualizado\s*:\s*(\d{1,2})/(\d{1,2})/(\d{4})\)",
                        re.I
                    )
                    matches = list(pattern.finditer(text))
                for m in matches:
                    name = re.sub(r"\s+", " ", m.group(1)).strip(" :-–")
                    if not name or name.lower() in {"actual", "hoy"}:
                        continue
                    number = int(m.group(2))
                    published = iso_date(m.group(3, 4, 5))
                    item = {
                        "id": slug(prov + "-" + name)[:48],
                        "prov": prov,
                        "name": name,
                        "y": int(published[:4]) if published else datetime.date.today().year,
                        "n": number,
                        "checked": today,
                        "published": published,
                        "source": "Portal Extranjería",
                        "source_url": url,
                        "source_type": "public_unofficial",
                        "source_checked": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    }
                    found.append(item)
                print(f"[fallback:Portal Extranjería] {prov}: {len(matches)} oficinas")
            except Exception as e:
                print(f"[fallback:Portal Extranjería] fallo en {url}: {e}")
    except Exception as e:
        print(f"[fallback:Portal Extranjería] no se pudo leer el índice nacional: {e}")

    # Deduplicar por oficina conservando la publicación más reciente, sin inventar
    # fechas ni exigir dos webs que podrían estar copiando la misma fuente.
    dedup = {}
    for item in found:
        key = item["id"]
        current = dedup.get(key)
        if current is None or (item.get("published") or "") > (current.get("published") or ""):
            dedup[key] = item
    results = list(dedup.values())
    print(f"[fallback] total de oficinas no oficiales extraídas: {len(results)}")
    return results

if __name__ == "__main__":
    try:
        # La sede puede tardar varios minutos en recorrer todas las provincias.
        # No cancelar a los 90 s: wait_for descartaba todos los resultados parciales.
        # El límite global lo controla el timeout del job de GitHub Actions.
        results = asyncio.run(scrape())
    except Exception as e:
        print(f"Falló la consulta oficial: {e}; se activa el fallback público.")
        results = []
    print("Comprobando fuentes públicas alternativas para cubrir oficinas no obtenidas oficialmente.")
    fallback = asyncio.run(fallback_public_sources())
    existing_ids = {r["id"] for r in results}
    results.extend(r for r in fallback if r["id"] not in existing_ids)
    # Fuentes adicionales: solo se incorporan lotes con formato explícito y trazabilidad.
    # El frontend actual conserva un registro vigente por oficina; si ya existe una
    # observación para esa oficina, no se sustituye automáticamente por una señal secundaria.
    try:
        from sources import scrape_secondary_sources
        secondary = scrape_secondary_sources()
        known_ids = {r["id"] for r in results}
        for item in secondary:
            if item["id"] not in known_ids:
                results.append(item)
                known_ids.add(item["id"])
    except Exception as e:
        print(f"[fuentes adicionales] error aislado: {e}")
    if not results:
        sys.exit("Sin resultados verificables: se conserva lotes.json y no se publica nada.")
    f = ROOT / "lotes.json"
    prev = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    if any("ejemplo" in o["name"] for o in prev.get("offices", [])): prev = {}   # descarta datos de demostración
    today = datetime.date.today().isoformat()
    f.write_text(json.dumps({"updated": today, "offices": merge(prev, results, today)}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(len(results), "oficinas actualizadas")

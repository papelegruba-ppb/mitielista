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
    # Esperar a que el servidor entregue el documento, no a que terminen
    # todos los eventos de carga: la sede a veces no dispara DOMContentLoaded.
    await page.goto(START, wait_until="commit", timeout=90000)
    await page.locator("select").first.wait_for(state="visible", timeout=30000)
    await page.locator("select").first.select_option(label=prov)
    await accept(page)

async def pick_tramite(page):
    for s in await page.locator("select").all():
        for o in await s.locator("option").all():
            if TRAMITE in (await o.text_content() or "").upper():
                await s.select_option(value=await o.get_attribute("value"))
                return
    raise RuntimeError("no se encontró el trámite de recogida de TIE")

async def read_lote(page, prov, value):
    await open_province(page, prov)
    await page.locator("select").first.select_option(value=value)
    await pick_tramite(page)
    await accept(page)
    m = RX.search(await page.inner_text("body"))
    if not m:
        raise RuntimeError("no aparece el último lote (¿captcha o bloqueo?)")
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
        page.set_default_timeout(90000)
        page.set_default_navigation_timeout(90000)
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

# Fuentes públicas alternativas. Se conserva la fecha de publicación de cada fuente;
# nunca se presenta la fecha de consulta como si el lote se hubiera actualizado hoy.
async def fallback_public_sources():
    import urllib.request
    from html.parser import HTMLParser

    sources = [
        ("https://lotenie.es/zaragoza/", "Lotenie"),
        ("https://portalextranjeria.com/lotes-nie-zaragoza/", "Portal Extranjería"),
        ("https://sclt.es/tie/zaragoza/zaragoza/", "SCLT"),
    ]
    found = []
    for url, source_name in sources:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 MiTIELista/1.0"})
            with urllib.request.urlopen(req, timeout=20) as response:
                page = response.read().decode("utf-8", "ignore")
            clean = re.sub(r"<script\b.*?</script>|<style\b.*?</style>", " ", page, flags=re.I|re.S)
            clean = re.sub(r"<[^>]+>", " ", clean)
            clean = (clean.replace("&nbsp;", " ").replace("&#160;", " ")
                        .replace("&amp;", "&").replace("&#8217;", "'"))
            clean = re.sub(r"\s+", " ", clean)
            # La página contiene varias oficinas; extraer cada bloque por nombre y su lote/fecha.
            office_specs = [
                ("Zaragoza Unidad Doc. Extranjeros", r"(?:Zaragoza Unidad Doc\.? Extranjeros|Comisaría de Extranjería de Zaragoza|CNP Zaragoza)", "Zaragoza Unidad Doc. Extranjeros"),
                ("Calatayud", r"(?:CNP Calatayud|Comisaría de Extranjería de Calatayud|Calatayud)", "Calatayud"),
            ]
            for office_id_name, marker, office_name in office_specs:
                for hit in re.finditer(marker, clean, re.I):
                    block = clean[max(0, hit.start()-160):min(len(clean), hit.end()+450)]
                    lm = re.search(r"(?:LOTE(?: NIE)?(?: ACTUAL)?|Lote actual|lote actual|Current lote)[^0-9]{0,40}(?:(20\d{2})\s*/\s*)?(\d{1,4})", block, re.I)
                    if not lm:
                        lm = re.search(r"(20\d{2})\s*/\s*(\d{1,4})", block)
                    if not lm:
                        continue
                    year = int(lm.group(1) or datetime.date.today().year)
                    number = int(lm.group(2))
                    dm = re.search(r"(?:Act(?:ualizado)?|Actualizado|Última actualización|Last update)[^0-9]{0,25}(\d{1,2})[/-](\d{1,2})[/-](20\d{2})", block, re.I)
                    if not dm:
                        dm = re.search(r"(\d{1,2})/(\d{1,2})/(20\d{2})", block)
                    published = f"{dm.group(3)}-{int(dm.group(2)):02d}-{int(dm.group(1)):02d}" if dm else None
                    found.append({
                        "id": slug("Zaragoza-" + office_name), "prov": "Zaragoza",
                        "name": office_name, "y": year, "n": number,
                        "checked": datetime.date.today().isoformat(),
                        "published": published, "source": source_name, "source_url": url,
                        "source_type": "public_unofficial",
                        "source_checked": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    })
                    break
        except Exception as e:
            print(f"[fallback:{source_name}] {e}")
    # Solo aceptar el mismo número respaldado por dos fuentes independientes.
    groups = {}
    for item in found:
        groups.setdefault((item["id"], item["y"], item["n"]), []).append(item)
    agreed = []
    for (office_id, year, number), items in groups.items():
        if len({x["source"] for x in items}) >= 2:
            agreed.append(max(items, key=lambda x: x.get("published") or ""))
            print(f"[fallback] {items[0]['name']}: {year}/{number} (no oficial; publicado {agreed[-1].get('published') or 'fecha no disponible'})")
    return agreed

if __name__ == "__main__":
    try:
        results = asyncio.run(asyncio.wait_for(scrape(), timeout=15 * 60))
    except asyncio.TimeoutError:
        print("La consulta oficial superó 15 minutos; se activa el fallback público.")
        results = []
    except Exception as e:
        print(f"Falló la consulta oficial: {e}; se activa el fallback público.")
        results = []
    print("Comprobando fuentes públicas alternativas para cubrir oficinas no obtenidas oficialmente.")
    fallback = asyncio.run(fallback_public_sources())
    official_ids = {r["id"] for r in results}
    results.extend(r for r in fallback if r["id"] not in official_ids)
    if not results:
        sys.exit("Sin resultados verificables: se conserva lotes.json y no se publica nada.")
    f = ROOT / "lotes.json"
    prev = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    if any("ejemplo" in o["name"] for o in prev.get("offices", [])): prev = {}   # descarta datos de demostración
    today = datetime.date.today().isoformat()
    f.write_text(json.dumps({"updated": today, "offices": merge(prev, results, today)}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(len(results), "oficinas actualizadas")

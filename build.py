"""Genera páginas estáticas para Mi TIE Lista."""
import html, json, os, pathlib, re, shutil, unicodedata
from urllib.parse import urlsplit

ROOT = pathlib.Path(__file__).parent
OUT = ROOT / "site"
tpl = (ROOT / "template.html").read_text(encoding="utf-8")
data = json.loads((ROOT / "lotes.json").read_text(encoding="utf-8"))
offices = data.get("offices", [])
DOMAIN = os.environ.get("DOMAIN", "https://mitielista.com").strip().rstrip("/")
BRAND, SITE = "Papelegruba", "Mi TIE Lista"
CITA = "https://icp.administracionelectronica.gob.es/icpplus/index.html"
parts = urlsplit(DOMAIN)
HOST = parts.netloc.lower()
IS_GITHUB_IO = HOST.endswith(".github.io") or HOST == "github.io"
BASE_PATH = parts.path.strip("/")
BASE = "/" + BASE_PATH + "/" if BASE_PATH else "/"
PROVINCES = [
 "A Coruña","Albacete","Alicante","Almería","Araba/Álava","Asturias","Ávila","Badajoz",
 "Balears (Illes)","Barcelona","Burgos","Cáceres","Cádiz","Cantabria","Castellón","Ceuta",
 "Ciudad Real","Córdoba","Cuenca","Girona","Granada","Guadalajara","Guipúzcoa / Gipuzkoa",
 "Huelva","Huesca","Jaén","La Rioja","Las Palmas","León","Lleida","Lugo","Madrid","Málaga",
 "Melilla","Murcia","Navarra","Ourense","Palencia","Pontevedra","Salamanca",
 "Santa Cruz de Tenerife","Segovia","Sevilla","Soria","Tarragona","Teruel","Toledo",
 "Valencia","Valladolid","Vizcaya / Bizkaia","Zamora","Zaragoza"
]
esc = html.escape

def slug(value):
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")

def province_path(prov):
    return "lote-tie/" + slug(prov) + "/"

def office_path(o):
    return province_path(o["prov"]) + slug(o["name"]) + "/"

def date_es(value):
    try:
        y, m, d = value[:10].split("-")
        return f"{d}/{m}/{y}"
    except (TypeError, ValueError, IndexError):
        return "fecha no confirmada"

def official_link():
    return f'<a href="{CITA}" target="_blank" rel="noopener noreferrer">Consultar sede y cita oficial</a>'

def office_info(o):
    source = esc(o.get("source") or "fuente no identificada")
    published = date_es(o.get("published"))
    checked = date_es(o.get("checked") or data.get("updated"))
    source_url = o.get("source_url", "")
    link = f'<a href="{esc(source_url, quote=True)}" target="_blank" rel="noopener noreferrer">fuente original</a>' if source_url.startswith("https://") else "fuente original no disponible"
    if o.get("source_type") == "official_public_notice":
        return f'<p><strong>Último lote indicado: {o["y"]}/{o["n"]}</strong>. Aviso oficial de {source}, publicado {published}; comprobado {checked}. {link}. No confirma la disponibilidad individual.</p>'
    return f'<p><strong>Último lote: {o["y"]}/{o["n"]}</strong>. <strong>Dato no oficial</strong> de {source}, publicado {published}; comprobado {checked}. {link}. Confirma con la oficina.</p>'

def render(title, desc, relpath, h1, lead, preset="", info="", crumbs=None):
    title = title[:60]
    desc = desc[:155]
    page_url = DOMAIN + ("/" + relpath if relpath else "/")
    canonical = "" if IS_GITHUB_IO else f'<link rel="canonical" href="{esc(page_url, quote=True)}">'
    graph = [{
      "@type":"WebApplication","name":SITE,"url":DOMAIN + "/",
      "applicationCategory":"UtilitiesApplication","operatingSystem":"Any",
      "inLanguage":"es","isAccessibleForFree":True,
      "offers":{"@type":"Offer","price":"0","priceCurrency":"EUR"},
      "author":{"@type":"Person","name":BRAND}
    }]
    if crumbs:
        graph.append({"@type":"BreadcrumbList","itemListElement":[
          {"@type":"ListItem","position":i,"name":name,"item":url}
          for i,(name,url) in enumerate(crumbs,1)
        ]})
    breadcrumb_html = ""
    if crumbs:
        breadcrumb_html = '<nav aria-label="Migas de pan" class="hint">' + " › ".join(esc(x[0]) for x in crumbs) + "</nav>"
    values = {
      "TITLE":esc(title), "DESC":esc(desc), "URL":esc(page_url, quote=True),
      "H1":esc(h1), "LEAD":esc(lead), "PRESET":esc(preset, quote=True),
      "OGIMG":'<meta name="twitter:card" content="summary">',
      "JSONLD":json.dumps({"@context":"https://schema.org","@graph":graph},ensure_ascii=False).replace("</","<\\/"),
      "INFO":info, "BASE":BASE, "CANONICAL":canonical, "BREADCRUMBS":breadcrumb_html
    }
    result = tpl
    for key,value in values.items():
        result = result.replace("{{"+key+"}}",value)
    return result

def write(rel, content):
    target = OUT / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")

if OUT.exists():
    shutil.rmtree(OUT)
OUT.mkdir(parents=True)
urls = []
home_info = '<section class="info"><h2>Información</h2><p>Herramienta gratuita y sin publicidad. Las estimaciones son orientativas.</p></section>'
write("index.html",render(
 "Mi TIE Lista: consulta tu lote TIE",
 "Comprueba el último lote TIE publicado por oficina y consulta una estimación orientativa. Gratis y sin publicidad.",
 "", "¿Está lista tu TIE?", "Escribe el lote de tu resguardo de huellas y consulta el último dato disponible.", info=home_info))
urls.append(DOMAIN + "/")

province_names = PROVINCES + sorted(p for p in {o.get("prov","") for o in offices} if p and p not in PROVINCES)
for prov in province_names:
    rows = sorted((o for o in offices if o.get("prov") == prov),key=lambda o:o.get("name",""))
    parts_html = ['<section class="info"><h2>Oficinas y últimos lotes</h2><ul>']
    if rows:
        for o in rows:
            link = BASE + office_path(o)
            parts_html.append(f'<li><a href="{esc(link,quote=True)}">{esc(o.get("name","Oficina"))}</a>: {o["y"]}/{o["n"]}. ')
            if o.get("source_type") == "public_unofficial":
                parts_html.append(f'<strong>Dato no oficial</strong>, publicado {date_es(o.get("published"))} en {esc(o.get("source") or "fuente no identificada")}.</li>')
            else:
                parts_html.append('Aviso oficial; no confirma disponibilidad individual.</li>')
    else:
        parts_html.append(f'<li>No hay datos de lotes disponibles para {esc(prov)}. Esta ausencia no significa que no exista oficina o que no se entreguen tarjetas.</li>')
    parts_html.append(f'</ul><p>{official_link()}</p></section>')
    rel = province_path(prov)
    crumbs = [("Inicio",DOMAIN+"/"),("Provincias",DOMAIN+"/lote-tie/"),(prov,DOMAIN+"/"+rel)]
    title = f"Lotes TIE en {prov} | Mi TIE Lista"
    desc = f"Consulta oficinas y últimos lotes TIE disponibles en {prov}. Distingue datos no oficiales y accede a la sede oficial."
    write(rel+"index.html",render(title,desc,rel,f"Lotes TIE en {prov}",f"Oficinas y último lote conocido en {prov}.",info="".join(parts_html),crumbs=crumbs))
    urls.append(DOMAIN+"/"+rel)

for o in offices:
    rel = office_path(o)
    provrel = province_path(o["prov"])
    crumbs = [("Inicio",DOMAIN+"/"),(o["prov"],DOMAIN+"/"+provrel),(o["name"],DOMAIN+"/"+rel)]
    title = f"Lote TIE {o['name']} {o['prov']} | Mi TIE Lista"
    desc = f"Último lote TIE de {o['name']} ({o['prov']}): {o['y']}/{o['n']}. Consulta fuente y fecha."
    content = '<section class="info">'+office_info(o)+f'<p>{official_link()}</p></section>'
    write(rel+"index.html",render(title,desc,rel,f"Lote TIE en {o['name']}",f"Último dato disponible para {o['name']}, {o['prov']}.",o["id"],content,crumbs))
    urls.append(DOMAIN+"/"+rel)

if not IS_GITHUB_IO:
    write("CNAME",HOST+"\n")
for filename in ("favicon.svg","logo.svg","og.png","manifest.json","service-worker.js"):
    source = ROOT/filename
    if source.exists():
        shutil.copy2(source,OUT/filename)
write("lotes.json",json.dumps(data,ensure_ascii=False))
catalog_file = ROOT / "oficinas.json"
if catalog_file.exists():
    catalog = json.loads(catalog_file.read_text(encoding="utf-8"))
else:
    catalog = {"updated": None, "source_url": "", "offices": []}
write("oficinas.json", json.dumps(catalog, ensure_ascii=False))
write("sitemap.xml",'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'+"".join(
 f"<url><loc>{esc(url)}</loc><lastmod>{data.get('updated','')}</lastmod></url>\n" for url in urls)+"</urlset>\n")
write("robots.txt",f"User-agent: *\nAllow: /\n\nSitemap: {DOMAIN}/sitemap.xml\n")
print(f"{len(urls)} URLs en sitemap; {len(province_names)} provincias; DOMAIN={DOMAIN}; BASE={BASE}")

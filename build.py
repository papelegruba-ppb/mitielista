"""Genera el sitio estático SEO: build.py -> site/
Uso: python build.py   (lee lotes.json y template.html)
Cambia DOMAIN al comprar el dominio."""
import json, re, unicodedata, pathlib, html, shutil
DOMAIN = "https://mitielista.com"
BRAND = "Papelegruba"
SITE = "Mi TIE Lista"
ROOT = pathlib.Path(__file__).parent
OUT = ROOT / "site"
tpl = (ROOT / "template.html").read_text(encoding="utf-8")
data = json.loads((ROOT / "lotes.json").read_text(encoding="utf-8"))
offices = data["offices"]
FAQ = [
 ("¿Qué es el lote de la TIE?", "Es el número de tanda (año/número) que figura en el resguardo de la toma de huellas. La comisaría recibe las tarjetas por lotes y por orden."),
 ("¿Dónde encuentro mi lote?", "En el resguardo que te dan tras la toma de huellas, con el formato año/número, por ejemplo 2026/233. Al final del documento se indica también dónde recoger la tarjeta."),
 ("¿Cómo sé si mi TIE está lista?", "Compara tu lote con el último lote publicado por tu oficina. Si tu lote es igual o inferior, podría haber llegado el turno de tu tarjeta, pero la web no confirma que esté físicamente disponible. Confirma siempre con la oficina antes de desplazarte."),
 ("¿La fecha estimada es oficial?", "No. Se calcula con el ritmo reciente de avance de los lotes de cada oficina y es solo orientativa."),
]
esc = html.escape
def slug(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
def path(o): return f"/lote-tie/{slug(o['prov'])}/{slug(o['name'])}/"
def fdate(d): y, m, dd = d.split("-"); return f"{dd}/{m}/{y}"

def info(o=None):
    p = ['<section class="info">']
    if o:
        p.append(f'<h2>Último lote en {esc(o["name"])}</h2><p>El último lote publicado es el <b>{o["y"]}/{o["n"]}</b> (actualizado el {fdate(data["updated"])}). Si tu lote es igual o menor, puede que la tarjeta ya haya llegado; confirma con la oficina antes de desplazarte.</p>')
    if not offices:
        p.append("<p>En este momento no hay lotes de oficinas que se hayan podido verificar. No mostramos números de ejemplo ni estimaciones inventadas. Vuelve a consultar cuando se recuperen las fuentes.</p>")
    p.append("<h2>Preguntas frecuentes</h2>")
    p += [f"<details><summary>{esc(q)}</summary><p>{esc(a)}</p></details>" for q, a in FAQ]
    p.append("<h2>Último lote por oficina</h2><ul>" + "".join(f'<li><a href="{path(x)}">{esc(x["name"])}</a>: {x["y"]}/{x["n"]}</li>' for x in offices) + "</ul></section>")
    return "".join(p)

og = ('<meta property="og:image" content="%s/og.png">\n<meta name="twitter:card" content="summary_large_image">' % DOMAIN) if (ROOT / "og.png").exists() else '<meta name="twitter:card" content="summary">'

def render(title, desc, url, h1, lead, preset, inf):
    ld = {"@context": "https://schema.org", "@graph": [
        {"@type": "WebApplication", "name": SITE, "url": url, "applicationCategory": "UtilitiesApplication",
         "operatingSystem": "Any", "inLanguage": "es", "isAccessibleForFree": True,
         "offers": {"@type": "Offer", "price": "0", "priceCurrency": "EUR"}, "author": {"@type": "Person", "name": BRAND}},
        {"@type": "FAQPage", "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in FAQ]}]}
    vals = {"TITLE": esc(title), "DESC": esc(desc), "URL": url, "H1": esc(h1), "LEAD": esc(lead), "PRESET": preset,
            "OGIMG": og, "JSONLD": json.dumps(ld, ensure_ascii=False).replace("</", "<\\/"), "INFO": inf}
    out = tpl
    for k, v in vals.items(): out = out.replace("{{" + k + "}}", v)
    return out

def write(rel, content):
    f = OUT / rel.lstrip("/"); f.parent.mkdir(parents=True, exist_ok=True); f.write_text(content, encoding="utf-8")

if OUT.exists(): shutil.rmtree(OUT)
urls = [DOMAIN + "/"]
write("index.html", render("Mi TIE Lista: comprueba tu lote y cuándo recogerla",
    "Escribe tu lote y comprueba al instante si tu TIE está lista para recoger. Último lote publicado por oficina, fecha estimada y sin publicidad.",
    DOMAIN + "/", "¿Está lista tu TIE?", "Escribe el lote de tu resguardo de huellas y míralo al instante, sin pasos extra.", "", info()))
for o in offices:
    u = DOMAIN + path(o); urls.append(u)
    write(path(o) + "index.html", render((lambda t: t + (' | ' + SITE if len(t) <= 45 else ''))(f"Lote TIE {o['name']} hoy: {o['y']}/{o['n']}"),
        f"Último lote TIE publicado en {o['name']} ({o['prov']}): {o['y']}/{o['n']}, actualizado el {fdate(data['updated'])}. Comprueba si tu tarjeta está lista y la fecha estimada.",
        u, f"Lote TIE en {o['name']}", f"Último lote publicado: {o['y']}/{o['n']}. Escribe el tuyo y comprueba si tu TIE está lista.", o["id"], info(o)))
write("sitemap.xml", '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' +
      "".join(f"<url><loc>{u}</loc><lastmod>{data['updated']}</lastmod></url>\n" for u in urls) + "</urlset>\n")
write("robots.txt", f"User-agent: *\nAllow: /\n\nSitemap: {DOMAIN}/sitemap.xml\n")
write("CNAME", DOMAIN.split("//")[1] + "\n")
for f in ("favicon.svg", "logo.svg", "og.png"):
    if (ROOT / f).exists(): shutil.copy(ROOT / f, OUT / f)
write("lotes.json", json.dumps(data, ensure_ascii=False))
print(len(urls), "URLs en el sitemap")

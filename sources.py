"""Adaptadores conservadores para fuentes adicionales de lotes TIE.

Solo devuelve observaciones cuando el HTML contiene un patrón explícito de lote.
No elude CAPTCHA, autenticación ni controles anti-bot. Los errores se aíslan por fuente.
"""
from __future__ import annotations

import datetime as dt
import html
import re
import unicodedata
import urllib.error
import urllib.request
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

SOURCES = [
    {"id": "icpplus", "name": "ICP+ / Cita previa", "official": True,
     "method": "icpplus", "url": "https://sede.administracionespublicas.gob.es/pagina/index/directorio/icpplus",
     "reliability": "high", "enabled": False,
     "notes": "Fuente primaria; la navegación actual se gestiona en scrape.py. Puede requerir interacción humana."},
    {"id": "mpt_melilla", "name": "Delegación del Gobierno en Melilla", "official": True,
     "method": "html", "url": "https://mptmd.gob.es/portal/delegaciones_gobierno/delegaciones/melilla/proyectos-ci/tabl-n-anuncios-extranjer-a/lotes-de-tarjetas-de-identidad-de-extranjeros-disponibles-en-la-oficina",
     "reliability": "high", "enabled": True,
     "notes": "Aviso oficial específico de Melilla; distinguir categorías de tarjeta y fecha del aviso."},
    {"id": "extranjeria_murcia", "name": "Extranjería Murcia", "official": False,
     "method": "html", "url": "https://www.extranjeriamurcia.com/lotes-recibidos",
     "reliability": "medium", "enabled": True,
     "notes": "Fuente secundaria no oficial; no asumir que sus datos equivalen a una confirmación individual."},
    {"id": "sclt", "name": "SCLT", "official": False, "method": "html",
     "url": "https://sclt.es/en/tie/consultar/", "reliability": "low", "enabled": True,
     "notes": "Portal secundario; se extraen solo lotes con formato inequívoco."},
    {"id": "form24", "name": "Form24", "official": False, "method": "html",
     "url": "https://form24.es/lote/select", "reliability": "low", "enabled": True,
     "notes": "Señal secundaria; no usar como única fuente ni asumir cobertura por provincia."},
    {"id": "policia_catalogo", "name": "Catálogo de ubicaciones de Policía Nacional",
     "official": True, "method": "csv",
     "url": "https://www.policia.es/miscelanea/catalogo_datos/PN_ubicaciones_EXTRANJERIA.csv",
     "reliability": "high", "enabled": False,
     "notes": "Catálogo de oficinas, no una fuente de números de lote."},
]

HEADERS = {"User-Agent": "MiTIELista/1.0 (+https://github.com/papelegruba-ppb/mitielista)"}
TIMEOUT = 18
MAX_BYTES = 2_000_000


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.links = []
        self._a = None
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("script", "style", "noscript", "svg"):
            self._skip += 1
        if tag == "a" and attrs.get("href"):
            self._a = [attrs["href"], []]
        if tag in ("br", "p", "div", "section", "article", "h1", "h2", "h3", "li", "tr"):
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg") and self._skip:
            self._skip -= 1
        if tag == "a" and self._a:
            self.links.append((self._a[0], "".join(self._a[1]).strip()))
            self._a = None
        if tag in ("p", "div", "section", "article", "h1", "h2", "h3", "li", "tr"):
            self.parts.append(" ")

    def handle_data(self, data):
        if self._skip:
            return
        self.parts.append(data)
        if self._a:
            self._a[1].append(data)

    @property
    def text(self):
        return re.sub(r"\s+", " ", html.unescape(" ".join(self.parts))).strip()


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def parse_lot(value: str):
    """Parsea solo formatos explícitos YYYY/NNN o NNN/YYYY; nunca deduce el año actual."""
    value = str(value).strip()
    m = re.search(r"(?<!\d)(20\d{2})\s*/\s*(\d{1,5})(?!\d)", value)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"(?<!\d)(\d{1,5})\s*/\s*(20\d{2})(?!\d)", value)
    if m:
        return int(m.group(2)), int(m.group(1))
    return None


def parse_date(value: str):
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(value.strip(), fmt).date().isoformat()
        except (ValueError, AttributeError):
            pass
    return None


def _fetch(url: str):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status}")
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise RuntimeError("respuesta demasiado grande; se omite por seguridad")
    parser = _Text()
    parser.feed(raw.decode("utf-8", "replace"))
    return parser


def _office_guess(text: str, fallback: str):
    patterns = [
        r"(?:oficina|comisar[ií]a)(?: de polic[ií]a)?(?: de extranjer[ií]a)?\s+([^.;]{2,90})",
        r"(?:polic[ií]a nacional)\s+[-–:]\s*([^.;]{2,90})",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.I)
        if m:
            name = re.sub(r"\s+", " ", m.group(1)).strip(" :-–")
            if name and len(name) <= 90:
                return name
    return fallback


def _record(source, province, office, year, number, published, source_url, raw_text, card_type="otros"):
    checked = dt.datetime.now(dt.timezone.utc).isoformat()
    prov = province.strip()
    name = office.strip()
    # El ID conserva la forma compatible con el sitio actual, normalizando variaciones comunes.
    ident = re.sub(r"[^a-z0-9]+", "-", normalize(prov + " " + name)).strip("-")[:48]
    return {
        "id": ident, "prov": prov, "name": name, "y": int(year), "n": int(number),
        "checked": checked[:10], "published": published, "source": source["name"],
        "source_url": source_url, "source_type": "public_unofficial" if not source["official"] else "official_public_notice",
        "source_checked": checked, "card_type": card_type, "raw_text": raw_text[:500],
        "confidence": source["reliability"],
    }


def _parse_murcia(source, parser):
    # Solo aceptar líneas con oficina y lote/año explícitos.
    out = []
    for chunk in re.split(r"(?<=[.;])\s+|\s{2,}", parser.text):
        m = re.search(r"(?P<office>(?:OFICINA|COMISAR[IÍ]A)[^:;]{2,100})\s*[:\-–]?\s*(?:HASTA\s*)?LOTE\s*(?:NIE\s*)?(?:ACTUAL\s*)?(?:[:#Nº ]+)?(?P<lot>20\d{2}\s*/\s*\d{1,5}|\d{1,5}\s*/\s*20\d{2})", chunk, re.I)
        if not m:
            continue
        lot = parse_lot(m.group("lot"))
        if not lot:
            continue
        office = re.sub(r"\s+", " ", m.group("office")).strip(" :-–")
        published = None
        dm = re.search(r"(?:actualizad[oa]|fecha)\s*[: ]\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})", chunk, re.I)
        if dm:
            published = parse_date(dm.group(1))
        out.append(_record(source, "Murcia", office, *lot, published, source["url"], chunk))
    return out


def _parse_explicit_page(source, url, parser, province_hint=None):
    text = parser.text
    # No se interpreta un número aislado como lote: se exige etiqueta de lote + año/número.
    lot_patterns = [
        re.compile(r"(?:lote|lot)\s*(?:actual|recibido|disponible)?\s*[:#]?\s*(20\d{2}\s*/\s*\d{1,5}|\d{1,5}\s*/\s*20\d{2})", re.I),
        re.compile(r"(?:último lote recibido|ultimo lote recibido)[^0-9]{0,80}(20\d{2}\s*/\s*\d{1,5}|\d{1,5}\s*/\s*20\d{2})", re.I),
    ]
    matches = []
    for pattern in lot_patterns:
        matches.extend(pattern.finditer(text))
    if not matches:
        return []
    province = province_hint or ("Melilla" if "melilla" in url.lower() else "")
    if not province:
        return []
    published = None
    dm = re.search(r"(?:publicado|actualizado|fecha del aviso|fecha)\s*[: ]\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})", text, re.I)
    if dm:
        published = parse_date(dm.group(1))
    # A page may mention several card categories; do not merge category-specific lots.
    card_type = "fronterizos" if re.search(r"fronteriz", text, re.I) else "residencia_comunitario"
    office = _office_guess(text, "Oficina de expedición de TIE")
    out = []
    seen = set()
    for m in matches:
        lot = parse_lot(m.group(1))
        if not lot or (lot, card_type) in seen:
            continue
        seen.add((lot, card_type))
        out.append(_record(source, province, office, *lot, published, url, m.group(0), card_type))
    return out


def scrape_secondary_sources():
    """Consulta fuentes públicas de baja frecuencia; cada fallo queda aislado."""
    today = dt.date.today().isoformat()
    found = []
    by_id = {s["id"]: s for s in SOURCES}
    # Melilla es el único aviso oficial provincial confirmado en el catálogo actual.
    source = by_id["mpt_melilla"]
    try:
        parser = _fetch(source["url"])
        found.extend(_parse_explicit_page(source, source["url"], parser, "Melilla"))
        print(f"[fuente:{source['id']}] {len(found)} observaciones explícitas")
    except Exception as exc:
        print(f"[fuente:{source['id']}] no disponible: {exc}")

    source = by_id["extranjeria_murcia"]
    try:
        parser = _fetch(source["url"])
        records = _parse_murcia(source, parser)
        found.extend(records)
        print(f"[fuente:{source['id']}] {len(records)} observaciones explícitas")
    except Exception as exc:
        print(f"[fuente:{source['id']}] no disponible: {exc}")

    # SCLT y Form24 se consultan como señales secundarias. Solo se aceptan lotes
    # explícitos con año; no se convierten estimaciones ni números aislados en datos.
    for source_id, province_hint in (("sclt", None), ("form24", None)):
        source = by_id[source_id]
        try:
            parser = _fetch(source["url"])
            records = _parse_explicit_page(source, source["url"], parser, province_hint)
            found.extend(records)
            print(f"[fuente:{source_id}] {len(records)} observaciones explícitas en página de entrada")
        except Exception as exc:
            print(f"[fuente:{source_id}] no disponible: {exc}")

    # No afirmar frescura si la página no declara una fecha de publicación.
    # El timestamp checked solo expresa cuándo se consultó la fuente.
    unique = {}
    for item in found:
        key = (item["id"], item["source"], item["card_type"], item["y"], item["n"])
        old = unique.get(key)
        if old is None or (item.get("published") or "") > (old.get("published") or ""):
            unique[key] = item
    return list(unique.values())

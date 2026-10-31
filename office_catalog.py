"""Catálogo automático de oficinas TIE desde el directorio accesible de Policía Nacional."""
from __future__ import annotations
import datetime as dt
import json
import pathlib
import re
import unicodedata
import urllib.request
from html.parser import HTMLParser

ROOT = pathlib.Path(__file__).parent
URL = "https://sede.policia.gob.es/portalCiudadano/_es/dependencias_localizador_accesible.php"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MiTIELista/1.0; +https://github.com/papelegruba-ppb/mitielista)"}
PROVINCES = [
"A Coruña","Albacete","Alicante","Almería","Araba/Álava","Asturias","Ávila","Badajoz",
"Balears (Illes)","Barcelona","Burgos","Cáceres","Cádiz","Cantabria","Castellón","Ceuta",
"Ciudad Real","Córdoba","Cuenca","Girona","Granada","Guadalajara","Guipúzcoa / Gipuzkoa",
"Huelva","Huesca","Jaén","La Rioja","Las Palmas","León","Lleida","Lugo","Madrid","Málaga",
"Melilla","Murcia","Navarra","Ourense","Palencia","Pontevedra","Salamanca",
"Santa Cruz de Tenerife","Segovia","Sevilla","Soria","Tarragona","Teruel","Toledo",
"Valencia","Valladolid","Vizcaya / Bizkaia","Zamora","Zaragoza"]

def norm(value):
    value = unicodedata.normalize("NFKD", str(value)).encode("ascii","ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+"," ",value).strip()

ALIASES = {norm(p):p for p in PROVINCES}
ALIASES.update({"alava":"Araba/Álava","araba":"Araba/Álava","baleares":"Balears (Illes)",
"illes balears":"Balears (Illes)","guipuzcoa":"Guipúzcoa / Gipuzkoa","gipuzkoa":"Guipúzcoa / Gipuzkoa",
"vizcaya":"Vizcaya / Bizkaia","bizkaia":"Vizcaya / Bizkaia","la coruna":"A Coruña",
"coruna":"A Coruña","tenerife":"Santa Cruz de Tenerife"})

class DirectoryParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.heading_tag = None
        self.heading = []
        self.current_province = None
        self.current = None
        self.offices = []
        self.lines = []
    def handle_starttag(self, tag, attrs):
        if re.fullmatch(r"h[1-6]",tag):
            self.heading_tag, self.heading = tag, []
        if tag in ("br","p","li","div","section","article","dt","dd"):
            self.current["text"] += "\n"
    def handle_endtag(self, tag):
        if self.heading_tag == tag:
            title = re.sub(r"\s+"," "," ".join(self.heading)).strip()
            self._heading(title)
            self.heading_tag = None
        if tag in ("br","p","li","div","section","article","dt","dd"):
            self.current["text"] += "\n"
    def handle_data(self, data):
        if self.heading_tag:
            self.heading.append(data)
        elif self.current:
            self.current["text"] += data
    def _save(self):
        if self.current:
            self.offices.append(self.current)
            self.current = None
    def _heading(self,title):
        m = re.search(r"Oficinas de trámites de extranjería en\s+(.+)$",title,re.I)
        if m:
            self._save()
            self.current_province = ALIASES.get(norm(m.group(1)))
            return
        if re.match(r"Volver a |Dependencias policiales|Oficinas de trámites",title,re.I):
            return
        if self.current_province and title:
            self._save()
            self.current={"prov":self.current_province,"name":title,"text":""}
    def close(self):
        super().close()
        self._save()

def parse_directory(html):
    parser=DirectoryParser()
    parser.feed(html)
    records=[]
    checked=dt.datetime.now(dt.timezone.utc).isoformat()
    for item in parser.offices:
        text=item["text"]
        # Solo oficinas con un servicio TIE explícito en el propio directorio oficial.
        if not re.search(r"expedici[oó]n\s*(?:de\s*)?TIE|expedici[oó]n\s+de\s+tarjeta|recogida\s+de\s+tarjeta\s+de\s+identidad\s+de\s+extranjero|toma\s+de\s+huellas\s*\(\s*expedici[oó]n\s+de\s+tarjeta",text,re.I):
            continue
        def field(label):
            m=re.search(label+r"\s*\n\s*([^\n]+)",text,re.I)
            return re.sub(r"\s+"," ",m.group(1)).strip() if m else ""
        services=[]
        for line in text.splitlines():
            line=re.sub(r"\s+"," ",line).strip()
            if line and re.search(r"expedici[oó]n.*TIE|tarjeta de identidad de extranjero|toma de huellas|tarjetas de residencia",line,re.I):
                if line not in services: services.append(line)
        ident=re.sub(r"[^a-z0-9]+","-",norm(item["prov"]+" "+item["name"])).strip("-")[:64]
        records.append({"id":ident,"prov":item["prov"],"name":item["name"],
            "address":field("Direcci[oó]n"),"phone":field("Tel[eé]fono"),
            "services":services,"source":"Policía Nacional","source_url":URL,
            "checked":checked,"official":True})
    unique={x["id"]:x for x in records}
    return sorted(unique.values(),key=lambda x:(x["prov"],x["name"]))

def main():
    req=urllib.request.Request(URL,headers=HEADERS)
    with urllib.request.urlopen(req,timeout=30) as response:
        raw=response.read(8_000_001)
    if len(raw)>8_000_000: raise RuntimeError("Directorio demasiado grande; se conserva el catálogo anterior")
    html=raw.decode("utf-8","replace")
    records=parse_directory(html)
    if len(records)<20:
        raise RuntimeError(f"El directorio devolvió solo {len(records)} oficinas TIE; no se sobrescribe el catálogo anterior")
    payload={"updated":dt.date.today().isoformat(),"source_url":URL,"offices":records}
    (ROOT/"oficinas.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"Catálogo oficial actualizado: {len(records)} oficinas con servicios TIE explícitos en {len({x['prov'] for x in records})} provincias")

if __name__=="__main__": main()

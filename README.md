# Mi TIE Lista

Aplicación para consultar lotes de TIE publicados por oficina. Un lote es un indicador general de una remesa, **no confirma que una tarjeta individual esté físicamente disponible**.

## Fuentes y fiabilidad

- **ICP+ / Cita previa:** fuente primaria oficial. El scraper actual intenta consultarla, pero el flujo puede fallar por disponibilidad, navegación o controles de acceso. No se eluden CAPTCHAs ni autenticación.
- **Avisos oficiales del Portal MPT:** el adaptador comienza por el aviso específico de Melilla. Solo publica observaciones si encuentra un patrón de lote explícito; la cobertura oficial no se extrapola a otras provincias.
- **Extranjería Murcia:** fuente secundaria no oficial. Los datos se identifican como no oficiales.
- **SCLT y Form24:** fuentes secundarias no oficiales. El adaptador solo acepta lotes con año explícito en las páginas de entrada; si no encuentra un patrón inequívoco, no publica registros.
- **Portal Extranjería:** fuente secundaria no oficial que ya procesa `scrape.py`.
- **Catálogo CSV de Policía Nacional:** catálogo de oficinas; no se utiliza como fuente de números de lote.

Registro de fuentes y adaptadores: [sources.py](sources.py).

## Datos y trazabilidad

Cada observación visible conserva, cuando la fuente lo proporciona, el nombre de la fuente, la URL original, la fecha de publicación y la fecha de comprobación. La fecha de comprobación no es la fecha de publicación. Si no existe fecha publicada verificable, se muestra como no confirmada.

No se marca una provincia como cubierta solo porque exista una página general. La cobertura depende de observaciones reales. El modelo del frontend actual mantiene un registro vigente por oficina; las fuentes secundarias no reemplazan automáticamente registros existentes. La normalización y el parser de lotes están preparados para formatos explícitos, pero el proyecto todavía no dispone de una base histórica relacional separada por fuente y categoría.

## Desarrollo y pruebas

Requisitos: Python 3.12. El scraping de ICP+ usa Playwright/Chromium.

```bash
python -m unittest discover -s tests -v
pip install playwright
playwright install chromium
python scrape.py
python build.py
```

Los adaptadores de fuentes son deliberadamente conservadores: no deducen el año actual a partir de un número aislado, no inventan oficinas ni lotes y no intentan eludir controles de acceso. Un fallo de una fuente no debe impedir consultar las demás.

## Limitaciones conocidas

- La sede ICP+ puede no ser accesible desde el entorno de automatización; el estado de error debe distinguirse de “no hay lote publicado”.
- Las páginas de SCLT y Form24 pueden contener estimaciones u otros indicadores; no se consideran oficiales.
- La página oficial de Melilla puede incluir categorías de tarjeta distintas. Un aviso de lote no demuestra disponibilidad individual.
- La estructura de los sitios externos puede cambiar. Los adaptadores registran fallos y solo generan datos al reconocer un patrón explícito.

import asyncio, time, urllib.request
from playwright.async_api import async_playwright
import scrape as S

BAD = ("captcha", "robot", "access denied", "request rejected",
       "acceso denegado", "too many requests")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

async def probe(ctx, prov):
    page = await ctx.new_page()
    page.set_default_timeout(30000)
    nav = []
    page.on("response", lambda r: nav.append((r.status, r.url[:90]))
            if r.request.is_navigation_request() else None)
    t = time.time()
    try:
        await S.open_province(page, prov)
        print(f"[{prov}] provincia OK en {time.time()-t:.1f}s")
        opts = [((await o.get_attribute("value")) or "", ((await o.text_content()) or "").strip())
                for o in await page.locator("select").first.locator("option").all()]
        offices = [(v, n) for v, n in opts if v.strip() and not n.upper().startswith("SELEC")]
        print(f"[{prov}] oficinas: {len(offices)}")
        if offices:
            v, name = offices[0]
            t = time.time()
            y, n = await S.read_lote(page, prov, v)
            print(f"[{prov}] {name}: {y}/{n} en {time.time()-t:.1f}s")
    except Exception as e:
        print(f"[{prov}] FALLO {type(e).__name__}: {str(e)[:300]}")
        body = ""
        try: body = (await page.inner_text("body"))[:500]
        except Exception: pass
        print(f"[{prov}] body: {body!r}")
        print(f"[{prov}] señales anti-bot: {[b for b in BAD if b in body.lower()]}")
        await S.snap(page, S.slug(prov) + "-diag")
    print(f"[{prov}] navegaciones: {nav[-6:]}")
    await page.close()

async def main():
    try:
        print("IP del runner:", urllib.request.urlopen("https://api.ipify.org", timeout=10).read().decode())
    except Exception as e:
        print("IP no disponible:", e)
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        ctx = await b.new_context(locale="es-ES", timezone_id="Europe/Madrid", user_agent=UA)
        for prov in ("Zaragoza", "Madrid", "Barcelona"):
            try:
                await asyncio.wait_for(probe(ctx, prov), timeout=150)
            except asyncio.TimeoutError:
                print(f"[{prov}] TIMEOUT 150s")
        await b.close()

asyncio.run(main())

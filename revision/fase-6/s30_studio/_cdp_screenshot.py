"""Smoke s30: captura la pestana Render con el dropdown de presets expandido (CDP).

Script de evidencia de sesion — no es parte del pipeline. Requiere Edge headless
con --remote-debugging-port=9223 y el Studio en :8787.
"""

import asyncio
import base64
import json
import urllib.request

import websockets

JS = """
showTab('render', document.querySelectorAll('nav button')[2]);
const sel = document.getElementById('render-preset');
sel.value = 'karaoke_highlight';
onPresetChange();
sel.size = sel.options.length;      // expande: se ven TODAS las opciones pobladas
const isel = document.getElementById('render-intensidad');
isel.size = isel.options.length;
sel.options.length + '|' + isel.options.length;
"""


async def main() -> None:
    tabs = json.loads(urllib.request.urlopen("http://localhost:9223/json").read())
    page = next(t for t in tabs if t["type"] == "page")
    async with websockets.connect(page["webSocketDebuggerUrl"], max_size=2**25) as ws:
        mid = 0

        async def cmd(method: str, **params):
            nonlocal mid
            mid += 1
            await ws.send(json.dumps({"id": mid, "method": method, "params": params}))
            while True:
                msg = json.loads(await ws.recv())
                if msg.get("id") == mid:
                    return msg.get("result", {})

        await cmd("Page.enable")
        await cmd("Page.navigate", url="http://localhost:8787/")
        await asyncio.sleep(4)  # carga + fetch de /api/presets
        r = await cmd("Runtime.evaluate", expression=JS, returnByValue=True)
        print("opciones preset|intensidad:", r.get("result", {}).get("value"))
        await asyncio.sleep(1)
        shot = await cmd("Page.captureScreenshot", format="png")
        out = "revision/fase-6/s30_studio/studio_dropdown_presets.png"
        with open(out, "wb") as f:
            f.write(base64.b64decode(shot["data"]))
        print("guardado:", out)


asyncio.run(main())

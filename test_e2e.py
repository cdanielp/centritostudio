"""Prueba E2E: transcribe reel02 via API, corrige confiwai->ComfyUI, renderiza, extrae frame."""
import requests, json, time, sys, subprocess
from pathlib import Path

BASE = "http://localhost:8787"

def poll_job(jid, timeout=120):
    for _ in range(timeout):
        j = requests.get(f"{BASE}/api/jobs/{jid}").json()
        pct = j["progress"]
        msg = j["message"]
        print(f"  [{pct}%] {msg}")
        if j["status"] in ("done", "error"):
            return j
        time.sleep(1.5)
    return {"status": "timeout"}

print("=== E2E Test 1: reel02 — transcribir, editar, renderizar ===\n")

# 1. Transcribir
print("[1] Transcribiendo reel02 con modelo auto...")
r = requests.post(f"{BASE}/api/videos/reel02/transcribe", params={"lang": "es", "model": "auto"})
if r.status_code != 200:
    print(f"ERROR: {r.status_code} {r.text}")
    sys.exit(1)
jid = r.json()["job_id"]
j = poll_job(jid)
if j["status"] != "done":
    print(f"ERROR en transcripcion: {j}")
    sys.exit(1)
print(f"OK — {j['message']}\n")

# 2. Ver grupos
groups = requests.get(f"{BASE}/api/videos/reel02/transcript").json()
print(f"[2] Grupos transcriptos ({len(groups)}):")
for g in groups:
    print(f"  [{g['id']}] {g['text']}")
print()

# 3. Editar: confiwai -> ComfyUI
print("[3] Editando 'confiwai' -> 'ComfyUI'...")
edited = 0
for g in groups:
    low = g["text"].lower()
    if "confiwai" in low:
        g["text"] = low.replace("confiwai", "ComfyUI")
        g["edited"] = True
        edited += 1
        print(f"  Grupo {g['id']} editado: {g['text']}")

if edited == 0:
    print("  AVISO: 'confiwai' no encontrado en grupos — puede estar ya corregido")

r2 = requests.put(
    f"{BASE}/api/videos/reel02/transcript",
    json=groups,
    headers={"Content-Type": "application/json"},
)
print(f"  Guardado: {r2.json()}\n")

# 4. Verificar grupos post-edicion
groups_check = requests.get(f"{BASE}/api/videos/reel02/transcript").json()
print("[4] Verificacion post-edicion:")
for g in groups_check:
    print(f"  [{g['id']}] {g['text']}")
print()

# 5. Renderizar en hormozi
print("[5] Renderizando en estilo hormozi...")
r3 = requests.post(f"{BASE}/api/videos/reel02/render", params={"style": "hormozi"})
if r3.status_code != 200:
    print(f"ERROR render: {r3.status_code} {r3.text}")
    sys.exit(1)
jid2 = r3.json()["job_id"]
j2 = poll_job(jid2)
if j2["status"] != "done":
    print(f"ERROR render: {j2}")
    sys.exit(1)
print(f"OK — {j2['message']}\n")

# 6. Extraer frame para verificar que "ComfyUI" quedo quemado
output = Path("output/reel02_hormozi.mp4")
frame  = Path("revision/e2e_reel02_comfyui.png")
print("[6] Extrayendo frame de verificacion...")
subprocess.run(
    ["ffmpeg", "-y", "-i", str(output), "-ss", "4.5", "-vframes", "1", str(frame)],
    capture_output=True,
)
if frame.exists():
    print(f"  Frame guardado: {frame}")
else:
    print("  ERROR: frame no generado")

print("\n=== E2E Test 1 COMPLETADO ===")

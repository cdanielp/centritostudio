"""Crea/limpia evidencia sintetica S37-C sin red, GPU ni datos reales."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ID = "test_s37c_demo_v2_20260718-1200"
PACKAGE_DIR = ROOT / "output" / "paquetes" / PACKAGE_ID
TRANSCRIPTS = ROOT / "transcripts"
CLIP_NAME = "test_s37c_clip1_9x16_hormozi.mp4"
RESOLVED_NAME = "test_s37c_clip1_9x16_broll_resolved.json"
FINGERPRINT = hashlib.sha256(b"test_s37c_fixture_v1").hexdigest()


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _crear_mp4(path: Path) -> None:
    comando = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        "color=c=0x17152b:size=216x384:rate=30",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=330:sample_rate=44100",
        "-t",
        "12",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "30",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        "-movflags",
        "+faststart",
        str(path),
    ]
    subprocess.run(comando, cwd=ROOT, check=True)


def _decisions() -> list[dict]:
    return [
        {
            "window_id": "broll-0001",
            "requested_media_type": "image",
            "final_media_type": "image",
            "query": "taller de cafe sintetico",
            "start_s": 3.2,
            "end_s": 5.2,
            "status": "resolved",
            "code": "resolved_image",
            "message": "fixture sintetico",
            "asset": None,
            "steps": [],
        },
        {
            "window_id": "broll-0002",
            "requested_media_type": "video",
            "final_media_type": "video",
            "query": "maquina en movimiento sintetica",
            "start_s": 6.0,
            "end_s": 8.0,
            "status": "resolved",
            "code": "resolved_video",
            "message": "fixture sintetico",
            "asset": None,
            "steps": [],
        },
        {
            "window_id": "broll-0003",
            "requested_media_type": "video",
            "final_media_type": "image",
            "query": "granos de cafe fallback sintetico",
            "start_s": 9.0,
            "end_s": 11.0,
            "status": "fallback",
            "code": "video_no_cover_fallback_image",
            "message": "fixture sintetico",
            "asset": None,
            "steps": ["video_no_cover_fallback_image"],
        },
    ]


def _clip() -> dict:
    return {
        "archivo": CLIP_NAME,
        "titulo": "Demo sintética Auto v2",
        "razon": "Fixture local para revisión visual de K",
        "score": 92,
        "dur_s": 12.0,
        "avisos": [],
        "qa": {"n_alertas": 0, "aplicadas": 0, "pendientes": 0},
        "emojis_msg": "1 overlay(s)",
        "pipeline_mode": "v2",
        "pipeline_version": 2,
        "config_fingerprint": FINGERPRINT,
        "brain_ok": True,
        "broll": {
            "planned": 3,
            "resolved": 3,
            "images": 2,
            "videos": 1,
            "fallbacks": 1,
            "blocked": 0,
            "omitted": 0,
            "manual_popups": 1,
            "manual_clips": 0,
            "plan_sidecar": "test_s37c_clip1_9x16_broll_plan.json",
            "auto_sidecar": "test_s37c_clip1_9x16_popups.auto.json",
            "resolved_sidecar": RESOLVED_NAME,
        },
        "fx": {
            "enabled": True,
            "preset": "express",
            "before": {"punch": 2, "flash": 1, "scanner": 0, "logo": 0},
            "after": {"punch": 1, "flash": 1, "scanner": 0, "logo": 0},
            "removed": [{"code": "punch_removed_cutaway", "t0": 3.4, "t1": 4.0}],
            "warnings": [],
        },
        "av": {
            "integrity": {"status": "pass", "packet_count_source": 518, "packet_count_output": 518},
            "sync": {
                "status": "pass",
                "audio_start_delta_s": 0.0,
                "audio_duration_delta_s": 0.0,
                "av_start_delta_s": 0.0,
                "av_end_drift_s": 0.031,
                "allowed_end_drift_s": 0.12,
            },
        },
    }


def create() -> None:
    if PACKAGE_DIR.exists() or (TRANSCRIPTS / RESOLVED_NAME).exists():
        raise SystemExit("Fixture ya existe. Ejecuta --clean antes de recrearlo.")
    PACKAGE_DIR.mkdir(parents=True)
    TRANSCRIPTS.mkdir(parents=True, exist_ok=True)
    _crear_mp4(PACKAGE_DIR / CLIP_NAME)
    meta = {
        "fecha": "20260718-1200",
        "objetivo": "clips",
        "pipeline_mode": "v2",
        "config_fingerprint": FINGERPRINT,
        "config": {
            "mode": "v2",
            "broll_enabled": True,
            "fx_enabled": True,
            "fx_preset": "express",
            "verify_av": True,
            "manual_sidecars": True,
        },
        "t_total_s": 12.0,
        "costo_usd": 0.0,
    }
    _write_json(PACKAGE_DIR / "paquete.json", {"clips": [_clip()], "meta": meta})
    (PACKAGE_DIR / "REPORTE.md").write_text(
        "# Fixture sintético S37-C\n\n"
        "AUTO V2 · B-roll 3/3 · FX 1 eliminado · Audio PASS · Sync PASS.\n",
        encoding="utf-8",
    )
    resolved = {
        "version": 1,
        "planner_version": 1,
        "mode": "v2",
        "config_fingerprint": FINGERPRINT,
        "clip": {"duration_s": 12.0, "width": 216, "height": 384, "fps": 30.0},
        "requested_windows": 3,
        "resolved": 2,
        "fallbacks": 1,
        "blocked": 0,
        "omitted": 0,
        "final": {"images": 2, "videos": 1, "coverage_s": 6.0, "coverage_pct": 0.5},
        "decisions": _decisions(),
    }
    _write_json(TRANSCRIPTS / RESOLVED_NAME, resolved)
    print(f"Fixture creado: {PACKAGE_ID}")


def clean() -> None:
    if PACKAGE_DIR.exists():
        shutil.rmtree(PACKAGE_DIR)
    sidecar = TRANSCRIPTS / RESOLVED_NAME
    if sidecar.exists():
        sidecar.unlink()
    print(f"Fixture limpiado: {PACKAGE_ID}")


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--create", action="store_true")
    group.add_argument("--clean", action="store_true")
    args = parser.parse_args()
    create() if args.create else clean()


if __name__ == "__main__":
    main()

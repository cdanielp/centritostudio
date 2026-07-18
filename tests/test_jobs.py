"""Adaptador de jobs para classic/v2; auto.ejecutar_auto sigue siendo el orquestador."""

import inspect

import pytest

import auto
import auto_av
import jobs
from auto_config import AutoConfig


@pytest.fixture
def registro(monkeypatch):
    updates = []
    monkeypatch.setattr(jobs, "update_job", lambda jid, **kw: updates.append((jid, kw)))
    return updates


@pytest.mark.parametrize("config", [None, AutoConfig(mode="v2", fx_preset="pro")])
def test_run_auto_pasa_config_y_conserva_resultado(monkeypatch, registro, tmp_path, config):
    esperado = {"clips": [{"pipeline_mode": "v2"}], "resumen": "completo", "meta": {"x": 1}}
    llamada = {}

    def fake(*args, **kwargs):
        llamada.update({"args": args, "kwargs": kwargs})
        kwargs["progress"](47, "progreso real")
        return esperado

    monkeypatch.setattr(auto, "ejecutar_auto", fake)
    jobs.run_auto("j1", tmp_path / "v.mp4", "v", config=config)
    assert llamada["kwargs"]["config"] is config
    assert llamada["kwargs"]["objetivo"] == "clips"
    assert any(u[1].get("progress") == 47 for u in registro)
    assert registro[-1][1]["status"] == "done" and registro[-1][1]["result"] is esperado


def test_llamada_historica_compatible(monkeypatch, registro, tmp_path):
    monkeypatch.setattr(auto, "ejecutar_auto", lambda *a, **k: {"clips": [], "resumen": "ok"})
    jobs.run_auto("j", tmp_path / "v.mp4", "v")
    assert "clasico" in registro[0][1]["message"]


@pytest.mark.parametrize(
    "error", [auto_av.AudioIntegrityError("audio"), auto_av.AVSyncError("sync"), RuntimeError("x")]
)
def test_excepciones_terminan_job_en_error(monkeypatch, registro, tmp_path, error):
    monkeypatch.setattr(auto, "ejecutar_auto", lambda *a, **k: (_ for _ in ()).throw(error))
    jobs.run_auto("j", tmp_path / "v.mp4", "v", config=AutoConfig(mode="v2"))
    assert registro[-1][1]["status"] == "error"
    assert registro[-1][1]["error"] != str(error)
    assert not any(u[1].get("status") == "done" for u in registro)


def test_error_worker_no_expone_secretos_ni_rutas(monkeypatch, registro, tmp_path):
    privado = r"C:\\privado\\video.mp4 PEXELS_API_KEY=secreto"
    monkeypatch.setattr(
        auto, "ejecutar_auto", lambda *a, **k: (_ for _ in ()).throw(RuntimeError(privado))
    )
    jobs.run_auto("j", tmp_path / "v.mp4", "v", config=AutoConfig(mode="v2"))
    publico = registro[-1][1]
    assert privado not in publico["message"] and "secreto" not in publico["error"]


def test_system_exit_no_es_capturado(monkeypatch, registro, tmp_path):
    monkeypatch.setattr(auto, "ejecutar_auto", lambda *a, **k: (_ for _ in ()).throw(SystemExit(2)))
    with pytest.raises(SystemExit):
        jobs.run_auto("j", tmp_path / "v.mp4", "v")
    assert not any(u[1].get("status") == "error" for u in registro)


def test_jobs_no_importa_auto_v2_ni_reconstruye_config():
    source = inspect.getsource(jobs.run_auto)
    assert "auto_v2" not in source and "AutoConfig(" not in source

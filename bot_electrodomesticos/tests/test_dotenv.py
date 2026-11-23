import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402


def test_carga_claves_del_archivo_env(tmp_path, monkeypatch):
    for k in ("GEMINI_API_KEY", "GOOGLE_SHEET_ID", "NUMEROS_PERMITIDOS", "OTRA"):
        monkeypatch.delenv(k, raising=False)
    env = tmp_path / ".env"
    env.write_text('# comentario\nGEMINI_API_KEY=abc123\nGOOGLE_SHEET_ID = "id-con-comillas"\nNUMEROS_PERMITIDOS=\nlinea sin igual\n', encoding="utf-8")
    config.cargar_dotenv(env)
    assert os.environ["GEMINI_API_KEY"] == "abc123"
    assert os.environ["GOOGLE_SHEET_ID"] == "id-con-comillas"
    assert "NUMEROS_PERMITIDOS" not in os.environ          # vacío = no definido


def test_no_pisa_variables_ya_definidas(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "del-entorno")
    env = tmp_path / ".env"
    env.write_text("GEMINI_API_KEY=del-archivo\n", encoding="utf-8")
    config.cargar_dotenv(env)
    assert os.environ["GEMINI_API_KEY"] == "del-entorno"


def test_sin_archivo_no_hace_nada(tmp_path):
    config.cargar_dotenv(tmp_path / "no-existe.env")


def test_env_real_esta_ignorado_por_git():
    raiz = Path(__file__).resolve().parent.parent
    assert ".env" in (raiz / ".gitignore").read_text().splitlines()

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "env.py"
spec = importlib.util.spec_from_file_location("deployment_env", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_init_preserves_existing_bytes(tmp_path):
    path = tmp_path / ".env"
    command = [sys.executable, str(SCRIPT), "init", str(path), "--demo"]
    subprocess.run(command, check=True, capture_output=True)
    original = path.read_bytes()
    result = subprocess.run(command, capture_output=True)
    assert result.returncode != 0
    assert path.read_bytes() == original
    module.validate(module.read_env(path))


@pytest.mark.parametrize("content", ["A=$(touch pwned)", "A=1\nA=2", "source bad.sh", "a=1"])
def test_rejects_shell_code_and_duplicates(tmp_path, content):
    path = tmp_path / ".env"
    path.write_text(content)
    with pytest.raises(ValueError):
        module.read_env(path)


def test_missing_secrets_fail_without_values_in_error():
    with pytest.raises(ValueError, match="DJANGO_SECRET_KEY"):
        module.validate({})

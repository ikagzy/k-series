import importlib.util
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parent.parent / "tools" / "make_version.py"


@pytest.fixture(scope="module")
def tool():
    spec = importlib.util.spec_from_file_location("make_version", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_version_tuple_pads_to_four_numbers(tool):
    assert tool.version_tuple("1.2") == (1, 2, 0, 0)
    assert tool.version_tuple("4.0.1") == (4, 0, 1, 0)
    assert tool.version_tuple("1.2.3.4") == (1, 2, 3, 4)
    with pytest.raises(ValueError):
        tool.version_tuple("nightly")


def test_rendered_file_carries_the_version_name_and_is_valid_python(tool):
    text = tool.render("K-Optimizer", "K-Optimizer", "1.5.2", "K-Optimizer.exe")
    assert "filevers=(1, 5, 2, 0)" in text and "'FileVersion', '1.5.2.0'" in text
    assert "'ProductName', 'K-Optimizer'" in text and "OriginalFilename', 'K-Optimizer.exe'" in text
    compile(text, "version_info", "eval")  # PyInstaller evaluates this text as a Python expression


def test_main_reads_the_version_from_the_package_and_writes_the_file(tool, tmp_path):
    out = tmp_path / "v.txt"
    tool.main(["k_optimizer", "K-Optimizer", "K-Optimizer.exe", str(out)])
    import k_optimizer

    assert f"'FileVersion', '{'.'.join(map(str, tool.version_tuple(k_optimizer.__version__)))}'" in out.read_text()

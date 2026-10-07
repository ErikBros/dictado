"""dictado-2ta: GPU timing tests skip, with the reason, while the installed Ecoscribe uses the GPU."""
from tests.gpu_busy import gpu_use

WIN = r"C:\Users\someone\AppData\Local\Programs\Ecoscribe\Ecoscribe.exe"
MAC = "/Applications/Ecoscribe.app/Contents/MacOS/Ecoscribe"


def test_the_installed_apps_gpu_work_is_recognised_on_both_platforms():
    assert gpu_use([f'"{WIN}"', f"{WIN} --hook 163 1.0 30.0", f"{WIN} --supervise"]) is None
    assert gpu_use([f'"{WIN}"', f"{WIN} --engine-worker"]).startswith("holding its speech model")
    assert gpu_use([f"{WIN} --meeting C:\\x\\2026-01-01_1000_meeting", f"{WIN} --engine-worker"]) == "recording a meeting"
    assert gpu_use([f"{MAC} --transcribe /tmp/x"]) == "transcribing a file"


def test_a_test_run_of_the_source_is_not_the_installed_app():
    assert gpu_use(["python.exe -m ecoscribe --transcribe C:\\tmp\\t", "python -m ecoscribe --engine-worker"]) is None

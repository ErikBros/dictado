"""dictado-2ta: GPU timing tests skip, with the reason, while the installed Ecoscribe uses the GPU."""
from tests.gpu_busy import busy_reason, gpu_use

WIN = r"C:\Users\someone\AppData\Local\Programs\Ecoscribe\Ecoscribe.exe"
MAC = "/Applications/Ecoscribe.app/Contents/MacOS/Ecoscribe"


def test_the_installed_apps_gpu_work_is_recognised_on_both_platforms():
    assert gpu_use([f'"{WIN}"', f"{WIN} --hook 163 1.0 30.0", f"{WIN} --supervise"]) is None
    assert gpu_use([f'"{WIN}"', f"{WIN} --engine-worker"]).startswith("holding its speech model")
    assert gpu_use([f"{WIN} --meeting C:\\x\\2026-01-01_1000_meeting", f"{WIN} --engine-worker"]) == "recording a meeting"
    assert gpu_use([f"{MAC} --transcribe /tmp/x"]) == "transcribing a file"


def test_a_test_run_of_the_source_is_not_the_installed_app():
    assert gpu_use(["python.exe -m ecoscribe --transcribe C:\\tmp\\t", "python -m ecoscribe --engine-worker"]) is None


def test_other_apps_keeping_the_gpu_busy_also_skip_with_the_number():
    """dictado-2so: another app's GPU effects at 36-42 % made the base latency 704 ms instead of ~250."""
    assert busy_reason(None, 38.4) == "the GPU is already 38 % busy with other apps"
    assert busy_reason("recording a meeting", 5.0) == "the installed Ecoscribe is recording a meeting"
    assert busy_reason(None, 3.0) is None and busy_reason(None, None) is None  # quiet, or no nvidia-smi (Mac)

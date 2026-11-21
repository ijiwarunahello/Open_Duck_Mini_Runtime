import subprocess

from tools.bench.preflight import find_conflicts


def _result(cmd, out, code=None):
    return subprocess.CompletedProcess(cmd, (0 if out else 1) if code is None else code, stdout=out, stderr="")


def test_conflict_when_runtime_running():
    def fake_run(cmd, **kw):
        out = "1234 python v2_rl_walk_mujoco.py\n" if cmd[0] == "pgrep" and "v2_rl_walk_mujoco.py" in cmd else ""
        return _result(cmd, out)

    assert any("v2_rl_walk_mujoco.py" in r for r in find_conflicts(run=fake_run))


def test_conflict_when_port_open():
    def fake_run(cmd, **kw):
        return _result(cmd, " 4321" if cmd[0] == "fuser" else "")

    assert any("/dev/ttyACM0" in r for r in find_conflicts(run=fake_run))


def test_no_conflict():
    assert find_conflicts(run=lambda cmd, **kw: _result(cmd, "")) == []


def test_own_process_is_ignored(monkeypatch):
    monkeypatch.setattr("os.getpid", lambda: 999)

    def fake_run(cmd, **kw):
        out = "999 python check_motors.py\n" if cmd[0] == "pgrep" and "check_motors.py" in cmd else ""
        return _result(cmd, out)

    assert find_conflicts(run=fake_run) == []

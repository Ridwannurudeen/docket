from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_the_oneshot_uses_the_live_database_and_yields_on_the_shared_host():
    unit = _read(DEPLOY / "systemd" / "docket-canary.service")

    for required in (
        "User=docket",
        "Group=docket",
        "WorkingDirectory=/var/lib/docket",
        "Environment=DOCKET_DB=/var/lib/docket/data/agents.sqlite3",
        "ExecStart=/opt/docket/.venv/bin/python -m docket.canary",
        "Nice=10",
        "IOSchedulingClass=idle",
        "TimeoutStartSec=8min",
    ):
        assert required in unit
    assert "Environment=DOCKET_CANARY_END_AT=2026-09-24T00:00:00Z" in unit


def test_the_timer_runs_daily_with_jitter_and_catches_one_missed_run():
    timer = _read(DEPLOY / "systemd" / "docket-canary.timer")

    assert "OnCalendar=*-*-* 04:17:00 UTC" in timer
    assert "RandomizedDelaySec=30m" in timer
    assert "Persistent=true" in timer
    assert "OnUnitActiveSec" not in timer


def test_the_installer_enables_but_never_starts_or_restarts_a_service():
    installer = _read(DEPLOY / "install-canary.sh")
    commands = [line.strip() for line in installer.splitlines()]

    assert "systemctl daemon-reload" in installer
    assert "systemctl enable docket-canary.timer" in installer
    assert "systemctl start docket-canary.timer" not in commands
    assert "systemctl restart docket.service" not in commands
    assert "/var/lib/docket/data" not in installer
    assert installer.index("backup_existing") < installer.index(
        'install -o root -g root -m 0644 "${SERVICE_SOURCE}"'
    )


def test_owner_only_lp_and_payment_configuration_remains_unset():
    config = _read(DEPLOY / "docket-canary.conf.example")

    for name in (
        "DOCKET_CANARY_WALLET",
        "DOCKET_CANARY_TOKEN_ID",
        "DOCKET_CANARY_POSITION_VALUE_USD",
        "DOCKET_CANARY_RECENTER_COST_USD",
        "DOCKET_CANARY_PRIVATE_KEY_FILE",
    ):
        assert f"# {name}=" in config

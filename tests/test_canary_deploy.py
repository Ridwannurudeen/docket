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


def test_public_b402_canary_configuration_names_the_live_payment_boundary():
    config = _read(DEPLOY / "docket-canary.conf.example")

    for required in (
        "DOCKET_FACILITATOR_KIND=b402",
        "DOCKET_FACILITATOR_URL=https://facilitatorv3.b402.ai/api/v1",
        "DOCKET_PAYMENT_TOKEN=0x55d398326f99059fF775485246999027B3197955",
        "DOCKET_B402_RELAYER_CONTRACT=0xE1Af7DaEa624bA3B5073f24A6Ea5531434D82d88",
        "# DOCKET_BSC_RPC_URL=https://your-bsc-mainnet-rpc.example",
    ):
        assert required in config


def test_the_v3_capture_prearms_and_has_bounded_failure_restarts():
    service = _read(DEPLOY / "systemd" / "docket-v3-capture.service")
    timer = _read(DEPLOY / "systemd" / "docket-v3-capture.timer")

    assert "OnCalendar=2026-08-26 11:50:00 UTC" in timer
    assert "Persistent=true" in timer
    assert not any(
        line.startswith("RandomizedDelaySec=") for line in timer.splitlines()
    )
    assert "Restart=on-failure" in service
    assert "RestartSec=30s" in service
    assert "RestartPreventExitStatus=2 3" in service
    assert "StartLimitIntervalSec=15min" in service
    assert "StartLimitBurst=3" in service
    assert "Restart=no" not in service


def test_the_v3_range_capture_starts_after_yield_and_uses_a_distinct_lock():
    service = _read(DEPLOY / "systemd" / "docket-v3-range-capture.service")
    timer = _read(DEPLOY / "systemd" / "docket-v3-range-capture.timer")

    assert "OnCalendar=2026-08-26 12:03:00 UTC" in timer
    assert "Unit=docket-v3-range-capture.service" in timer
    assert "Persistent=true" in timer
    assert not any(
        line.startswith("RandomizedDelaySec=") for line in timer.splitlines()
    )
    assert "v3-05-range-doctor /var/lib/docket/v3-capture/range" in service
    assert "Nice=-5" in service
    assert "TimeoutStartSec=15min" in service
    assert "Restart=on-failure" in service
    assert "RestartSec=30s" in service
    assert "RestartPreventExitStatus=2 3" in service
    assert "After=docket-v3-capture.service" not in service

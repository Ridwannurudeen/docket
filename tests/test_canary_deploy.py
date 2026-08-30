from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_the_oneshot_uses_the_live_database_and_yields_on_the_shared_host():
    unit = _read(DEPLOY / "systemd" / "docket-canary.service")

    for required in (
        "User=docket-canary",
        "Group=docket-canary",
        "WorkingDirectory=/var/lib/docket",
        "Environment=DOCKET_DB=/var/lib/docket/data/agents.sqlite3",
        "ExecStart=/opt/docket/.venv/bin/python -P -m docket.canary",
        "Nice=10",
        "IOSchedulingClass=idle",
        "TimeoutStartSec=8min",
    ):
        assert required in unit
    assert "SupplementaryGroups=" not in unit
    assert "Environment=DOCKET_CANARY_END_AT=2026-09-24T00:00:00Z" in unit


def test_the_web_unit_cannot_open_canary_signing_material():
    unit = _read(DEPLOY / "systemd" / "docket.service")

    assert (
        "InaccessiblePaths=-/etc/docket/docket-canary.conf "
        "-/etc/docket/docket-canary-payment.key"
    ) in unit


def test_the_timer_runs_daily_with_jitter_and_catches_one_missed_run():
    timer = _read(DEPLOY / "systemd" / "docket-canary.timer")

    assert "OnCalendar=*-*-* 04:17:00 UTC" in timer
    assert "RandomizedDelaySec=30m" in timer
    assert "Persistent=true" in timer
    assert "OnUnitActiveSec" not in timer


def test_the_installer_locks_and_quiesces_without_enabling_or_starting_services():
    installer = _read(DEPLOY / "install-canary.sh")
    commands = [line.strip() for line in installer.splitlines()]

    assert "systemctl daemon-reload" in installer
    assert "flock -n" in installer
    assert "systemctl disable --now docket-canary.timer" in installer
    assert "systemctl enable docket-canary.timer" not in commands
    assert "systemctl start docket-canary.timer" not in commands
    assert "systemctl restart docket.service" not in commands
    assert installer.index("backup_existing") < installer.index(
        'install -o root -g root -m 0644 "${SERVICE_SOURCE}"'
    )


def test_the_installer_builds_and_validates_the_dedicated_signer_boundary():
    installer = _read(DEPLOY / "install-canary.sh")

    for required in (
        "groupadd --system docket-canary",
        "useradd --system --gid docket-canary --no-create-home",
        "--home-dir /nonexistent --shell /usr/sbin/nologin docket-canary",
        "command -v getfacl",
        '"${canary_groups}" != docket-canary',
        '-n "${group_members}"',
        "-e /nonexistent || -L /nonexistent",
        "docket must not be a member of docket-canary",
        'install -o root -g docket-canary -m 0640 "${CONFIG_SOURCE}"',
        'chown root:docket-canary "${CONFIG_TARGET}"',
        'chown root:docket-canary "${PAYMENT_KEY_TARGET}"',
        'install -o root -g docket -m 0640 "${TOKEN_TEMP}" "${TOKEN_TARGET}"',
        'setfacl -b "${TOKEN_TARGET}" "${CONFIG_TARGET}" "${DATABASE_TARGET}"',
        'setfacl -b "${PAYMENT_KEY_TARGET}"',
        'setfacl -b -k "${CONFIG_DIRECTORY}" "${STATE_DIRECTORY}" "${DATA_TARGET}"',
        'chown docket:docket "${STATE_DIRECTORY}" "${DATA_TARGET}" "${DATABASE_TARGET}"',
        'chmod 0750 "${STATE_DIRECTORY}" "${DATA_TARGET}"',
        'chmod 0640 "${DATABASE_TARGET}"',
        'setfacl -m u:docket-canary:--x "${CONFIG_DIRECTORY}" "${STATE_DIRECTORY}"',
        'setfacl -m u:docket-canary:r-- "${TOKEN_TARGET}"',
        'setfacl -m u:docket:rwx,u:docket-canary:rwx,o::--- "${DATA_TARGET}"',
        'setfacl -m d:u:docket:rwx,d:u:docket-canary:rwx,d:o::--- "${DATA_TARGET}"',
        'setfacl -m u:docket:rw-,u:docket-canary:rw-,o::--- "${DATABASE_TARGET}"',
    ):
        assert required in installer

    backup_start = installer.index("for target in")
    backup_end = installer.index("backup_existing", backup_start)
    assert '"${PAYMENT_KEY_TARGET}"' in installer[backup_start:backup_end]


def test_the_web_dropin_contains_only_public_settlement_settings_and_the_token_file():
    installer = _read(DEPLOY / "install-canary.sh")

    for required in (
        "Environment=DOCKET_ENABLE_SETTLEMENT=1",
        "Environment=DOCKET_FACILITATOR_KIND=b402",
        "Environment=DOCKET_FACILITATOR_URL=https://facilitatorv3.b402.ai/api/v1",
        "Environment=DOCKET_PAY_TO=0xe55816904796341bf8535e25f6c8b647927fc946",
        "Environment=DOCKET_CANARY_TOKEN_FILE=/etc/docket/docket-canary.token",
        'install -o root -g root -m 0644 "${DROPIN_TEMP}" "${DROPIN_TARGET}"',
    ):
        assert required in installer

    assert "EnvironmentFile=/etc/docket/docket-canary.conf" not in installer
    assert "Environment=DOCKET_BSC_RPC_URL=" not in installer
    assert "Environment=DOCKET_CANARY_PRIVATE_KEY_FILE=" not in installer


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
        "DOCKET_PAY_TO=0xe55816904796341bf8535e25f6c8b647927fc946",
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
    assert "StartLimitIntervalSec=15min" in service
    assert "StartLimitBurst=3" in service
    assert "After=docket-v3-capture.service" not in service


def test_the_v3_yield_v6_capture_prearms_with_a_distinct_target():
    service = _read(DEPLOY / "systemd" / "docket-v3-yield-v6-capture.service")
    timer = _read(DEPLOY / "systemd" / "docket-v3-yield-v6-capture.timer")

    assert "OnCalendar=2026-09-03 11:50:00 UTC" in timer
    assert "Unit=docket-v3-yield-v6-capture.service" in timer
    assert "Persistent=true" in timer
    assert not any(
        line.startswith("RandomizedDelaySec=") for line in timer.splitlines()
    )
    assert (
        "v3-06-yield-router-assisted /var/lib/docket/v3-capture/yield-v3-06"
        in service.replace("\\\n", "")
    )
    assert "Nice=-5" in service
    assert "TimeoutStartSec=15min" in service
    assert "Restart=on-failure" in service
    assert "RestartSec=30s" in service
    assert "RestartPreventExitStatus=2 3" in service
    assert "StartLimitIntervalSec=15min" in service
    assert "StartLimitBurst=3" in service

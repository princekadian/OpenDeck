from __future__ import annotations

import pytest

from opendeck.services.pairing import MAX_FAILED_ATTEMPTS, PairingError, PairingService


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def pairing(services, clock) -> PairingService:
    return PairingService(services.devices, clock=clock)


def test_pair_issues_token_and_code_is_single_use(pairing: PairingService) -> None:
    code, _ = pairing.current_code()
    device, token = pairing.pair(code, "iPad")
    assert pairing.authenticate(token).id == device.id
    with pytest.raises(PairingError):
        pairing.pair(code, "iPad 2")


def test_token_is_not_stored_in_plain_text(pairing: PairingService, services) -> None:
    code, _ = pairing.current_code()
    _, token = pairing.pair(code, "iPad")
    stored = services.db.query("SELECT token_hash FROM devices")
    assert all(token not in row["token_hash"] for row in stored)


def test_code_expires(pairing: PairingService, clock: FakeClock) -> None:
    code, _ = pairing.current_code()
    clock.now += 301
    with pytest.raises(PairingError) as exc:
        pairing.pair(code, "iPad")
    assert exc.value.code == "code_expired"


def test_code_invalidated_after_failed_attempts(pairing: PairingService) -> None:
    code, _ = pairing.current_code()
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(MAX_FAILED_ATTEMPTS):
        with pytest.raises(PairingError):
            pairing.pair(wrong, "attacker")
    with pytest.raises(PairingError) as exc:
        pairing.pair(code, "iPad")
    assert exc.value.code == "code_expired"


def test_revoked_device_cannot_authenticate(pairing: PairingService, services) -> None:
    code, _ = pairing.current_code()
    device, token = pairing.pair(code, "iPad")
    services.devices.revoke(device.id)
    assert pairing.authenticate(token) is None

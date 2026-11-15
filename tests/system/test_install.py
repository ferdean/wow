"""File modes of the installed service on the Pi (L6): T-SYS-05.

After `sudo deploy/install.sh`, with the account entered once in
Settings (run `sudo -v` first):

    uv run pytest -m pi tests/system/test_install.py
"""

import os
import subprocess

import pytest

DATA = os.environ.get("WOW_DATA", "/var/lib/wow")
SECRETS = (f"{DATA}/secrets.json", f"{DATA}/tls/server.key")


@pytest.mark.case("T-SYS-05")
@pytest.mark.req("APP-817")
@pytest.mark.pi
@pytest.mark.parametrize("path", SECRETS)
def test_secrets_are_readable_by_wow_only(path: str) -> None:
    found = subprocess.run(["sudo", "stat", "-c", "%a %U %G", path],
                           check=True, capture_output=True, text=True)
    assert found.stdout.split() == ["600", "wow", "wow"]

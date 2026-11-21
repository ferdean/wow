"""Sign in to Garmin Connect for the Garmin upload.

    wow-garmin login                  # email, password and MFA code, once
    wow-garmin check                  # are the stored tokens accepted?
    wow-garmin upload <ride.fit>      # one file by hand, as the app does
    wow-garmin upload <ride.fit> --import
    wow-garmin logout

Run it as the user the service runs as, with the service's wow.toml, so
the tokens land in its data directory:

    sudo -u wow /opt/wow/venv/bin/wow-garmin --config /etc/wow/wow.toml login

With a [riders] table in wow.toml, name the rider (riders.md):

    sudo -u wow /opt/wow/venv/bin/wow-garmin --rider anna login
"""

import argparse
import getpass
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final

from wow.adapters.garmin_connect import GarminConnect, GarminError
from wow.app.config import Config, garmin_tokens, load_config
from wow.app.riders import Riders
from wow.core.upload import Outcome

DEFAULT_CONFIG: Final[Path] = Path("/etc/wow/wow.toml")
SENT: Final[frozenset[Outcome]] = frozenset({Outcome.CREATED, Outcome.KNOWN})

Account = Callable[[Path], GarminConnect]
Ask = Callable[[str], str]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the command line."""
    parser = argparse.ArgumentParser(
        prog="wow-garmin", description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--rider", help="the rider's ID in [riders]")
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("login", help="sign in and store the tokens")
    actions.add_parser("check", help="sign in from the stored tokens")
    upload = actions.add_parser("upload", help="upload one FIT file")
    upload.add_argument("fit", type=Path)
    upload.add_argument("--import", dest="as_import", action="store_true",
                        help="as an import; the library says Garmin "
                        "doesn't pass imports on to partners")
    actions.add_parser("logout", help="delete the stored tokens")
    return parser.parse_args(argv)


def run(args: argparse.Namespace, account: Account, ask: Ask,
        secret: Ask) -> int:
    """Carry out one action; return the exit code."""
    home = _home(load_config(args.config), args.rider)
    if home is None:
        return 2
    tokens = garmin_tokens(home)
    garmin = account(tokens)
    try:
        match args.action:
            case "login":
                name = garmin.sign_in(ask("Garmin email: "),
                                      secret("Garmin password: "),
                                      lambda: ask("MFA code: "))
                print(f"Signed in as {name}; tokens in {tokens}")
            case "check":
                print(f"Tokens accepted for {garmin.check()}")
            case "logout":
                garmin.sign_out()
                print(f"Tokens deleted from {tokens}")
            case "upload":
                return _upload(garmin, args.fit, args.as_import)
    except GarminError as error:
        print(f"Garmin Connect: {error}", file=sys.stderr)
        return 1
    return 0


def _home(config: Config, rider_id: str | None) -> Path | None:
    riders = Riders(config.data, config.riders, lambda work: work())
    known = ", ".join(r.rider_id for r in riders.riders)
    if riders.configured and riders.find(rider_id) is None:
        print(f"name the rider with --rider: {known}", file=sys.stderr)
        return None
    if not riders.configured and rider_id is not None:
        print("wow.toml has no [riders]: leave --rider out", file=sys.stderr)
        return None
    riders.prepare()
    return riders.home(rider_id or riders.active.rider_id)


def _upload(garmin: GarminConnect, fit: Path, as_import: bool) -> int:
    if not fit.is_file():
        print(f"{fit}: no such file", file=sys.stderr)
        return 1
    outcome = garmin.send(fit, as_import)
    print(f"{fit}: {outcome}")
    return 0 if outcome in SENT else 1


def main(argv: Sequence[str] | None = None) -> None:
    """Run wow-garmin from the command line."""
    sys.exit(run(parse_args(argv), GarminConnect, input, getpass.getpass))


if __name__ == "__main__":
    main()

"""Phase 2 display spike S8: a private root certificate and a server
certificate for the Pi. Throwaway: not app code."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT_DAYS = 3650
SERVER_DAYS = 365
KEY = "rsa:2048"


@dataclass(frozen=True)
class Files:
    folder: Path

    @property
    def root_key(self) -> Path:
        return self.folder / "root.key"

    @property
    def root_cert(self) -> Path:
        return self.folder / "root.crt"

    @property
    def root_config(self) -> Path:
        return self.folder / "root.cnf"

    @property
    def server_key(self) -> Path:
        return self.folder / "server.key"

    @property
    def server_request(self) -> Path:
        return self.folder / "server.csr"

    @property
    def server_cert(self) -> Path:
        return self.folder / "server.crt"

    @property
    def server_config(self) -> Path:
        return self.folder / "server.cnf"


CONSTRAINTS = ("full", "dns", "none")


def name_constraints(host: str, mode: str) -> str | None:
    """The iPhone fully trusts this root, so whoever holds root.key could
    impersonate any site to it. "full" limits the root to the Pi's own
    name and rules out IP addresses; "dns" only limits the name."""
    if mode == "none":
        return None
    value = f"critical, permitted;DNS:{host}"
    if mode == "full":
        value += (", excluded;IP:0.0.0.0/0.0.0.0"
                  ", excluded;IP:0:0:0:0:0:0:0:0/0:0:0:0:0:0:0:0")
    return value


def root_config(host: str, mode: str) -> str:
    lines = [
        "[req]",
        "prompt = no",
        "distinguished_name = dn",
        "x509_extensions = root",
        "[dn]",
        f"CN = WitchesOnWheels private root ({host}, {mode})",
        "[root]",
        "basicConstraints = critical, CA:TRUE, pathlen:0",
        "keyUsage = critical, keyCertSign, cRLSign",
        "subjectKeyIdentifier = hash",
    ]
    constraints = name_constraints(host, mode)
    if constraints is not None:
        lines.append(f"nameConstraints = {constraints}")
    return "\n".join(lines) + "\n"


def server_config(host: str) -> str:
    return "\n".join([
        "[server]",
        "basicConstraints = critical, CA:FALSE",
        "keyUsage = critical, digitalSignature, keyEncipherment",
        "extendedKeyUsage = serverAuth",
        f"subjectAltName = DNS:{host}",
        "subjectKeyIdentifier = hash",
        "authorityKeyIdentifier = keyid, issuer",
    ]) + "\n"


def root_commands(files: Files) -> list[list[str]]:
    return [[
        "openssl", "req", "-x509", "-newkey", KEY, "-noenc", "-sha256",
        "-days", str(ROOT_DAYS), "-config", str(files.root_config),
        "-keyout", str(files.root_key), "-out", str(files.root_cert),
    ]]


def server_commands(files: Files, host: str) -> list[list[str]]:
    return [
        ["openssl", "req", "-new", "-newkey", KEY, "-noenc",
         "-subj", f"/CN={host}", "-keyout", str(files.server_key),
         "-out", str(files.server_request)],
        ["openssl", "x509", "-req", "-sha256", "-days", str(SERVER_DAYS),
         "-in", str(files.server_request), "-CA", str(files.root_cert),
         "-CAkey", str(files.root_key), "-extfile", str(files.server_config),
         "-extensions", "server", "-out", str(files.server_cert)],
        ["openssl", "verify", "-CAfile", str(files.root_cert),
         str(files.server_cert)],
    ]


def fingerprint_command(cert: Path) -> list[str]:
    return ["openssl", "x509", "-noout", "-fingerprint", "-sha256",
            "-in", str(cert)]


def run(command: list[str]) -> str:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(command[:2])} failed:\n"
                           f"{result.stderr.strip()}")
    return result.stdout.strip()


def make(folder: Path, host: str, new_root: bool,
         constraints: str) -> tuple[Files, bool]:
    """Keeps an existing root, because the iPhone trusts that exact root;
    the server certificate is reissued every time."""
    files = Files(folder)
    folder.mkdir(parents=True, exist_ok=True)
    made_root = new_root or not files.root_cert.exists()
    if made_root:
        files.root_config.write_text(root_config(host, constraints))
        for command in root_commands(files):
            run(command)
    files.server_config.write_text(server_config(host))
    for command in server_commands(files, host):
        run(command)
    for key in (files.root_key, files.server_key):
        os.chmod(key, 0o600)
    return files, made_root


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="wow.local")
    parser.add_argument("--folder", type=Path, default=Path("certs"))
    parser.add_argument("--new-root", action="store_true",
                        help="replace the root; the iPhone must trust the "
                             "new one again")
    parser.add_argument("--constraints", choices=CONSTRAINTS,
                        help="name constraints on a new root: full (name "
                             "and no IP addresses), dns (name only), none")
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args(sys.argv[1:])
    try:
        files, made_root = make(args.folder, args.host, args.new_root,
                                args.constraints or "full")
    except (RuntimeError, FileNotFoundError) as error:
        sys.exit(str(error))
    if args.constraints and not made_root:
        print("Root kept, so --constraints had no effect; add --new-root "
              "to replace it.")
    state = "new" if made_root else "kept"
    print(f"Root certificate ({state}): {files.root_cert}")
    print(f"  {run(fingerprint_command(files.root_cert))}")
    print(f"Server certificate for {args.host}: {files.server_cert} "
          f"({SERVER_DAYS} days)")
    if made_root:
        print("The iPhone must install and fully trust this root before "
              "the HTTPS page opens.")


if __name__ == "__main__":
    main()

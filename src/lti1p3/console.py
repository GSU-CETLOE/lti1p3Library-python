"""The lti1p3-generate-keypair command.

Every LTI 1.3 tool registration needs its own RSA key pair to sign outbound
JWTs (client assertions, Deep Linking responses) and a JWKS the platform
verifies them against. Generating one is a setup step, not something the
library does at runtime, so it lives here as a command.

The argument handling is a plain method taking a list of arguments and
returning a CommandResult, instead of calling sys.exit itself, so it can be
unit tested without a subprocess.
"""

import json
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from lti1p3.security import buildJwk, generateKeyPair

USAGE = """Usage: lti1p3-generate-keypair --kid=<kid> [--bits=2048] [--out-dir=working/keys]

  --kid       Required. Key ID to embed in the JWK (e.g. "2026-07-key-1").
  --bits      Optional. RSA key size in bits, minimum 2048 (default: 2048).
  --out-dir   Optional. Directory to write <kid>.private.pem/<kid>.public.pem into
              (default: working/keys, relative to the current directory). Created if missing.
  --help      Show this message.

Generates a new RSA key pair for signing outbound tool JWTs, writes the
PEM files, and prints the corresponding JWK entry as JSON on stdout so you
can add it to your tool's published JWKS document.
"""


@dataclass(frozen=True)
class CommandResult:
    """The outcome of a command: an exit code plus what to write to stdout and stderr."""

    exitCode: int
    stdout: str = ""
    stderr: str = ""


class GenerateKeypairCommand:
    """Parses the command's arguments, generates a key pair, writes the PEM files, and prints the JWK."""

    DEFAULT_BITS = 2048
    MINIMUM_BITS = 2048

    def run(self, arguments: Sequence[str]) -> CommandResult:
        """Run with the command-line arguments (without the program name)."""
        try:
            options = self._parseArguments(arguments)
        except ValueError as error:
            return CommandResult(1, stderr=f"Error: {error}\n\n{USAGE}")

        if options.help:
            return CommandResult(0, USAGE)

        if options.kid is None or not options.kid.strip():
            return CommandResult(1, stderr=f"Error: --kid is required.\n\n{USAGE}")

        bits = options.bits if options.bits is not None else self.DEFAULT_BITS
        if bits < self.MINIMUM_BITS:
            return CommandResult(1, stderr=f"Error: --bits must be at least {self.MINIMUM_BITS}.\n\n{USAGE}")

        outDir = options.outDir if options.outDir is not None else Path.cwd() / "working" / "keys"
        try:
            outDir.mkdir(mode=0o700, parents=True, exist_ok=True)
        except OSError:
            return CommandResult(1, stderr=f'Error: could not create output directory "{outDir}".\n')

        keyPair = generateKeyPair(options.kid, bits)
        privateKeyPath = outDir / f"{options.kid}.private.pem"
        publicKeyPath = outDir / f"{options.kid}.public.pem"

        privateKeyPath.write_text(keyPair.privateKey)
        os.chmod(privateKeyPath, 0o600)
        publicKeyPath.write_text(keyPair.publicKey)

        stdout = (
            f"Wrote private key: {privateKeyPath}\n"
            f"Wrote public key:  {publicKeyPath}\n"
            "\n"
            'JWK (add this to your tool\'s published JWKS "keys" array):\n'
            "\n"
            f"{json.dumps(buildJwk(keyPair), indent=4)}\n"
        )
        return CommandResult(0, stdout)

    @dataclass(frozen=True)
    class Options:
        help: bool
        kid: str | None
        bits: int | None
        outDir: Path | None

    @classmethod
    def _parseArguments(cls, arguments: Sequence[str]) -> Options:
        """Parse --help, --kid=, --bits=, and --out-dir=, raising ValueError for anything else."""
        showHelp = False
        kid: str | None = None
        bits: int | None = None
        outDir: Path | None = None

        for argument in arguments:
            if argument == "--help":
                showHelp = True
            elif argument.startswith("--kid="):
                kid = argument[len("--kid=") :]
            elif argument.startswith("--bits="):
                rawBits = argument[len("--bits=") :]
                if not rawBits.isdigit():
                    raise ValueError("--bits must be a whole number.")
                bits = int(rawBits)
            elif argument.startswith("--out-dir="):
                outDir = Path(argument[len("--out-dir=") :])
            else:
                raise ValueError(f'Unknown argument "{argument}".')

        return cls.Options(showHelp, kid, bits, outDir)


def main(arguments: Sequence[str] | None = None) -> None:
    """Console entry point: run the command and exit with its code."""
    result = GenerateKeypairCommand().run(sys.argv[1:] if arguments is None else arguments)
    if result.stdout:
        sys.stdout.write(result.stdout)
    if result.stderr:
        sys.stderr.write(result.stderr)
    sys.exit(result.exitCode)

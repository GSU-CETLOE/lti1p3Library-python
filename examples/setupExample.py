"""One-shot setup for the example: generates two RSA key pairs and writes config.json.

One key pair is the tool's; the other belongs to the simulator playing the
platform. Safe to re-run: it regenerates everything, so any launch mid-flight
has to start over.

Usage:
    python examples/setupExample.py [--home DIR] [--tool-port 8000] [--simulator-port 8001]
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from exampleCommon import DEFAULT_HOME, SIMULATOR_KID, TOOL_KID  # noqa: E402

from lti1p3 import generateKeyPair  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate keys and config for the example tool and simulator.")
    parser.add_argument("--home", type=Path, default=DEFAULT_HOME, help="Where keys, config, and cache files go.")
    parser.add_argument("--tool-port", type=int, default=8000, help="Port the example tool will listen on.")
    parser.add_argument("--simulator-port", type=int, default=8001, help="Port the platform simulator will listen on.")
    args = parser.parse_args()

    home: Path = args.home
    keysDir = home / "keys"
    keysDir.mkdir(mode=0o700, parents=True, exist_ok=True)

    for kid in (TOOL_KID, SIMULATOR_KID):
        keyPair = generateKeyPair(kid)
        privatePath = keysDir / f"{kid}.private.pem"
        privatePath.write_text(keyPair.privateKey)
        os.chmod(privatePath, 0o600)
        (keysDir / f"{kid}.public.pem").write_text(keyPair.publicKey)

    config = {
        "tool_base_url": f"http://localhost:{args.tool_port}",
        "simulator_base_url": f"http://localhost:{args.simulator_port}",
        "client_id": "demo-client-1",
        "deployment_id": "demo-deployment-1",
        "tool_kid": TOOL_KID,
        "simulator_kid": SIMULATOR_KID,
    }
    (home / "config.json").write_text(json.dumps(config, indent=2) + "\n")

    print("Setup complete.\n")
    print(f"Generated tool and simulator RSA key pairs in {keysDir}.")
    print(f"Wrote {home / 'config.json'}.\n")
    print("Next steps (run each in its own terminal):")
    print(f"  1. python examples/tool.py --home {home}")
    print(f"  2. python examples/simulator.py --home {home}")
    print(f"  3. Open {config['simulator_base_url']}/ in your browser and click through.")


if __name__ == "__main__":
    main()

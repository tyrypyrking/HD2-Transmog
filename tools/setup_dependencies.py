#!/usr/bin/env python3
"""Fetch only the pinned upstream packaging modules into ignored local storage."""
from pathlib import Path
import hashlib
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
REVISION = '836427cef78b8a67cf771c1f16291d93be921744'
SOURCE = 'https://raw.githubusercontent.com/CowboyBingus/BingusSharedLoader/'
FILES = {
    'build_addon.py': 'a4e5aefb58152b8380c504f154bceb242a1b0b0ba8d6266f249409012896cbee',
    'archive.py': '1da94db4352340246ae99515638784f0653839f26fc77b7405a9bb39d834f9c2',
}


def main():
    destination = ROOT / 'vendor/BingusSharedLoader/scripts'
    pending = {}
    for name, digest in FILES.items():
        target = destination / name
        if target.exists():
            if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                raise SystemExit(f'{target.name} differs from the pinned dependency; preserve your changes before replacing it.')
            continue
        with urllib.request.urlopen(SOURCE + REVISION + '/scripts/' + name, timeout=30) as response:
            data = response.read(1024 * 1024)
        if hashlib.sha256(data).hexdigest() != digest:
            raise SystemExit(f'Upstream checksum mismatch: {name}')
        pending[name] = data
    destination.mkdir(parents=True, exist_ok=True)
    for name, data in pending.items():
        (destination / name).write_bytes(data)
    print('Pinned Bingus Shared Loader packaging dependency is ready.')


if __name__ == '__main__':
    main()

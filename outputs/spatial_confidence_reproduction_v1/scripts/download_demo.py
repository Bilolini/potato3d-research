"""Fetch only the pinned public demo, verify bytes, then safely extract it."""
import argparse
import hashlib
from pathlib import Path
import stat
import urllib.request
import zipfile

URL = "https://github.com/UTokyo-FieldPhenomics-Lab/corepp/releases/download/demo_dataset/3DPotatoTwinDemo.zip"
SHA256 = "c89fd95fba3284559d5b79a5679bf4bc5a9da96cb0fbc0bc9eeb6c7d8fb33fa2"
SIZE = 278967884


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=Path("data/raw"))
    args = parser.parse_args()
    root = args.destination.resolve()
    root.mkdir(parents=True, exist_ok=True)
    archive = root/"3DPotatoTwinDemo.zip"
    if not archive.exists():
        temporary = archive.with_suffix(".zip.part")
        request = urllib.request.Request(URL, headers={"User-Agent": "potato3d-reproducible-demo/0.1"})
        with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as output:
            received = 0
            while chunk := response.read(1024*1024):
                received += len(chunk)
                if received > SIZE:
                    raise ValueError("Unexpected archive size; stop and review upstream release")
                output.write(chunk)
        if received != SIZE:
            raise ValueError("Incomplete download")
        with temporary.open("rb") as f:
            if hashlib.file_digest(f, "sha256").hexdigest() != SHA256:
                raise ValueError("Archive checksum mismatch")
        temporary.replace(archive)
    with archive.open("rb") as f:
        digest = hashlib.file_digest(f, "sha256").hexdigest()
    if archive.stat().st_size != SIZE or digest != SHA256:
        raise ValueError("Existing archive does not match the pinned release")
    destination = root/"3DPotatoTwinDemo"
    if destination.exists():
        print(f"Verified archive; existing extraction retained: {destination}")
        return
    with zipfile.ZipFile(archive) as z:
        if sum(i.file_size for i in z.infolist()) > 500_000_000:
            raise ValueError("Unexpected expanded size")
        for member in z.infolist():
            if not (root/member.filename).resolve().is_relative_to(root):
                raise ValueError("Unsafe archive member")
            if stat.S_ISLNK(member.external_attr >> 16):
                raise ValueError("Symlinks are not accepted")
        z.extractall(root)
    print(f"Verified and extracted {destination}; SHA256 {digest}")


if __name__ == "__main__":
    main()

"""Fetch only pinned ZIP members, bounded HTTP ranges, CRC/size checks; no full ZIP."""
import argparse
import binascii
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import zlib

from potato3d.io import sha256, write_json


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("data/bonn_minipairs_manifest.json"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    if sum(m["compressed_bytes"] for m in manifest["members"]) > 10_000_000:
        raise ValueError("This audit script is limited to 10 MB of selected compressed assets")
    args.out.mkdir(parents=True, exist_ok=False)
    report = {"manifest_sha256": sha256(args.manifest), "source_url": manifest["source_url"], "members": []}
    with tempfile.TemporaryDirectory(prefix="bonn-zip-ranges-") as temporary:
        for member in manifest["members"]:
            name = member["name"]
            output = (args.out/name).resolve()
            if not output.is_relative_to(args.out.resolve()):
                raise ValueError("Unsafe archive member path")
            # The 512-byte local-extra budget is checked against the actual header.
            length = 30+len(name.encode("utf-8"))+512+member["compressed_bytes"]
            start, end = member["offset"], member["offset"]+length-1
            chunk = Path(temporary)/"chunk.bin"
            headers = Path(temporary)/"headers.txt"
            subprocess.run(["curl", "-sSL", "--fail", "--max-time", "60", "--range", f"{start}-{end}",
                            "--max-filesize", str(length), "-D", str(headers), manifest["source_url"], "-o", str(chunk)], check=True)
            header_text = headers.read_text().lower()
            if f"content-range: bytes {start}-{end}/{manifest['archive_bytes']}" not in header_text:
                raise ValueError("Server did not honor the exact range/total size")
            data = chunk.read_bytes()
            fields = struct.unpack_from("<4s5H3L2H", data)
            if fields[0] != b"PK\x03\x04" or fields[2] & 1:
                raise ValueError("Invalid/encrypted local ZIP entry")
            name_length, extra_length = fields[-2:]
            if extra_length > 512 or data[30:30+name_length].decode("utf-8") != name:
                raise ValueError("Local header/name differs from the manifest")
            payload = data[30+name_length+extra_length:30+name_length+extra_length+member["compressed_bytes"]]
            if fields[3] == 8:
                content = zlib.decompress(payload, -15)
            elif fields[3] == 0:
                content = payload
            else:
                raise ValueError("Unexpected compression method")
            if len(content) != member["bytes"] or binascii.crc32(content) != member["crc32"]:
                raise ValueError("ZIP CRC/size mismatch")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(content)
            report["members"].append({"name": name, "sha256": sha256(output), "bytes": len(content), "range_bytes": len(data), "crc32_verified": True})
            write_json(args.out/"download_manifest.json", report)
            print(name, len(content), "bytes; CRC verified", flush=True)

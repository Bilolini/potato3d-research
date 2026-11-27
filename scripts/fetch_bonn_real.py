"""Retrieve a bounded, pinned Bonn subset; holdout requires a frozen selection."""
import argparse
import binascii
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import zlib

from potato3d.bonn import validate_manifest
from potato3d.fruit_study import MANIFEST, verify_selection
from potato3d.io import sha256, write_json


def fetch(member, root, manifest):
    output = (root/member["name"]).resolve()
    if not output.is_relative_to(root.resolve()):
        raise ValueError("Archive member escapes data root")
    if output.exists():
        content = output.read_bytes()
        if len(content) != member["bytes"] or binascii.crc32(content) != member["crc32"]:
            raise ValueError("Existing asset does not match pinned CRC/size")
        range_bytes = 0
    else:
        length = 30+len(member["name"].encode())+512+member["compressed_bytes"]
        start, end = member["offset"], member["offset"]+length-1
        with tempfile.TemporaryDirectory(prefix="bonn-real-range-") as temporary:
            chunk, headers = Path(temporary)/"chunk", Path(temporary)/"headers"
            subprocess.run(["curl", "-sSL", "--fail", "--retry", "2", "--max-time", "90", "--range", f"{start}-{end}",
                            "--max-filesize", str(length), "-D", str(headers), manifest["source_url"], "-o", str(chunk)], check=True)
            if f"content-range: bytes {start}-{end}/{manifest['archive_bytes']}" not in headers.read_text().lower():
                raise ValueError("Exact HTTP range/total size not honored")
            data = chunk.read_bytes()
        fields = struct.unpack_from("<4s5H3L2H", data)
        name_len, extra_len = fields[-2:]
        if fields[0] != b"PK\x03\x04" or fields[2] & 1 or fields[3] != member["compression"] or extra_len > 512:
            raise ValueError("Invalid/encrypted/unexpected local ZIP header")
        if data[30:30+name_len].decode() != member["name"]:
            raise ValueError("ZIP member name differs")
        offset = 30+name_len+extra_len
        payload = data[offset:offset+member["compressed_bytes"]]
        content = zlib.decompress(payload, -15) if fields[3] == 8 else payload if fields[3] == 0 else None
        if content is None or len(content) != member["bytes"] or binascii.crc32(content) != member["crc32"]:
            raise ValueError("ZIP content CRC/size mismatch")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(content)
        range_bytes = len(data)
    return {"name": member["name"], "bytes": len(content), "sha256": sha256(output),
            "crc32_verified": True, "range_bytes": range_bytes}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--roles", choices=["train", "development", "holdout"], nargs="+", required=True)
    parser.add_argument("--selection", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    manifest = validate_manifest(json.loads(MANIFEST.read_text()))
    members = [m for o in manifest["objects"] if o["role"] in args.roles for m in o["members"]]
    if manifest["compressed_bytes"] > 200_000_000 or sum(m["compressed_bytes"] for m in members) > 200_000_000:
        raise ValueError("Bounded research subset exceeds 200 MB cap")
    if "holdout" in args.roles:
        if args.selection is None:
            raise ValueError("Holdout download requires frozen development selection")
        verify_selection(args.selection)
    args.out.mkdir(parents=True, exist_ok=True)
    receipt_path = args.out/"download_manifest.json"
    receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else {
        "manifest_sha256": sha256(MANIFEST), "source_url": manifest["source_url"], "members": []}
    if receipt["manifest_sha256"] != sha256(MANIFEST):
        raise ValueError("Data root belongs to another pinned manifest")
    byname = {m["name"]: m for m in receipt["members"]}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(fetch, m, args.out, manifest) for m in members]
        for future in as_completed(futures):
            item = future.result()
            # Preserve first retrieval receipt when reusing a verified cached member.
            if item["name"] not in byname:
                byname[item["name"]] = item
            elif byname[item["name"]]["sha256"] != item["sha256"]:
                raise ValueError("Cached member changed")
            receipt["members"] = [byname[k] for k in sorted(byname)]
            write_json(receipt_path, receipt)
            print(item["name"], "CRC/size/SHA verified", flush=True)

"""Serve a local, blinded one-response-per-image collection session."""

import argparse
import csv
from datetime import datetime, timezone
import fcntl
from functools import partial
from hashlib import sha256
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
from threading import Lock
from urllib.parse import urlsplit
import webbrowser
from zipfile import ZipFile

from PIL import Image

STUDY = Path(__file__).resolve().parent
ROOT = STUDY.parents[1]
ARCHIVES = ROOT / "data/raw/3DPotatoTwin/1_rgbd/1_images"
FIELDS = ("trial", "response", "x", "y", "recorded_at_utc")
DEFAULT_INSTRUCTION = (
    "Click once on a clear patch of skin on the indicated potato, "
    "away from the registration pin and the potato edge."
)


def pilot_manifest(directory):
    path = directory / "trial_manifest.json"
    return path if path.is_file() else STUDY / "trial_manifest.json"


def pilot_protocol(manifest_file):
    path = manifest_file.with_name("protocol.md")
    return path if path.is_file() else STUDY / "protocol.md"


def digest(data):
    return sha256(data).hexdigest()


def atomic_write(path, data):
    tmp = path.with_name(f".{path.name}.tmp")
    with tmp.open("wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)


def validate_response(payload, trial):
    if not isinstance(payload, dict) or type(payload.get("trial")) is not int:
        raise ValueError("Invalid response")
    if payload["trial"] != trial["trial"]:
        raise StaleResponse
    action = payload.get("response")
    x, y = payload.get("x"), payload.get("y")
    if action == "click" and type(x) is int and type(y) is int:
        if 0 <= x < trial["width"] and 0 <= y < trial["height"]:
            return
    if action == "cannot_identify" and x is None and y is None:
        return
    raise ValueError("Invalid response coordinates")


class StaleResponse(Exception):
    pass


class Collection:
    def __init__(self, directory, manifest_file):
        self.directory = directory
        manifest_bytes = manifest_file.read_bytes()
        self.manifest_sha256 = digest(manifest_bytes)
        self.manifest = json.loads(manifest_bytes)
        self.trials = self.manifest["trials"]
        self.source = self.manifest["source"]
        self.protocol_sha256 = digest(pilot_protocol(manifest_file).read_bytes())
        if self.manifest["protocol_sha256"] != self.protocol_sha256:
            raise ValueError("Trial manifest does not match the frozen protocol")
        if self.source not in {"development", "confirmation", "dummy"}:
            raise ValueError("Unknown image source")
        if self.source == "development":
            parent = STUDY.parent / "sam2_center_weight_v1" / "frame_manifest.json"
            if len(self.trials) != 40 or digest(parent.read_bytes()) != self.manifest["parent_frame_manifest_sha256"]:
                raise ValueError("Trial manifest does not match the frozen development cohort")
        if self.source == "confirmation":
            frozen_bytes = manifest_file.with_name("cohort_freeze.json").read_bytes()
            if digest(frozen_bytes) != self.manifest.get("cohort_sha256"):
                raise ValueError("Trial manifest does not match the frozen confirmation cohort")
            frozen = json.loads(frozen_bytes)
            expected = [
                (row["tuber"], row["archive"], row["frames"][0]["rgb_member"],
                 row["frames"][0]["crc32"], row["frames"][-1]["rgb_member"])
                for row in frozen["roster"]
            ]
            seen = [
                (row["tuber"], row["archive"], row["entry_file"], row["entry_crc32"], row["center_file"])
                for row in self.trials
            ]
            if not seen or seen != expected or frozen["protocol_sha256"] != self.protocol_sha256:
                raise ValueError("Trial order or frame selection differs from the frozen cohort")
        if [item["trial"] for item in self.trials] != list(range(1, len(self.trials) + 1)):
            raise ValueError("Invalid trial order")
        self.lock = Lock()
        self.click_file = directory / "clicks.csv"
        self.receipt_file = directory / "click_freeze.json"
        self.frozen_file = directory / "frozen_clicks.csv"
        self.image_dir = manifest_file.parent
        self.cached_image = None
        self.rows = self.read_clicks() if self.click_file.exists() else []
        if not self.click_file.exists():
            self.write_clicks(self.rows)
        self.finalize_if_complete()

    def read_clicks(self):
        with self.click_file.open(newline="") as stream:
            reader = csv.DictReader(stream)
            if tuple(reader.fieldnames or ()) != FIELDS:
                raise ValueError("Click CSV schema changed")
            rows = list(reader)
        if len(rows) > len(self.trials):
            raise ValueError("More responses than frozen trials")
        for row, trial in zip(rows, self.trials):
            row["trial"] = int(row["trial"])
            row["x"] = int(row["x"]) if row["x"] else None
            row["y"] = int(row["y"]) if row["y"] else None
            validate_response(row, trial)
            datetime.fromisoformat(row["recorded_at_utc"])
        return rows

    def write_clicks(self, rows):
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        atomic_write(self.click_file, buffer.getvalue().encode("utf-8"))

    def finalize_if_complete(self):
        complete = len(self.rows) == len(self.trials)
        if not complete:
            if self.receipt_file.exists() or self.frozen_file.exists():
                raise ValueError("Frozen receipt exists but the click ledger is incomplete")
            return
        data = self.click_file.read_bytes()
        receipt = {"manifest_sha256": self.manifest_sha256, "protocol_sha256": self.protocol_sha256,
                   "completed": len(self.rows), "clicks_sha256": digest(data)}
        if self.receipt_file.exists():
            recorded = json.loads(self.receipt_file.read_bytes())
            if recorded != receipt or self.frozen_file.read_bytes() != data:
                raise ValueError("Archived frozen responses changed")
            return
        if self.frozen_file.exists() and self.frozen_file.read_bytes() != data:
            raise ValueError("An existing click snapshot differs from the completed ledger")
        atomic_write(self.frozen_file, data)
        atomic_write(self.receipt_file, (json.dumps(receipt, indent=2) + "\n").encode())

    def public_state(self):
        with self.lock:
            total = len(self.trials)
            answered = len(self.rows)
            state = {"completed": answered == total, "total": total,
                     "answered": answered, "session": self.manifest_sha256}
            if answered < total:
                trial = self.trials[answered]
                state.update({"trial": trial["trial"], "width": trial["width"], "height": trial["height"],
                              "cue_lines": trial["cue"]["lines"], "image": f"/image/{trial['trial']}.png",
                              "instruction": self.manifest.get("operator_instruction", DEFAULT_INSTRUCTION)})
            return state

    def record(self, payload):
        with self.lock:
            if len(self.rows) == len(self.trials):
                self.finalize_if_complete()
                raise StaleResponse
            trial = self.trials[len(self.rows)]
            validate_response(payload, trial)
            row = {"trial": trial["trial"], "response": payload["response"],
                   "x": payload.get("x"), "y": payload.get("y"),
                   "recorded_at_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds")}
            candidate = [*self.rows, row]
            self.write_clicks(candidate)
            self.rows = candidate
            self.cached_image = None
            self.finalize_if_complete()

    def current_png(self, path):
        with self.lock:
            if len(self.rows) == len(self.trials):
                return None
            trial = self.trials[len(self.rows)]
            if path != f"/image/{trial['trial']}.png":
                return None
            if self.cached_image is None:
                self.cached_image = self.decode_image(trial)
            return self.cached_image

    def decode_image(self, trial):
        if self.source == "dummy":
            encoded = (self.image_dir / trial["entry_file"]).read_bytes()
        else:
            with ZipFile(ARCHIVES / trial["archive"]) as archive:
                member = archive.getinfo(trial["entry_file"])
                if f"{member.CRC:08x}" != trial["entry_crc32"]:
                    raise ValueError("Frozen RGB source changed")
                encoded = archive.read(member)
        with Image.open(io.BytesIO(encoded)) as source:
            rgb = source.convert("RGB")
        if rgb.size != (trial["width"], trial["height"]) or digest(rgb.tobytes()) != trial["rgb_pixels_sha256"]:
            raise ValueError("Displayed pixels do not match the frozen RGB")
        output = io.BytesIO()
        rgb.save(output, "PNG")
        return output.getvalue()


class Handler(BaseHTTPRequestHandler):
    def __init__(self, *args, collection, **kwargs):
        self.collection = collection
        super().__init__(*args, **kwargs)

    def reply(self, status, data, kind="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def reply_json(self, status, state):
        self.reply(status, json.dumps(state).encode())

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/":
            self.reply(HTTPStatus.OK, (STUDY / "collector.html").read_bytes(), "text/html; charset=utf-8")
        elif path == "/api/current":
            self.reply_json(HTTPStatus.OK, self.collection.public_state())
        elif path.startswith("/image/"):
            data = self.collection.current_png(path)
            if data is None:
                self.reply_json(HTTPStatus.NOT_FOUND, {"error": "Image unavailable"})
            else:
                self.reply(HTTPStatus.OK, data, "image/png")
        else:
            self.reply_json(HTTPStatus.NOT_FOUND, {"error": "Page unavailable"})

    def do_POST(self):
        if urlsplit(self.path).path != "/api/response":
            self.reply_json(HTTPStatus.NOT_FOUND, {"error": "Page unavailable"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 1024 or self.headers.get_content_type() != "application/json":
                raise ValueError("Invalid response body")
            payload = json.loads(self.rfile.read(size))
            self.collection.record(payload)
        except StaleResponse:
            self.reply_json(HTTPStatus.CONFLICT, self.collection.public_state())
        except (ValueError, UnicodeError):
            self.reply_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid response"})
        else:
            self.reply_json(HTTPStatus.OK, self.collection.public_state())

    def log_message(self, fmt, *args):
        return


def serve(directory, manifest, port, open_browser):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".collector.lock").open("a") as lockfile:
        try:
            fcntl.flock(lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise SystemExit("The collector is already open for this click file.") from error
        collection = Collection(directory, manifest)
        handler = partial(Handler, collection=collection)
        with ThreadingHTTPServer(("127.0.0.1", port), handler) as server:
            url = f"http://127.0.0.1:{server.server_port}/"
            print(f"Collector available at {url}", flush=True)
            if open_browser:
                webbrowser.open(url)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", help="Open the local page in the default browser")
    parser.add_argument("--directory", type=Path, default=STUDY)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    serve(args.directory, args.manifest or pilot_manifest(args.directory), args.port, args.open)


if __name__ == "__main__":
    main()

import assert from "node:assert/strict";
import {spawn, spawnSync} from "node:child_process";
import {createHash} from "node:crypto";
import {mkdtemp, readFile, rm} from "node:fs/promises";
import {tmpdir} from "node:os";
import {join} from "node:path";
import {fileURLToPath} from "node:url";
import {once} from "node:events";

const study = fileURLToPath(new URL(".", import.meta.url));
const python = process.env.PILOT_TEST_PYTHON ?? ".venv/bin/python";
const chrome = process.env.PILOT_TEST_CHROME ?? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const work = await mkdtemp(join(tmpdir(), "potato-click-browser-test-"));
let collector, browser, socket;
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

async function until(check, description) {
  const expiry = Date.now() + 10000;
  while (Date.now() < expiry) {
    try {
      const result = await check();
      if (result) return result;
    } catch (_) {}
    await pause(60);
  }
  throw new Error("Timed out waiting for " + description);
}

async function launch(port) {
  const child = spawn(python, [join(study, "collector.py"), "--directory", work,
                              "--manifest", join(work, "trial_manifest.json"), "--port", String(port)],
                      {stdio: ["ignore", "pipe", "inherit"]});
  collector = child;
  const address = await Promise.race([
    once(child.stdout, "data").then(([line]) => line.toString().match(/http:\/\/127\.0\.0\.1:\d+\//)?.[0]),
    once(child, "exit").then(([code]) => {throw new Error("Collector exited " + code);}),
  ]);
  assert.ok(address);
  return address;
}

let sequence = 1;
const pending = new Map();
function cdp(method, params = {}) {
  const id = sequence++;
  return new Promise((resolve, reject) => {
    pending.set(id, {resolve, reject});
    socket.send(JSON.stringify({id, method, params}));
  });
}
async function evaluate(expression) {
  const response = await cdp("Runtime.evaluate", {expression, returnByValue: true});
  if (response.exceptionDetails) throw new Error(response.exceptionDetails.text);
  return response.result.value;
}

async function fit(width, height) {
  await cdp("Emulation.setDeviceMetricsOverride", {width, height, deviceScaleFactor: 2, mobile: false});
}

async function ready(trial) {
  await until(() => evaluate(
    `document.querySelector("#progress")?.textContent === "${trial} of 3" &&
      document.querySelector("#photo")?.getAttribute("aria-disabled") === "false"`),
  "displayed trial " + trial);
}

async function click(x, y, clickCount = 1) {
  await cdp("Input.dispatchMouseEvent", {type: "mousePressed", x, y, button: "left", clickCount});
  await cdp("Input.dispatchMouseEvent", {type: "mouseReleased", x, y, button: "left", clickCount});
}

async function boxFor(selector) {
  return evaluate(`document.querySelector("${selector}").getBoundingClientRect().toJSON()`);
}

function csvRecords(text) {
  return text.trimEnd().split("\n").slice(1).map(row => row.split(","));
}

try {
  const setup = spawnSync(python, ["-c", `
from hashlib import sha256
import json
from pathlib import Path
import sys
from PIL import Image, ImageDraw
work, study = map(Path, sys.argv[1:])
trials = []
for i, (w,h) in enumerate([(320,200),(1280,640),(300,180)],1):
    path = f"dummy_{i}.png"
    img = Image.new("RGB", (w,h), (35, 58, 72))
    draw = ImageDraw.Draw(img)
    draw.ellipse((w//4,h//4,3*w//4,3*h//4), fill=(203,165,120))
    img.save(work/path)
    trials.append({"trial":i,"entry_file":path,"tuber":"PRIVATE_DUMMY_ID",
                   "width":w,"height":h,"rgb_pixels_sha256":sha256(img.tobytes()).hexdigest(),
                   "cue":{"lines":[[5,h//2,35,h//2],[22,h//2-8,35,h//2],
                                    [22,h//2+8,35,h//2]]}})
(work/"protocol.md").write_text("Independent dummy repeat protocol.")
(work/"trial_manifest.json").write_text(json.dumps({
    "source":"dummy","protocol_sha256":sha256((work/"protocol.md").read_bytes()).hexdigest(),
    "operator_instruction":"Dummy repeat instruction",
    "trials":trials}))
`, work, study], {stdio: "inherit"});
  assert.equal(setup.status, 0);
  const url = await launch(0);
  browser = spawn(chrome, ["--headless", "--no-first-run", "--no-default-browser-check",
                           "--disable-gpu", "--remote-debugging-port=0",
                           "--user-data-dir=" + join(work, "chrome"), "about:blank"],
                  {stdio: "ignore"});
  const debuggerPort = await until(async () =>
    (await readFile(join(work, "chrome", "DevToolsActivePort"), "utf8")).split("\n")[0], "headless Chrome");
  const targets = await (await fetch("http://127.0.0.1:" + debuggerPort + "/json/list")).json();
  socket = new WebSocket(targets.find(t => t.type === "page").webSocketDebuggerUrl);
  socket.addEventListener("message", event => {
    const message = JSON.parse(event.data);
    const handler = pending.get(message.id);
    if (!handler) return;
    pending.delete(message.id);
    if (message.error) handler.reject(new Error(JSON.stringify(message.error)));
    else handler.resolve(message.result);
  });
  await new Promise((resolve, reject) => {
    socket.addEventListener("open", resolve, {once: true});
    socket.addEventListener("error", reject, {once: true});
  });
  await fit(1450, 900);
  await cdp("Page.navigate", {url});
  await ready(1);
  assert.equal(await evaluate('document.querySelector("#instruction").textContent'), "Dummy repeat instruction");
  const state = await (await fetch(url + "api/current")).text();
  assert.equal(state.includes("PRIVATE_DUMMY_ID"), false);
  assert.equal(state.includes("dummy_1.png"), false);
  assert.equal((await fetch(url + "image/2.png")).status, 404);
  let box = await boxFor("#photo");
  assert.equal(box.width, 320);
  await click(Math.ceil(box.left + 319), Math.ceil(box.top + 199));
  await ready(2);
  const savedFirst = await readFile(join(work, "clicks.csv"), "utf8");
  assert.deepEqual(csvRecords(savedFirst)[0].slice(0, 4), ["1", "click", "319", "199"]);
  box = await boxFor("#photo");
  await click(Math.ceil(box.left + 20), Math.ceil(box.top + 20), 2);
  assert.equal(await readFile(join(work, "clicks.csv"), "utf8"), savedFirst);
  const stale = await fetch(url + "api/response", {
    method:"POST", headers:{"Content-Type":"application/json"},
    body:JSON.stringify({trial:1,response:"click",x:1,y:1}),
  });
  assert.equal(stale.status, 409);
  assert.equal(await readFile(join(work, "clicks.csv"), "utf8"), savedFirst);

  const ended = once(collector, "exit");
  collector.kill();
  await ended;
  assert.equal(await launch(Number(new URL(url).port)), url);
  await fit(800, 650);
  await cdp("Page.navigate", {url});
  await ready(2);
  box = await boxFor("#photo");
  assert.ok(box.width > 700 && box.width < 1280);
  assert.ok(Math.abs(box.width / box.height - 2) < .001);
  const x = Math.trunc(box.left + 411), y = Math.trunc(box.top + 137);
  await click(x, y);
  await ready(3);
  const beforeSkip = await readFile(join(work, "clicks.csv"), "utf8");
  assert.deepEqual(csvRecords(beforeSkip)[1].slice(0, 4),
                   ["2", "click", String(Math.floor((x-box.left) * 1280 / box.width)),
                    String(Math.floor((y-box.top) * 640 / box.height))]);
  await cdp("Page.reload", {ignoreCache: true});
  await ready(3);
  box = await boxFor("#skip");
  await click(Math.floor(box.left + box.width / 2), Math.floor(box.top + box.height / 2));
  await until(() => evaluate('document.querySelector("#status")?.textContent.includes("Collection complete")'),
              "saved completion");
  const collected = await readFile(join(work, "clicks.csv"), "utf8");
  assert.deepEqual(csvRecords(collected)[2].slice(0, 4), ["3", "cannot_identify", "", ""]);
  assert.equal(await readFile(join(work, "frozen_clicks.csv"), "utf8"), collected);
  const receipt = JSON.parse(await readFile(join(work, "click_freeze.json"), "utf8"));
  assert.equal(receipt.completed, 3);
  assert.equal(receipt.clicks_sha256, createHash("sha256").update(collected).digest("hex"));
  await cdp("Page.reload", {ignoreCache: true});
  await until(() => evaluate('document.querySelector("#status")?.textContent.includes("Collection complete")'),
              "completion after reload");
  assert.equal(await readFile(join(work, "clicks.csv"), "utf8"), collected);
  console.log("Dummy Chrome test passed: native and scaled coordinates at DPR 2, stale response, server restart, reload, skip and frozen receipt.");
} finally {
  socket?.close();
  for (const process of [browser, collector]) {
    if (process?.exitCode === null && process.signalCode === null) {
      const ended = once(process, "exit");
      process.kill();
      await ended;
    }
  }
  await rm(work, {recursive: true, force: true, maxRetries: 5});
}

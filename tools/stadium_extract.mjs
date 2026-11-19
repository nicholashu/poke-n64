#!/usr/bin/env node
/**
 * Local-only Stadium ROM to DSM3 pack bridge.
 *
 * Executes the upstream inspector's compiled extraction worker using the
 * same approach as its scripts/rom-self-test.mjs. No source code, models
 * or ROM bytes are copied into this repository.
 *
 * Usage: node tools/stadium_extract.mjs INSPECTOR ROM SPECIES OUT
 */
import { readFile, readdir, writeFile, mkdir } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const nodeProcess = globalThis.process;
const [inspectorPath, romPath, speciesString, outputPath] = nodeProcess.argv.slice(2);
const species = Number(speciesString);

if (!inspectorPath || !romPath || !outputPath || !Number.isInteger(species) ||
    species < 1 || species > 151) {
  nodeProcess.stderr.write(
    "Usage: node tools/stadium_extract.mjs <inspector> <stadium ROM> <species 1..151> <out.dsm>\n",
  );
  nodeProcess.exit(2);
}

try {
  const assetsPath = resolve(inspectorPath, "dist", "assets");
  const workerFiles = (await readdir(assetsPath))
    .filter((name) => name.startsWith("romWorker-") && name.endsWith(".js"));
  if (workerFiles.length !== 1) {
    throw new Error("Expected one compiled inspector romWorker-*.js; run npm run build");
  }

  const rom = await readFile(romPath);
  let latest;
  globalThis.self = {
    postMessage(message) { latest = message; },
  };

  // Upstream's Fengari worker is browser-targeted and expects process to
  // be absent at module initialization, as demonstrated by its self-test.
  globalThis.process = undefined;
  await import(pathToFileURL(join(assetsPath, workerFiles[0])).href);

  function send(data) {
    latest = undefined;
    globalThis.self.onmessage({ data });
    if (latest?.type === "error") {
      throw new Error(latest.message || "Stadium model extraction failed");
    }
    return latest;
  }

  const ready = send({
    type: "open",
    bytes: rom.buffer.slice(rom.byteOffset, rom.byteOffset + rom.byteLength),
  });
  if (ready?.type !== "ready" || !Array.isArray(ready.species) ||
      !ready.species.includes(species)) {
    throw new Error("Stadium ROM was not accepted by the inspector's extractor");
  }

  const result = send({ type: "build", requestId: 1, species });
  if (result?.type !== "built" || result.requestId !== 1 ||
      result.species !== species || !(result.bytes instanceof ArrayBuffer)) {
    throw new Error("Stadium model builder did not return the requested species");
  }
  const data = new Uint8Array(result.bytes);
  if (data.length < 24 ||
      String.fromCharCode(...data.subarray(0, 4)) !== "DSM3") {
    throw new Error("Unexpected or truncated DSM3 model pack");
  }

  // The Python exporter validates the complete mesh, textures and hierarchy.
  await mkdir(dirname(outputPath), { recursive: true });
  await writeFile(outputPath, data);
  nodeProcess.stdout.write(
    "Built local DSM3 species " + species + ": " + data.byteLength +
    " bytes -> " + outputPath + "\n",
  );
} catch (error) {
  nodeProcess.stderr.write("Stadium extractor failed: " +
    (error.message || error) + "\n");
  nodeProcess.exitCode = 1;
} finally {
  globalThis.process = nodeProcess;
}

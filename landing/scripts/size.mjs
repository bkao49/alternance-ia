// Vérifie que le JavaScript du build reste sous 500 Ko une fois compressé (gzip).
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { gzipSync } from "node:zlib";

const LIMIT = 500 * 1024;
const dir = "dist/assets";
const total = readdirSync(dir)
  .filter((f) => f.endsWith(".js"))
  .reduce((sum, f) => sum + gzipSync(readFileSync(join(dir, f))).length, 0);
console.log(`JavaScript compressé : ${(total / 1024).toFixed(1)} Ko (limite ${LIMIT / 1024} Ko)`);
if (total > LIMIT) process.exit(1);

// Writes dist/staticwebapp.config.json with the backend origin filled into the
// CSP connect-src. The origin comes from VITE_API_URL, the same value the
// bundle was built with, so the CSP can never drift from the real API.
import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

const apiUrl = process.env.VITE_API_URL;
if (!apiUrl) {
  console.error("VITE_API_URL is required (for example https://api.example.com)");
  process.exit(1);
}

let origin;
try {
  const parsed = new URL(apiUrl);
  const isLocal = parsed.hostname === "localhost" || parsed.hostname === "127.0.0.1";
  if (parsed.protocol !== "https:" && !isLocal) {
    throw new Error("must be https");
  }
  origin = parsed.origin;
} catch {
  console.error("VITE_API_URL must be an https URL");
  process.exit(1);
}

const template = readFileSync(resolve("staticwebapp.config.json"), "utf8");
if (!template.includes("__API_ORIGIN__")) {
  console.error("staticwebapp.config.json has no __API_ORIGIN__ placeholder");
  process.exit(1);
}
const rendered = template.split("__API_ORIGIN__").join(origin);
JSON.parse(rendered); // fail loudly if the result is not valid JSON
writeFileSync(resolve("dist", "staticwebapp.config.json"), rendered);
console.log("Wrote dist/staticwebapp.config.json for " + origin);

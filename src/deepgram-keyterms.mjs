import { readFile } from "node:fs/promises";

const DEFAULT_CONFIG_URL = new URL(
  "../config/deepgram-keyterms.json",
  import.meta.url,
);

export async function loadKeytermConfig(configUrl = DEFAULT_CONFIG_URL) {
  const contents = await readFile(configUrl, "utf8");
  return JSON.parse(contents);
}

export function collectKeyterms(config, categoryNames) {
  const categories = config.categories ?? {};
  const selectedNames = categoryNames?.length
    ? categoryNames
    : Object.keys(categories);
  const unknownNames = selectedNames.filter((name) => !(name in categories));

  if (unknownNames.length > 0) {
    throw new Error(`Unknown keyterm categories: ${unknownNames.join(", ")}`);
  }

  const keyterms = selectedNames.flatMap((name) => categories[name]);
  const uniqueKeyterms = [...new Set(keyterms)];

  if (uniqueKeyterms.length !== keyterms.length) {
    throw new Error("Deepgram keyterms must be unique across selected categories");
  }

  if (uniqueKeyterms.some((keyterm) => typeof keyterm !== "string" || !keyterm.trim())) {
    throw new Error("Every Deepgram keyterm must be a non-empty string");
  }

  if (uniqueKeyterms.length > config.max_keyterms) {
    throw new Error(
      `Selected ${uniqueKeyterms.length} keyterms; Deepgram allows at most ${config.max_keyterms}`,
    );
  }

  return uniqueKeyterms;
}

export function buildKeytermQuery(keyterms) {
  const params = new URLSearchParams();

  for (const keyterm of keyterms) {
    params.append("keyterm", keyterm);
  }

  return params.toString();
}

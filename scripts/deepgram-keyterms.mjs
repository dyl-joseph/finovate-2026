#!/usr/bin/env node

import {
  buildKeytermQuery,
  collectKeyterms,
  loadKeytermConfig,
} from "../src/deepgram-keyterms.mjs";

function parseArguments(argumentsToParse) {
  const options = { categories: [], format: "query" };

  for (let index = 0; index < argumentsToParse.length; index += 1) {
    const argument = argumentsToParse[index];

    if (argument === "--category") {
      const category = argumentsToParse[index + 1];
      if (!category) throw new Error("--category requires a category name");
      options.categories.push(category);
      index += 1;
    } else if (argument === "--format") {
      const format = argumentsToParse[index + 1];
      if (!format) throw new Error("--format requires query, json, or lines");
      options.format = format;
      index += 1;
    } else {
      throw new Error(`Unknown argument: ${argument}`);
    }
  }

  if (!["query", "json", "lines"].includes(options.format)) {
    throw new Error("--format must be query, json, or lines");
  }

  return options;
}

function formatKeyterms(keyterms, format) {
  if (format === "json") return JSON.stringify(keyterms, null, 2);
  if (format === "lines") return keyterms.join("\n");
  return buildKeytermQuery(keyterms);
}

try {
  const options = parseArguments(process.argv.slice(2));
  const config = await loadKeytermConfig();
  const keyterms = collectKeyterms(config, options.categories);
  process.stdout.write(`${formatKeyterms(keyterms, options.format)}\n`);
} catch (error) {
  process.stderr.write(`${error.message}\n`);
  process.exitCode = 1;
}

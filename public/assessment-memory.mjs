const INSTITUTION_LABELS = {
  chase: "Chase",
  paypal: "PayPal",
  bank_of_america: "Bank of America",
};

function formatInstitution(value) {
  const normalized = String(value ?? "").trim();
  if (!normalized) return "Unknown institution";
  return INSTITUTION_LABELS[normalized] ?? normalized.replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatConfidence(value) {
  const confidence = Number(value);
  if (!Number.isFinite(confidence)) return null;
  return `Match confidence ${Math.round(confidence * 100)}%`;
}

function joinInstitutions(values) {
  return (Array.isArray(values) ? values : []).filter(Boolean).map(formatInstitution).join(", ");
}

export function buildMemoryHighlights(findings = []) {
  return findings.flatMap((finding) => {
    const confidence = formatConfidence(finding.match_confidence);
    const attributes = finding.attributes ?? {};
    if (finding.kind === "repeat_flagged_speaker") {
      const institutions = joinInstitutions(attributes.prior_institutions);
      const meta = [confidence, institutions ? `Previously claimed: ${institutions}` : null]
        .filter(Boolean)
        .join(" · ");
      return [{
        kind: finding.kind,
        title: "Similar speaker pattern detected",
        detail: finding.description ?? "A similar speaker pattern appeared in a previously flagged interaction.",
        meta,
      }];
    }
    if (finding.kind === "identity_switch") {
      const prior = joinInstitutions(attributes.prior_institutions);
      const current = joinInstitutions(attributes.current_institutions);
      const meta = [
        confidence,
        prior ? `Previously: ${prior}` : null,
        current ? `Now: ${current}` : null,
      ].filter(Boolean).join(" · ");
      return [{
        kind: finding.kind,
        title: "Institution identity changed across interactions",
        detail: finding.description ?? "The similar speaker pattern previously claimed a different institutional identity.",
        meta,
      }];
    }
    return [];
  });
}

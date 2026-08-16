# Finovate 2026 Planning

## Executive recommendation

Build a **Financial Scam Intelligence Layer** for banks and payment providers.

The product should not be positioned as another generic AI scam-call detector. Its defensible idea is to connect:

- What a caller says
- What the caller is asking the customer to do
- What is actually happening in the customer’s financial account
- What scam patterns have appeared across previous encounters

The one-sentence pitch is:

> We help banks stop socially engineered payments by connecting live conversation evidence with real account behavior—and remembering scam patterns across encounters.

The strongest MVP combines a live evidence graph, financial-context contradiction detection, scam-progression tracking, and active verification recommendations. Persistent speaker similarity should be the high-impact differentiator layered on top.

## Evaluation criteria

Ideas should be judged on:

1. Novelty and defensibility
2. Finance-specific value
3. Demo impact
4. Hackathon feasibility
5. Explainability and customer trust
6. Potential enterprise customer and business model

## Evaluation of current ideas

| Idea | Novelty | Demo impact | Build difficulty | Recommendation |
| --- | ---: | ---: | ---: | --- |
| Call forwarding/proxy number | Low–medium | High | High | Use as the delivery mechanism, not the core innovation |
| Live scam evidence graph | High | Very high | Medium | Make this the core product |
| Persistent speaker re-identification | Very high | Very high | High and privacy-sensitive | Use as a secondary differentiator |
| Financial-context verification | High | Very high | Medium | Essential for finance credibility |
| Scam progression/stage detection | High | High | Medium | Include in the interface |
| Active verification agent | Medium–high | High | Low–medium | Include as the user action layer |

### 1. Call forwarding/proxy number

This makes the product feel real, but it is not by itself defensible. The difficult parts are telecom integration, call latency, consent, recording laws, and reliable streaming audio.

For the hackathon, simulate the phone layer with WebRTC or a browser-based call. Describe proxy-number deployment as the production architecture while focusing the demo on the intelligence layer.

### 2. Live evidence graph

This is the best visual and conceptual feature. Instead of showing only “Scam probability: 94%,” show the reasoning:

- Claimed identity: Chase
- Requested action: Move $2,000
- Manipulation: urgency, authority, secrecy
- Account context: new recipient, unusual amount
- Contradiction: no matching fraud event
- Recommended action: end the call and contact the bank independently

This makes the system explainable to customers, bankers, compliance teams, and judges.

### 3. Persistent speaker re-identification

The differentiator is longitudinal intelligence:

> The system remembers scam behavior across encounters, not just within a single call.

Do not claim to prove a person’s identity. Use language such as:

> A similar voice pattern appeared in a previous flagged interaction.

Safeguards:

- Store voice embeddings rather than raw recordings when possible.
- Use confidence thresholds and human-readable uncertainty.
- Never automatically block a caller based only on voice similarity.
- Combine voice similarity with behavior, account context, and transaction signals.

### 4. Financial-context verification

This is what makes the project distinctly fintech rather than a generic AI safety product.

Useful demo contradictions and risk signals:

- Caller claims there was a $900 fraudulent charge; the account has no such transaction.
- Caller requests a transfer to a new recipient.
- Requested transfer is 83% of available liquid funds.
- Caller asks the customer to bypass normal bank authentication.
- Caller’s instructions conflict with the bank’s actual fraud workflow.

Use a simulated, read-only account with realistic transactions. Do not connect to real bank accounts during the competition.

### 5. Scam progression detection

Represent a scam as a sequence:

1. Identity claim
2. Credibility claim
3. Threat or urgency
4. Isolation request
5. Financial action
6. Transfer or credential request

The risk score should increase as the sequence develops. This creates a compelling live demonstration and clearly shows why the product is more than transcription plus an LLM prompt.

### 6. Active verification agent

Detection becomes prevention when the product recommends a safe next action:

- Ask the caller for the last four digits of the disputed transaction.
- Do not use the phone number provided by the caller.
- Hang up and call the official number on the customer’s card.
- Pause the transfer for 30 minutes while the recipient is verified.
- Contact a trusted person before proceeding.

The system should create a safe pause rather than argue with the customer or make irreversible decisions.

## Recommended product architecture

```text
LIVE AUDIO
    ↓
Streaming ASR
    ↓
Speaker diarization ───────→ Speaker similarity memory
    ↓                               ↓
Transcript and claims ───────→ Prior flagged interactions
    ↓                               ↓
Scam-stage and tactic extraction
    ↓
Evidence graph
    ↓
Financial-context verification
    ↓
Risk reasoner
    ↓
Explainable alert + verification action
```

The first version can use a browser call or prerecorded call segments. The system should stream transcript events into a structured state object and render the graph live.

## Suggested live interface

```text
LIVE RISK: 94% — HIGH

Caller claims:
Chase fraud department

Caller requests:
Transfer $2,000 to a “secure account”

Detected tactics:
Urgency · Authority · Secrecy · Isolation

Account inconsistencies:
No matching suspicious transaction
New recipient
Transfer is 78% of available balance

Prior intelligence:
Similar speaker pattern appeared in a flagged PayPal impersonation call

Recommended action:
End call. Call the number on the back of the card.
Temporarily pause transfer?
```

## Recommended demo

### Act 1: First scam call

The caller claims to be from Chase and reports suspicious activity. Risk starts moderate. As the caller creates urgency, requests secrecy, and asks for a transfer, the evidence graph fills in and risk rises.

### Act 2: Repeat encounter

Five minutes later, the same speaker calls pretending to be PayPal. Display:

> Similar speaker pattern detected from a previous flagged financial scam.

The new conversation then adds fresh evidence to the existing risk assessment.

### Act 3: Account contradiction

The caller claims there was a $900 fraudulent charge. The simulated account contains no such charge. Highlight the contradiction and recommend an independent verification path.

This gives the judges a simple story: detect, remember, verify, intervene.

## New ideas worth considering

### 1. Transfer Interruption Copilot

A safety layer for Zelle, wire, ACH, and crypto transfers. It detects combinations such as a new recipient, a large amount, a recent password reset, remote-access software, caller-induced urgency, and behavior outside the customer’s normal pattern.

Instead of simply rejecting the transaction, it explains the risk and starts a short cooling-off workflow. This may be easier to sell to banks than a phone product because it sits directly at the point of financial loss.

### 2. Trusted Contact Fraud Firewall

When a high-risk transfer is detected, the customer selects a trusted contact or banker for verification. The contact receives a neutral explanation of the unusual transaction and can independently confirm whether it is legitimate.

This directly addresses social isolation, a central tactic in elder fraud and impersonation scams.

### 3. Scam Pattern Network for Banks

A privacy-preserving intelligence network where banks share scam patterns without sharing customer data. Signals could include phone numbers, recipient accounts, wallet addresses, scam scripts, voice-pattern fingerprints, impersonated institutions, and common transaction paths.

The differentiator is cross-institution intelligence: a scammer targeting one bank can be recognized when targeting another.

### 4. Financial Second-Opinion Agent

Before a customer sends a large or unusual payment, they ask, “Does this payment make sense?” The agent reviews the transaction, recipient history, recent communications, account behavior, and stated purpose, then identifies what should be verified and whether a cooling-off period is appropriate.

This expands beyond scam calls into payments, invoices, checks, and crypto.

### 5. Real Estate Wire Fraud Sentinel

Protect mortgage disbursements, escrow payments, and changed wiring instructions. Detect last-minute instruction changes, lookalike domains, pressure to act immediately, mismatches between known parties and payment details, and requests to bypass title-company procedures.

This is a credible vertical extension because real estate wire fraud has a clear financial impact and an easy-to-understand demo.

### 6. AI Invoice and Vendor Impersonation Detector

For small businesses and finance teams, compare new invoices with historical vendor behavior, detect changed bank details and unusual urgency, identify suspicious domains, verify request provenance, and require out-of-band confirmation before payment.

This aligns well with CFO, finance forecasting, banking, and private-equity interests.

## Judge-specific presentation strategy

### Banking and finance judges

For David Yan, Du Chun, Lucas Yang, and Monica Li, emphasize:

- Fraud loss reduction
- Explainability
- Integration with existing bank workflows
- False-positive management
- Customer trust
- Human escalation
- Audit trails
- Account-level risk signals

Answer the question “Where would this fit in a bank?” with: call-center systems, digital-banking payment flows, fraud operations, and banker-assisted customer support.

### Private equity and investment judges

For Ning So, Jessie Hernandez, and Kelvin Xu, emphasize:

- Large and growing fraud problem
- Clear initial customers: banks and payment providers
- Enterprise SaaS or per-account pricing
- Defensibility from cross-conversation intelligence
- Distribution through banks, fintechs, and telcos
- Expansion from scam calls into payments, invoices, and wire fraud

Do not pitch it only as a consumer app. The stronger business is infrastructure sold to financial institutions.

### Real estate judges

For Angela Chen and Songmei Wang, show the real-estate wire-fraud extension:

> The same evidence graph can protect mortgage disbursements, escrow payments, and changed wiring instructions.

### Education-focused judge

For Ivy Sun, emphasize financial literacy and prevention:

- Explain why the request is suspicious.
- Teach customers which tactics scammers use.
- Provide guided verification.
- Offer family or caregiver modes.
- Use the system as a training simulator for students, bank employees, and older adults.

### Finance professor

For Dr. Liping Ma, frame the research contribution precisely:

> Our contribution is not scam classification. It is longitudinal, explainable fraud reasoning across conversations, behavioral tactics, and financial state.

Evaluation metrics to mention:

- Scam detection precision and recall
- Time-to-warning
- False-positive rate
- Accuracy of scam-progression detection
- Accuracy of account-claim contradiction detection
- Intervention acceptance rate

## Business model and expansion

Initial customers should be banks, payment providers, and fraud-operations teams. Potential pricing models include per monitored account, per protected transaction, or enterprise platform licensing.

Expansion path:

1. Scam-call intelligence
2. Payment-interruption workflows
3. Invoice and vendor impersonation
4. Real-estate wire protection
5. Cross-institution scam intelligence

The long-term moat is the combination of longitudinal scam patterns, financial context, explainable reasoning, and workflow integration—not merely the underlying speech-to-text model.

## Risks and safeguards

### Privacy and consent

Clearly disclose call analysis, minimize retained audio, encrypt sensitive data, and prefer embeddings and extracted events over raw recordings.

### False positives

Never block or accuse someone based on a single signal. Use calibrated confidence, show evidence, and allow customer or banker review.

### Voice similarity misuse

Describe results as similarity or recurrence, not identity proof. Make it one feature in a larger risk model.

### Regulatory and legal concerns

Avoid presenting the hackathon prototype as production-ready legal or financial advice. Explain that deployment would require review of call-recording consent, privacy, model governance, accessibility, and bank-specific controls.

### Security

Use synthetic accounts, synthetic calls, and fake recipients in the demo. Keep the prototype read-only and separate from real credentials or payment rails.

## MVP priority order

1. Live evidence graph
2. Financial-context contradiction detection
3. Scam-progression model
4. Active verification recommendations
5. Persistent speaker similarity
6. Proxy-number or telecom integration

If time is limited, ship the first four. They provide the strongest finance story with less implementation and privacy risk. Add speaker similarity only after the main evidence flow is reliable.

## Final recommendation

Build the Financial Scam Intelligence Layer and present persistent cross-encounter speaker similarity as the memorable differentiator. The product should be sold as bank and payment infrastructure that prevents socially engineered payments, not as a standalone consumer call-blocking app.

The winning demo should show the system detecting a scam, explaining why it is risky, finding a contradiction in simulated account data, recognizing a repeat scam pattern, and recommending a safe verification action.

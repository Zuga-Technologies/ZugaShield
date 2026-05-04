Actions that need review or testing by Buga:

Verify all claims for ZugaShields Performance 

 **Zero dependencies** — works out of the box, no C extensions
- **< 15ms overhead** — compiled regex fast path, async throughout
- **150+ signatures** — curated threat catalog with auto-updating threat feed
- **MCP-aware** — scans tool definitions for hidden injection payloads
- **7 defense layers** — defense in depth, not a single point of failure
- **Auto-updating** — opt-in signature feed pulls new defenses from GitHub Releases

Checking on the OWASP LLM Top 10 Mapping:

We are missing LLM03 (Training Data Poisoning): Claude recommends

 This is consistent with ZugaShield's design as a runtime/inference-time security layer. Training data poisoning is a
  pre-training threat — by the time ZugaShield is active, the model is already trained and deployed. There's nothing a
  runtime shield can do to detect or undo poisoned training data.

  If defending against training data poisoning is a requirement for your use case, you'd need to look at separate
  tooling focused on:
  - Data curation pipelines (validating training datasets before they're used)
  - Model evaluation/red-teaming (detecting behavioral anomalies post-training)
  - Supply chain verification (ensuring pretrained base models are from trusted sources)

For LLM09 (Overreliance): Claude recommends 

 Addressing LLM09 requires solutions at the UX, policy, and workflow level — things like:
  - Displaying confidence disclaimers in the UI
  - Requiring human sign-off for high-stakes outputs
  - Training users on LLM limitations
  - Building validation steps into business processes

  These are outside what a technical guardrail library can realistically enforce.

  For LLM10 (Model Theft): Claude recommends 

    Defending against LLM10 requires controls at the platform/infrastructure level, such as:
  - Strict API authentication and rate limiting
  - Monitoring for systematic extraction queries (model inversion attacks)
  - Limiting response detail to prevent reconstruction
  - Legal protections and terms of service enforcement

  These are platform-owner responsibilities, not something a client-side or middleware security library like ZugaShield
  can enforce.

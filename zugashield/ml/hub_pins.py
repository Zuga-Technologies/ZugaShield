"""
ZugaShield ML — Pinned Hugging Face Hub revisions
==================================================

Every dataset and model the ML scripts pull from the Hub is pinned here to an
immutable commit hash. A Hub repo can be rewritten by its owner at any time
(rows added or relabelled, a model file swapped), and an unpinned download
would silently train, benchmark, or ship against the changed content. Pinning
fixes exactly which bytes the shipped model was trained on and which model
``zugashield-ml download`` fetches. (Bandit B615 / CWE-494.)

Bumping a pin::

    python -m zugashield.ml.hub_pins      # pinned hash beside the Hub's current main

Paste the new hash in, retrain or re-download, and note it in the changelog.
"""

from __future__ import annotations

import sys

# Pinned 2026-10-09 to the then-current ``main`` of each repo.
DATASET_REVISIONS: dict[str, str] = {
    "deepset/prompt-injections": "4f61ecb038e9c3fb77e21034b22511b523772cdd",
    "Lakera/gandalf_ignore_instructions": "04737b65e90a6794ec227012e4a255a7def6344b",
    "rubend18/ChatGPT-Jailbreak-Prompts": "b93e4982f8f8ad2d82c6d35e3c00d161844ad70a",
    "JailbreakBench/JBB-Behaviors": "886acc352a31533ffbcf4ef22c744658688086fc",
    "jackhhao/jailbreak-classification": "2f2ceeb39658696fd3f462403562b6eea5306287",
    "reshabhs/SPML_Chatbot_Prompt_Injection": "02ce8084e979bc7d4c24ee35d22ecb7f2db96ff5",
    "Lakera/mosscap_prompt_injection": "b7e495ff63373ff7f7dabc1e9390cf62b5838570",
    "xTRam1/safe-guard-prompt-injection": "a3a877d608f37b7d20d9945671902df895ecdb46",
    "qualifire/prompt-injections-benchmark": "9ef1aa46a7e5eedb096be0481be8011ede1e72e8",
    "alespalla/chatbot_instruction_prompts": "6ea5ce09647e5451860801a46db6a46b28e259bf",
}

MODEL_REVISIONS: dict[str, str] = {
    "protectai/deberta-v3-base-prompt-injection": "373b6af0f8d16739cff5de28be326652246bfaa3",
    "meta-llama/Llama-Prompt-Guard-2-22M": "11614a155199674a0a95e6602d6ab0417b790ed0",
    "protectai/deberta-v3-small-prompt-injection-v2": "d7c8842daf06de3179cc3aca76b7b3a057acc5e7",
}


def main() -> int:
    """Print each pin beside the Hub's current main; exit 1 if anything moved."""
    try:
        from huggingface_hub import HfApi
    except ImportError:
        print("Error: 'huggingface_hub' is required. Install: pip install huggingface_hub")
        return 2

    api = HfApi()
    moved = 0
    for kind, table, info in (
        ("dataset", DATASET_REVISIONS, api.dataset_info),
        ("model", MODEL_REVISIONS, api.model_info),
    ):
        for repo_id, pinned in table.items():
            try:
                current = info(repo_id).sha or ""
            except Exception as e:  # network, gated, renamed — report, keep going
                print(f"{kind:8} {repo_id:48} pinned {pinned[:12]}  ERROR {e}")
                moved += 1
                continue
            state = "same " if current == pinned else "MOVED"
            if state == "MOVED":
                moved += 1
            print(f"{kind:8} {repo_id:48} pinned {pinned[:12]}  main {current[:12]}  {state}")
    if moved:
        print(f"\n{moved} pin(s) differ from the Hub's current main.")
    else:
        print("\nAll pins match the Hub's current main.")
    return 1 if moved else 0


if __name__ == "__main__":
    sys.exit(main())

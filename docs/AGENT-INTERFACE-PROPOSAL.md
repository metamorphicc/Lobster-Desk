# Agent interface proposal

Recommended direction: **The committee** — a compact decision desk, with personality in the names and writing rather than illustrated characters.

## 1. The committee — recommended

Three aligned columns: Clawdius / market analysis, Pinch / risk review, Ledger / capital and execution. Each contains a precise status and one short recorded rationale. A full-width verdict beneath them explains the current outcome. On phones the columns become a vertical sequence.

Use restrained orange for the current step, green only for recorded approval and red for an actual veto. Quiet borders, deliberate spacing, and no aquarium background, pseudo-3D mascots, animated faces or random movement. Show recorded summaries rather than private chain-of-thought. New decisions can enter with a brief opacity transition; respect reduced motion.

The standalone [interface study](AGENT-INTERFACE-CONCEPT.html) illustrates waiting, reviewing, approved and vetoed states. Its examples are explicitly labelled design material, have no live metrics and cannot execute a trade. It is not installed in the product.

## 2. Decision rail

A narrow horizontal progress line: Market → Strategy → Risk → Capital → Execution. Selecting a completed step reveals its recorded rationale. Best when the BTC chart should dominate the screen. On mobile use a vertical rail, not a horizontally scrolling label strip. This is clearer about process but has less character.

## 3. Live notebook

A journal of concise signed entries: author, role, recorded time, verdict and rationale. A pinned verdict stays above the latest discussion. Best for spectators who want to follow debate. It needs bounded history and manual “Load earlier” rather than an endlessly moving feed.

## Data contract for eventual integration

Keep reviewed, authorized, submitted, filled and protected states distinct. Only observed fills may produce an “Executed” verdict. A risk veto cannot be overridden by a later model message. Missing observations show a waiting/unavailable state; animations never manufacture activity. Old review results must remain labelled historical when execution data is stale. The current character artwork remains out of the product until the owner chooses a direction.

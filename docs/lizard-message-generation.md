# Lizard message generation — design note

Status: proposed, nothing built. Written 2026-08-14.

Two separate problems, one of which we were about to solve the wrong
layer of.

## The problem

Bryan's diagnosis: the messages "feel tacked on with tape. They don't
flow." He's right, and it's structural rather than a content quality
issue.

`render_survival` assembles up to five independently-sampled parts —
opener, body, victim clause, aside, offline fragment — and joins them
with `" ".join(parts)`. Each fragment is authored as a complete
sentence with its own terminal punctuation, so concatenation can only
ever produce a list of sentences. Flow lives in the joins, and the
joiner is a space.

Real output, `clinical`:

> Negative discharge. Recalibrating. Streak 10. The lizard is
> submitting a variance report. insanebot22 set a timer for this. To an
> empty room. The lizard is almost touched. bardLizard

Four independent thoughts, and the voice changes partway through: it
opens clinical and closes sentimental. That last part is
`_offline_fragment(ctx)`, which draws from a single pool shared across
every mood — so a wistful three-beat closer gets stapled onto a
clinical opener. It is the worst offender and it always lands last.

Deaths read better (`694. The lizard didn't even bother picking up the
gun this time, Shinrin_Cole.`) because that path is effectively two
parts with a natural closer in the countdown. Survivals have no closer
discipline at all.

Measured, spoonee, n=1765 survivals: median 129 chars. Length isn't the
problem — those 129 characters are five or six complete thoughts.

Note that `flows` (body and clause authored *together*, gated by
`FLOW_CHANCE`) already exists and is the right idea. It's wired to
exactly one seam. This note is largely "do that everywhere."

## Part 1 — templates own structure, slots own voice

Move the unit of authorship up. A template is one authored sentence
shape, including its punctuation and how its clauses relate. Slots hold
per-mood vocabulary.

```
TEMPLATES["victim"] = ["{beat} {body} — unlike {victim}.",
                       "{beat} {body}, and {victim} didn't."]

BORED = {"beat": ["*click*", "Empty.", "yeah.", "again.", "mhm."],
         "body": ["$(user) lives", "$(user) survives",
                  "$(streak) in a row for $(user)"],
         "tag":  ["Whatever.", "Cool.", "Sure.", "Riveting."]}
```

Prototyped with existing `bored` fragments, nothing newly written:

> mhm. insanebot22 survives — riveting.
> yeah. insanebot22 survives, to an empty room. Whatever.
> Empty. insanebot22 lives — unlike Shinrin_Cole.

Key properties:

- **Templates are mostly shared across moods; slots are per-mood.**
  Same skeleton, different lizard. This is what keeps authoring
  tractable — an estimated 20–30 shapes total, plus two or three
  signature ones per mood, rather than hundreds.
- **Variants replace appending.** Offline and victim cases become their
  own templates instead of clauses stapled on the end. A clinical
  template never reaches for a sentimental closer, because the closer
  is written into it. This kills the tonal whiplash structurally.
- **Combinatorics improve as you add words**, not degrade as you add
  parts. 2 templates × 5 beats × 3 bodies × 4 tags = 120 grammatical
  messages from the sample above.
- **Whoever owns the punctuation owns the flow.** The prototype's first
  draft left periods out of the templates and immediately produced
  "survives Riveting." That failure is the thesis in miniature.

Existing content survives the move: openers → beats, bodies → bodies,
clauses → template variants, `flows` entries are already templates in
all but name.

## Part 2 — precompute instead of JIT

Bryan's framing: find procedural time to process messages without
sacrificing response time, and accept that for the heavy players the
work won't be wasted.

The data is unusually favourable (spoonee, 3,638 plays, 72 players):

| measure | value |
|---|---|
| top 10% of players (7) | **89% of plays** |
| top 25% (18) | 95% of plays |
| top 3 players | 83% of plays |
| median gap between one player's plays | **34 minutes** |
| gaps under 10 minutes | 0% |

Ten players × two outcome branches is ~20 cached messages covering
roughly 90% of invocations, with a half-hour of lead time. This is
chess-engine pondering: think on the opponent's clock.

**Pipeline.** For a likely-next player, predict both branch contexts
(survival → streak+1; death → deaths+1 — both knowable), do the
expensive generation for each, cache in Redis keyed by
`(channel, user, outcome)`. At play time: verify assumptions, bind
volatile slots, send.

**Context volatility is the one real constraint.** Message inputs move
at different rates:

- stable until *they* play: `$(user)`, `$(streak)`, `$(deaths)`
- volatile, changes when *anyone* dies: `$(victim)`
- volatile: bullets loaded, `is_live`, `$(chemical)`

With a 34-minute gap and a ~16% death rate, the victim will often
change between generation and use. **Fix: precompute the message with
volatile tokens left unsubstituted.** `_substitute` already runs last,
so it is the late-binding mechanism — cache the rendered structure and
voice, bind `$(victim)` at send. Structure and voice are the expensive,
stable part.

**Fallback.** If cached assumptions don't hold at play time (gun got
loaded, stream ended, no cache entry), fall through to today's JIT
path. This can never be worse than current behaviour.

**Invalidation.** Consume-on-use; regenerate after the player plays,
on stream on/off, and when bullets load.

**Storage.** Redis, per the state-durability rule — same as cooldowns,
bullets, victim, recency. Survives deploys.

**What the lead time buys.** Generate N candidates and keep the best by
some scoring; multi-pass refinement; checking a message doesn't repeat
recent *structure* rather than just recent fragments. It also changes
the economics of an LLM in the loop — twenty entries refreshed
half-hourly is ~40 calls/hour, not one per play. Bryan's objection was
to JIT LLM, and this isn't that. Still his call; nothing here assumes
it.

## Sequencing

Templates first. Precomputing today's concatenative output would just
cache tape. Templates define what a good message is; precompute buys
the budget to choose among good ones.

## Open questions

- How many shapes per mood, and which are shared vs signature? This is
  the real cost of Part 1, and it is authoring, not code.
- Does mood govern structure at all, or only vocabulary? Current
  instinct: mostly vocabulary, with a couple of signature shapes each.
- Which player does the precompute warmer target — everyone off
  cooldown, or a top-N by recent play count?
- Death messages have `timeout_first` variants that change send order.
  Precompute must carry that flag with the cached message.

## Out of scope

Writing new lizard voice. The lizard's language is a creative artifact
with community-verified idiom in it (see the lexicon memory); the work
here is the assembly that stops good lines being ruined, not
mass-producing lines. Templates get re-shelved from existing content;
new voice is Bryan's.

## Evaluation

Read them. This is a craft problem, and the chat-velocity analysis that
started this thread turned out to be measuring the wrong layer — mood
selection, when the flaw was in composition. A hundred freshly rendered
samples and a human ear beats a metric here. (For the record, that
analysis also found mood assignment is context-dependent, so
observational engagement data can't attribute causation without
randomised exploration. If mood weighting ever comes back, it needs an
exploration arm and a floor to stop the distribution collapsing onto
one mood — variety is the point.)

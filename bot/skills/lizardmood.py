"""Lizard mood engine — personality system for lizardroulette."""

from __future__ import annotations

import logging
import random
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger("bot")


# ---------------------------------------------------------------------------
# Core types
# ---------------------------------------------------------------------------


class Mood(Enum):
    THEATRICAL = "theatrical"
    BORED = "bored"
    IMPRESSED = "impressed"
    SMUG = "smug"
    CLINICAL = "clinical"
    GLEEFUL = "gleeful"
    DEADPAN = "deadpan"


@dataclass(frozen=True)
class MoodContext:
    """Everything the mood engine needs to compute weights and render."""

    outcome: str  # "death" or "survival"
    deaths: int
    streak: int  # current streak (survival) or broken streak (death)
    max_streak: int
    chatter_name: str
    victim: str
    is_self_victim: bool
    bullets_loaded: bool
    chemical: str
    channel_id: str = ""


@dataclass(frozen=True)
class MoodBehavior:
    """Non-text behavior modifiers for a mood."""

    timeout_delay_multiplier: float
    countdown: str | None
    include_victim_clause: bool
    emote: str
    timeout_first: bool = False


@dataclass(frozen=True)
class MoodRoll:
    """Result of a mood roll — carries context for logging/ML training."""

    mood: Mood
    weights: dict[Mood, int]
    ctx: MoodContext


@dataclass(frozen=True)
class DeathMessage:
    """Result of render_death — message text plus behavior overrides."""

    text: str
    timeout_first: bool = False


WeightFn = Callable[[dict[Mood, int], MoodContext], dict[Mood, int]]


# ---------------------------------------------------------------------------
# Weight system
# ---------------------------------------------------------------------------

BASE_WEIGHTS: dict[Mood, int] = {
    Mood.THEATRICAL: 30,
    Mood.BORED: 10,
    Mood.IMPRESSED: 10,
    Mood.SMUG: 5,
    Mood.CLINICAL: 5,
    Mood.GLEEFUL: 5,
    Mood.DEADPAN: 5,
}


def _adjust_for_death_count(weights: dict[Mood, int], ctx: MoodContext) -> None:
    if ctx.deaths >= 100:
        weights[Mood.CLINICAL] += 25
        weights[Mood.BORED] += 20
        weights[Mood.THEATRICAL] -= 10
    elif ctx.deaths >= 50:
        weights[Mood.BORED] += 15
        weights[Mood.CLINICAL] += 10
    elif ctx.deaths >= 25:
        weights[Mood.BORED] += 8


def _adjust_for_streak(weights: dict[Mood, int], ctx: MoodContext) -> None:
    if ctx.outcome == "survival":
        if ctx.streak >= 8:
            weights[Mood.IMPRESSED] += 25
            weights[Mood.THEATRICAL] += 10
        elif ctx.streak >= 5:
            weights[Mood.IMPRESSED] += 15
    elif ctx.outcome == "death":
        if ctx.streak >= 8:
            weights[Mood.GLEEFUL] += 30
            weights[Mood.IMPRESSED] += 10
        elif ctx.streak >= 5:
            weights[Mood.GLEEFUL] += 20


def _adjust_for_bullets(weights: dict[Mood, int], ctx: MoodContext) -> None:
    if ctx.bullets_loaded:
        weights[Mood.SMUG] += 25
        weights[Mood.GLEEFUL] += 10


def _adjust_for_first_death(weights: dict[Mood, int], ctx: MoodContext) -> None:
    if ctx.outcome == "death" and ctx.deaths == 1:
        weights[Mood.THEATRICAL] += 15
        weights[Mood.IMPRESSED] += 10
        weights[Mood.BORED] = 0


MOOD_ADJUSTERS = [
    _adjust_for_death_count,
    _adjust_for_streak,
    _adjust_for_bullets,
    _adjust_for_first_death,
]


def roll_mood(
    ctx: MoodContext, weight_fn: WeightFn | None = None
) -> MoodRoll:
    """Roll for the lizard's mood, weighted by context."""
    weights = dict(BASE_WEIGHTS)
    for adjuster in MOOD_ADJUSTERS:
        adjuster(weights, ctx)
    if weight_fn:
        weights = weight_fn(weights, ctx)
    weights = {k: max(0, v) for k, v in weights.items()}
    if all(w == 0 for w in weights.values()):
        weights[Mood.THEATRICAL] = 1
    moods = list(weights.keys())
    mood_weights = [weights[m] for m in moods]
    mood = random.choices(moods, weights=mood_weights, k=1)[0]
    return MoodRoll(mood=mood, weights=weights, ctx=ctx)


# ---------------------------------------------------------------------------
# Mood behaviors
# ---------------------------------------------------------------------------

MOOD_BEHAVIORS: dict[Mood, MoodBehavior] = {
    Mood.THEATRICAL: MoodBehavior(
        timeout_delay_multiplier=1.0,
        countdown="3, 2, 1...",
        include_victim_clause=True,
        emote="LizardWithAGun",
    ),
    Mood.BORED: MoodBehavior(
        timeout_delay_multiplier=0.5,
        countdown=None,
        include_victim_clause=False,
        emote="LizardWithAGun",
    ),
    Mood.IMPRESSED: MoodBehavior(
        timeout_delay_multiplier=1.0,
        countdown="3... 2... 1...",
        include_victim_clause=True,
        emote="LizardWithAGun",
    ),
    Mood.SMUG: MoodBehavior(
        timeout_delay_multiplier=1.5,
        countdown="3, 2, 1...",
        include_victim_clause=True,
        emote="LizardWithAGun",
    ),
    Mood.CLINICAL: MoodBehavior(
        timeout_delay_multiplier=1.0,
        countdown="Timeout commencing.",
        include_victim_clause=False,
        emote="LizardWithAGun",
    ),
    Mood.GLEEFUL: MoodBehavior(
        timeout_delay_multiplier=1.2,
        countdown="THREE! TWO! ONE!",
        include_victim_clause=True,
        emote="LizardWithAGun",
    ),
    Mood.DEADPAN: MoodBehavior(
        timeout_delay_multiplier=0.3,
        countdown=None,
        include_victim_clause=False,
        emote="LizardWithAGun",
    ),
}


# ---------------------------------------------------------------------------
# Tier ranges
# ---------------------------------------------------------------------------

TierKey = tuple[int, int | None]
RARE_CHANCE = 0.03  # 3% chance to pull from the rare pool

SURVIVAL_TIER_RANGES: list[TierKey] = [
    (1, 2),
    (3, 4),
    (5, 7),
    (8, None),
]

DEATH_TIER_RANGES: list[TierKey] = [
    (1, 1),
    (2, 9),
    (10, 24),
    (25, 49),
    (50, 99),
    (100, None),
]


def _get_tier_key(tiers: list[TierKey], value: int) -> TierKey:
    """Return the tier key for the given value."""
    for tier in tiers:
        min_val, max_val = tier
        if value >= min_val and (max_val is None or value <= max_val):
            return tier
    return tiers[-1]


# ---------------------------------------------------------------------------
# Recency tracker — avoids repeating fragments within a window
# ---------------------------------------------------------------------------

RECENCY_WINDOW = 10  # remember last N fragments per channel
FLOW_CHANCE = 0.5  # probability of using a paired flow vs independent selection


class RecencyTracker:
    """Track recently used message fragments per channel to avoid repeats."""

    def __init__(self) -> None:
        self._history: dict[str, deque[str]] = {}

    def pick(self, channel_id: str, options: list[str]) -> str:
        """Pick a random option, avoiding recently used ones.

        Falls back to unfiltered random if all options are recent
        (small pool, many plays).
        """
        history = self._history.setdefault(
            channel_id, deque(maxlen=RECENCY_WINDOW)
        )
        fresh = [o for o in options if o not in history]
        choice = random.choice(fresh) if fresh else random.choice(options)
        history.append(choice)
        return choice

    def clear(self, channel_id: str | None = None) -> None:
        """Clear history. If channel_id is None, clear all."""
        if channel_id is None:
            self._history.clear()
        else:
            self._history.pop(channel_id, None)


recency = RecencyTracker()


# ---------------------------------------------------------------------------
# Ordinal helper (shared with lizardroulette tests)
# ---------------------------------------------------------------------------


def _ordinal(n: int) -> str:
    """Format an integer as an ordinal string (1st, 2nd, 3rd, 14th, etc.)."""
    if 11 <= (n % 100) <= 13:
        return f"{n}th"
    return f"{n}{['th', 'st', 'nd', 'rd', 'th'][min(n % 10, 4)]}"


# ---------------------------------------------------------------------------
# Survival message pools — per mood, per tier
# ---------------------------------------------------------------------------

MOOD_SURVIVAL: dict[Mood, dict[TierKey, dict]] = {
    # ------------------------------------------------------------------
    # THEATRICAL — the classic lizard. Dramatic, performative.
    # ------------------------------------------------------------------
    Mood.THEATRICAL: {
        (1, 2): {
            "openers": [
                "*click*",
                "The chamber was empty.",
                "...nothing happened.",
            ],
            "bodies": [
                "$(user) survives. Have some $(chemical).",
                "$(user) gets away with it. Enjoy some $(chemical).",
                "$(user) lives. Here's your $(chemical).",
            ],
            "victim_clauses": [
                "$(victim) wasn't so lucky.",
                "The lizard's still eating $(victim)...",
                "$(victim)'s seat is still warm.",
            ],
            "self_victim_clauses": [
                "Looks like the lizard shot a corpse.",
                "Wait, didn't $(user) just die?",
                "The lizard checks its notes. Weren't you just here?",
            ],
            "flows": [
                {
                    "body": "$(user) survives — unlike $(victim).",
                    "victim": "The lizard still has fresh ammunition from that one.",
                    "self_victim": "Then again, the lizard already got $(user) once today.",
                },
                {
                    "body": "$(user) lives. $(chemical) dispensed.",
                    "victim": "$(victim) didn't get any $(chemical). $(victim) got the gun.",
                    "self_victim": "Last time, $(user) got the gun instead.",
                },
            ],
        },
        (3, 4): {
            "openers": [
                "*click* ...again?",
                "*click* ...seriously?",
                "The lizard squints.",
            ],
            "bodies": [
                "$(user) at $(streak) in a row. Don't push it.",
                "$(streak) survivals for $(user). The lizard's patience is thinning.",
                "$(user) walks away again. That's $(streak).",
            ],
            "victim_clauses": [
                "$(victim) is watching from the shadow realm.",
                "$(victim) could never.",
                "$(victim) is seething, in Minecraft.",
            ],
            "self_victim_clauses": [
                "Somehow back from the dead and thriving.",
                "The shadow realm couldn't hold $(user).",
                "$(user) speedran the respawn timer.",
            ],
            "flows": [
                {
                    "body": "$(streak) for $(user). The lizard is keeping count,",
                    "victim": "just like it counted $(victim)'s last breaths.",
                    "self_victim": "just like it counted $(user)'s last breaths.",
                },
                {
                    "body": "$(user) walks away again. That's $(streak),",
                    "victim": "which is $(streak) more than $(victim) managed.",
                    "self_victim": "not bad for someone who just respawned.",
                },
            ],
        },
        (5, 7): {
            "openers": [
                "*click* ...you're STILL here?",
                "The lizard is visibly shaking.",
                "*click* ...impossible.",
            ],
            "bodies": [
                "$(streak) survivals. $(user), the lizard is getting REAL irritated.",
                "$(user) at $(streak). This can't last.",
                "$(streak) times, $(user). The lizard remembers every single one.",
            ],
            "victim_clauses": [
                "$(victim) WISHES they had your luck.",
                "$(victim) is rolling in their grave.",
                "At least $(victim) had the decency to get shot.",
            ],
            "self_victim_clauses": [
                "$(user) came back from the grave and chose violence.",
                "Died and came back stronger. The lizard is shook.",
                "$(user) used a phoenix down apparently.",
            ],
            "flows": [
                {
                    "body": "$(streak) times, $(user). The lizard remembers every single one —",
                    "victim": "especially what happened to $(victim).",
                    "self_victim": "especially $(user)'s last visit.",
                },
                {
                    "body": "$(user) at $(streak). The lizard's aim is clearly off.",
                    "victim": "Worked just fine on $(victim), though.",
                    "self_victim": "It wasn't off last time, $(user).",
                },
                {
                    "body": "$(streak) survivals, $(user). The lizard can't even look at you.",
                    "victim": "It's still making eye contact with $(victim)'s ghost.",
                    "self_victim": "It's still staring at the spot where $(user) fell.",
                },
            ],
        },
        (8, None): {
            "openers": [
                "*click* — HOW.",
                "The lizard throws the gun.",
                "...this is RIGGED.",
            ],
            "bodies": [
                "$(streak) in a ROW, $(user)?! The lizard is furious, but their face doesn't change.",
                "$(user) at $(streak). The lizard is getting their revolver checked.",
                "$(streak). $(user). The lizard will remember this.",
            ],
            "victim_clauses": [
                "$(victim) is filing a complaint.",
                "$(victim) died so $(user) could live. Disgusting.",
                "$(victim) is COOKED.",
            ],
            "self_victim_clauses": [
                "$(user) died, respawned, and is now immortal. The lizard quits.",
                "Back from the grave $(streak) times?! This is a ZOMBIE.",
                "$(user) keeps dying and coming back. The lizard is filing a bug report.",
            ],
            "flows": [
                {
                    "body": "$(streak), $(user). The lizard has nothing left —",
                    "victim": "it spent everything on $(victim).",
                    "self_victim": "it already used its best material on $(user) last round.",
                },
                {
                    "body": "$(user) at $(streak). At this point the lizard is questioning itself,",
                    "victim": "not $(victim). $(victim) went down clean.",
                    "self_victim": "because $(user) went down clean last time and STILL came back.",
                },
                {
                    "body": "$(streak). $(user). The lizard is starting to think the gun is broken.",
                    "victim": "It worked on $(victim) just fine.",
                    "self_victim": "It worked on $(user) just fine last time.",
                },
            ],
        },
    },
    # ------------------------------------------------------------------
    # BORED — flat affect, short sentences. The lizard has seen it all.
    # ------------------------------------------------------------------
    Mood.BORED: {
        (1, 2): {
            "openers": ["*click*", "Empty.", "yeah."],
            "bodies": [
                "$(user) lives. Whatever.",
                "$(user). Have some $(chemical), I guess.",
                "Sure. $(user) survives.",
            ],
        },
        (3, 4): {
            "openers": ["*click*", "again.", "mhm."],
            "bodies": [
                "$(streak) in a row for $(user). Cool.",
                "$(streak) survivals for $(user). Are we done?",
                "$(user) at $(streak) in a row. Riveting.",
            ],
        },
        (5, 7): {
            "openers": ["*click*", "still going.", "great."],
            "bodies": [
                "$(streak), $(user). The lizard stopped counting.",
                "$(user) at $(streak). The lizard has other things to do.",
                "$(streak). $(user). Wow. Anyway.",
            ],
        },
        (8, None): {
            "openers": ["*click*", "...", "okay."],
            "bodies": [
                "$(streak), $(user). The lizard left the room.",
                "$(user)'s at $(streak). The lizard is on its phone.",
                "$(streak). The lizard has mentally clocked out.",
            ],
        },
    },
    # ------------------------------------------------------------------
    # IMPRESSED — genuine surprise. The lizard respects the feat.
    # ------------------------------------------------------------------
    Mood.IMPRESSED: {
        (1, 2): {
            "openers": ["*click* — oh.", "The chamber was empty!", "...huh."],
            "bodies": [
                "$(user) survives. Not bad.",
                "$(user) pulls through. The lizard raises an eyebrow.",
                "$(user) lives to tell the tale. $(chemical) well earned.",
            ],
            "victim_clauses": [
                "$(victim) should be taking notes.",
                "$(victim) couldn't pull that off.",
                "$(victim) is watching from the afterlife, impressed.",
            ],
            "self_victim_clauses": [
                "Back already? Bold.",
                "$(user) came back swinging.",
                "The lizard respects the quick recovery.",
            ],
        },
        (3, 4): {
            "openers": [
                "...okay then.",
                "The lizard pauses.",
                "*click* — the lizard nods.",
            ],
            "bodies": [
                "$(streak) for $(user). The lizard is paying attention now.",
                "$(user) at $(streak). This is getting interesting.",
                "$(streak) survivals. $(user) has the lizard's respect. For now.",
            ],
            "victim_clauses": [
                "$(victim) never made it this far.",
                "$(victim) wishes they had $(user)'s composure.",
                "The lizard glances at where $(victim) used to sit.",
            ],
            "self_victim_clauses": [
                "From the grave to a streak. That takes nerve.",
                "$(user) clawed back from death. The lizard is intrigued.",
                "Death was just a warmup for $(user).",
            ],
        },
        (5, 7): {
            "openers": [
                "...whoa.",
                "The lizard sets down the gun for a moment.",
                "*click* — remarkable.",
            ],
            "bodies": [
                "$(streak) in a row, $(user). The lizard hasn't seen this in a while.",
                "$(user) at $(streak). The lizard is genuinely surprised.",
                "$(streak) survivals. $(user), the lizard underestimated you.",
            ],
            "victim_clauses": [
                "$(victim) could only dream of this.",
                "$(victim) is somewhere, seething respectfully.",
                "Even $(victim) has to admit — that's impressive.",
            ],
            "self_victim_clauses": [
                "Died, came back, and now THIS? $(user) is built different.",
                "The lizard watches $(user) with grudging admiration.",
                "$(user) went from dead to legendary.",
            ],
            "flows": [
                {
                    "body": "$(streak) survivals, $(user). The lizard underestimated you.",
                    "victim": "It didn't underestimate $(victim), though. That was precision.",
                    "self_victim": "Especially after what happened to $(user) last time.",
                },
                {
                    "body": "$(user) at $(streak). The lizard is genuinely surprised —",
                    "victim": "$(victim) never gave the lizard this kind of trouble.",
                    "self_victim": "$(user) didn't seem this capable last round.",
                },
            ],
        },
        (8, None): {
            "openers": [
                "...the lizard stands up.",
                "The lizard slowly claps.",
                "*click* — the lizard has no words.",
            ],
            "bodies": [
                "$(streak), $(user). The lizard tips its hat.",
                "$(user) at $(streak). This is... actually incredible.",
                "$(streak) survivals. $(user), the lizard is taking notes.",
            ],
            "victim_clauses": [
                "$(victim) couldn't even comprehend this streak.",
                "$(victim) would need three lifetimes to match $(user).",
                "Even the lizard forgot about $(victim) watching this.",
            ],
            "self_victim_clauses": [
                "From death to $(streak)? $(user) is writing history.",
                "The lizard has never seen a comeback like this.",
                "$(user) died, respawned, and became a legend.",
            ],
            "flows": [
                {
                    "body": "$(streak), $(user). The lizard has seen a lot of players,",
                    "victim": "but $(victim) was the only one who put up a fight. Until now.",
                    "self_victim": "and $(user) died and came back better than all of them.",
                },
                {
                    "body": "$(user) at $(streak). The lizard puts the gun down —",
                    "victim": "it only picks it up for worthy challengers. $(victim) wasn't one.",
                    "self_victim": "not out of mercy. Out of respect for what $(user) survived.",
                },
            ],
        },
    },
    # ------------------------------------------------------------------
    # SMUG — knows something you don't. Loaded gun energy.
    # ------------------------------------------------------------------
    Mood.SMUG: {
        (1, 2): {
            "openers": [
                "*click* ...for now.",
                "The lizard smirks.",
                "...interesting.",
            ],
            "bodies": [
                "$(user) survives. The lizard seems... amused.",
                "$(user) gets lucky. The lizard is patient.",
                "$(user) lives. Enjoy it while it lasts.",
            ],
            "victim_clauses": [
                "$(victim) thought they were safe too.",
                "The lizard glances at $(victim)'s empty chair.",
                "$(victim) had that same confidence once.",
            ],
            "self_victim_clauses": [
                "$(user) came back. The lizard was hoping for that.",
                "The lizard grins. Welcome back, $(user).",
                "$(user) returns. The lizard was waiting.",
            ],
        },
        (3, 4): {
            "openers": [
                "*click* ...oh, you'll be back.",
                "The lizard chuckles.",
                "The lizard's grin widens.",
            ],
            "bodies": [
                "$(streak) for $(user). The lizard is counting too.",
                "$(user) at $(streak). Every streak ends, $(user).",
                "$(streak) survivals. The lizard has seen how this goes.",
            ],
            "victim_clauses": [
                "$(victim) was on a streak too. Once.",
                "Ask $(victim) how confidence worked out.",
                "$(victim) had the same look on their face.",
            ],
            "self_victim_clauses": [
                "$(user) came back confident. The lizard likes confident.",
                "Fresh off a death and already cocky? Cute.",
                "$(user) forgot what happened last time.",
            ],
        },
        (5, 7): {
            "openers": [
                "*click* ...tick tock.",
                "The lizard leans forward.",
                "The lizard polishes the gun. Casually.",
            ],
            "bodies": [
                "$(streak), $(user). You know this can't last, right?",
                "$(user) at $(streak). The lizard has all the time in the world.",
                "$(streak) survivals. The fall will be spectacular.",
            ],
            "victim_clauses": [
                "$(victim) was flying high too. Before.",
                "$(victim)'s streak was shorter. Just saying.",
                "The lizard whispers $(victim)'s name.",
            ],
            "self_victim_clauses": [
                "$(user) cheated death and is getting cocky. The lizard takes note.",
                "From corpse to $(streak) streak. The lizard is... entertained.",
                "$(user) forgot the taste of the shadow realm. The lizard will remind them.",
            ],
            "flows": [
                {
                    "body": "$(streak) survivals, $(user). The fall will be spectacular —",
                    "victim": "ask $(victim) how the landing felt.",
                    "self_victim": "$(user) already knows how the landing feels.",
                },
                {
                    "body": "$(user) at $(streak). The lizard is patient.",
                    "victim": "It was patient with $(victim) too. Look how that ended.",
                    "self_victim": "It was patient last time too, $(user). Remember?",
                },
            ],
        },
        (8, None): {
            "openers": [
                "*click* ...any day now.",
                "The lizard checks its watch.",
                "The lizard loads the next round. Slowly.",
            ],
            "bodies": [
                "$(streak), $(user). The higher they climb...",
                "$(user) at $(streak). The lizard is already writing the obituary.",
                "$(streak). $(user). The lizard can wait.",
            ],
            "victim_clauses": [
                "$(victim) thought $(streak) was possible for them too.",
                "$(victim) sends their regards from the shadow realm.",
                "The lizard dedicates the next bullet to $(victim).",
            ],
            "self_victim_clauses": [
                "$(user) keeps coming back. The lizard admires the audacity.",
                "$(streak) after dying? $(user) is speed-running the tragedy.",
                "The lizard lets $(user) build the streak. It's more fun that way.",
            ],
            "flows": [
                {
                    "body": "$(streak), $(user). The lizard is writing the obituary —",
                    "victim": "it recycled $(victim)'s. Just changed the name.",
                    "self_victim": "it already has $(user)'s on file from last time.",
                },
                {
                    "body": "$(user) at $(streak). The lizard can wait.",
                    "victim": "$(victim) couldn't.",
                    "self_victim": "$(user) couldn't, last time.",
                },
            ],
        },
    },
    # ------------------------------------------------------------------
    # CLINICAL — detached, statistical. The lizard reads your file.
    # ------------------------------------------------------------------
    Mood.CLINICAL: {
        (1, 2): {
            "openers": ["Chamber empty.", "Result: survival.", "Negative discharge."],
            "bodies": [
                "Subject $(user) survives. Administering $(chemical).",
                "$(user): survived. Streak: $(streak).",
                "Survival logged. $(user), streak $(streak).",
            ],
        },
        (3, 4): {
            "openers": [
                "Chamber empty. Noted.",
                "Result: survival. Consecutive.",
                "Negative discharge. Pattern emerging.",
            ],
            "bodies": [
                "Subject $(user), streak $(streak). Within expected parameters.",
                "$(user): $(streak) consecutive survivals. Anomalous but not significant.",
                "Streak $(streak) for $(user). The lizard updates the spreadsheet.",
            ],
        },
        (5, 7): {
            "openers": [
                "Survival confirmed. Streak flagged.",
                "Result: anomalous.",
                "Negative discharge. Flagging for review.",
            ],
            "bodies": [
                "Subject $(user) at $(streak). Exceeds standard deviation.",
                "$(user): $(streak) consecutive survivals. The data is... unexpected.",
                "Streak $(streak). $(user)'s file has been escalated.",
            ],
        },
        (8, None): {
            "openers": [
                "Survival confirmed. Alert triggered.",
                "Result: statistically improbable.",
                "Negative discharge. Recalibrating.",
            ],
            "bodies": [
                "Subject $(user). Streak: $(streak). The model needs retraining.",
                "$(user) at $(streak). This defies the actuarial tables.",
                "Streak $(streak). The lizard is submitting a variance report.",
            ],
        },
    },
    # ------------------------------------------------------------------
    # GLEEFUL — cackling, sadistic joy. Frustrated on survivals.
    # ------------------------------------------------------------------
    Mood.GLEEFUL: {
        (1, 2): {
            "openers": ["*click* — tch.", "Empty. Unfortunate.", "...fine."],
            "bodies": [
                "$(user) lives. The lizard hides its disappointment.",
                "$(user) survives. The lizard begrudgingly dispenses $(chemical).",
                "$(user) gets away. The lizard will get its chance.",
            ],
            "victim_clauses": [
                "At least the lizard still has $(victim).",
                "$(victim) was more fun anyway.",
                "The lizard consoles itself with the memory of $(victim).",
            ],
            "self_victim_clauses": [
                "$(user) came back. The lizard's eyes light up.",
                "Oh, $(user) is back! The lizard missed its favorite target.",
                "$(user) survived? That just makes next time sweeter.",
            ],
        },
        (3, 4): {
            "openers": [
                "*click* — UGH.",
                "The lizard grits its teeth.",
                "...are you serious right now?",
            ],
            "bodies": [
                "$(streak) for $(user). The lizard is losing its patience AND ITS MIND.",
                "$(user) at $(streak). This is NOT how this was supposed to go.",
                "$(streak) survivals, $(user)? The lizard's trigger finger is TWITCHING.",
            ],
            "victim_clauses": [
                "$(victim) went down easy. Why can't $(user)?!",
                "The lizard misses $(victim). $(victim) played fair.",
                "$(victim) had the decency to DIE.",
            ],
            "self_victim_clauses": [
                "$(user) JUST died and is already at $(streak)?! The NERVE.",
                "The lizard JUST got $(user) and they're BACK?!",
                "$(user) escaped the shadow realm to do THIS to the lizard.",
            ],
        },
        (5, 7): {
            "openers": [
                "*click* — NO.",
                "The lizard SLAMS the table.",
                "This is UNACCEPTABLE.",
            ],
            "bodies": [
                "$(streak), $(user)?! The lizard is VIBRATING with rage.",
                "$(user) at $(streak). The lizard is planning something special.",
                "$(streak) survivals. $(user), the lizard is going to SAVOR your eventual demise.",
            ],
            "victim_clauses": [
                "$(victim) is the only thing keeping the lizard sane right now.",
                "The lizard clings to the memory of $(victim)'s timeout.",
                "$(victim) went down. Why won't $(user)?!",
            ],
            "self_victim_clauses": [
                "$(user) DIED and came back to do this. The AUDACITY.",
                "$(user) broke free from the shadow realm to torment the lizard.",
                "The lizard thought $(user) was DONE. It was WRONG.",
            ],
            "flows": [
                {
                    "body": "$(streak) survivals, $(user)?! The lizard is going to SAVOR your demise",
                    "victim": "the way it SAVORED $(victim)'s!",
                    "self_victim": "AGAIN! Just like LAST TIME!",
                },
                {
                    "body": "$(user) at $(streak). The lizard got $(victim) so easily,",
                    "victim": "WHY CAN'T IT GET $(user)?!",
                    "self_victim": "GOT $(user) so easily last time, WHAT CHANGED?!",
                },
            ],
        },
        (8, None): {
            "openers": [
                "*click* — the lizard SCREAMS.",
                "The lizard FLIPS the table.",
                "HOW ARE YOU STILL ALIVE?!",
            ],
            "bodies": [
                "$(streak), $(user)?! The lizard is going to EXPLODE.",
                "$(user) at $(streak). The lizard is questioning EVERYTHING.",
                "$(streak) survivals. The lizard is ONE bad roll from a breakdown.",
            ],
            "victim_clauses": [
                "$(victim) is laughing at the lizard from the shadow realm. NOT HELPING.",
                "Even $(victim) is shocked the lizard can't get $(user).",
                "The lizard NEEDS $(user) to join $(victim). NEEDS IT.",
            ],
            "self_victim_clauses": [
                "$(user) died and has now survived $(streak) in a ROW?! The lizard needs THERAPY.",
                "FROM DEATH TO $(streak)?! $(user) is the lizard's NEMESIS.",
                "$(user) won't STAY DOWN. The lizard is filing for a transfer.",
            ],
            "flows": [
                {
                    "body": "$(streak), $(user)?! The lizard is going to EXPLODE.",
                    "victim": "$(victim) went down in ONE. WHY NOT $(user)?! WHY?!",
                    "self_victim": "$(user) went down LAST TIME! THIS ISN'T FAIR!",
                },
                {
                    "body": "$(user) at $(streak). The lizard is questioning EVERYTHING it knows",
                    "victim": "because EVERYTHING worked PERFECTLY on $(victim)!",
                    "self_victim": "because EVERYTHING worked PERFECTLY on $(user) LAST TIME!",
                },
            ],
        },
    },
    # ------------------------------------------------------------------
    # DEADPAN — ultra-minimal one-liners. Comedy through brevity.
    # ------------------------------------------------------------------
    Mood.DEADPAN: {
        (1, 2): {
            "openers": ["*click*", "nope.", "empty."],
            "bodies": ["$(user) lives.", "sure.", "$(chemical)."],
        },
        (3, 4): {
            "openers": ["*click*", "again.", "hm."],
            "bodies": ["$(streak).", "$(user). $(streak).", "fine."],
        },
        (5, 7): {
            "openers": ["*click*", "still.", "yep."],
            "bodies": [
                "$(user). $(streak).",
                "noted.",
                "$(streak) for $(user).",
            ],
        },
        (8, None): {
            "openers": ["...", "*click*", "wow."],
            "bodies": [
                "$(streak).",
                "$(user). just. $(streak).",
                "the lizard has no words. literally.",
            ],
        },
    },
}


# ---------------------------------------------------------------------------
# Death message pools — per mood, per tier
# ---------------------------------------------------------------------------

MOOD_DEATH: dict[Mood, dict[TierKey, dict]] = {
    # ------------------------------------------------------------------
    # THEATRICAL
    # ------------------------------------------------------------------
    Mood.THEATRICAL: {
        (1, 1): {
            "cores": [
                "You lose, $(user). Reach for the sky.",
                "$(user) goes down. First time's free.",
                "Welcome to the club, $(user).",
            ],
            "rare": [
                {
                    "text": "The lizard waddles towards $(user), gun in hand. Accidentally slipping on a banana, the gun flies through the air. A bunny catches it. $(user) goes down.",
                    "emote": "bardGun",
                    "countdown": None,
                },
            ],
        },
        (2, 9): {
            "cores": [
                "For the $(deaths) time, you lose, $(user).",
                "$(deaths) time's the charm? Nope. $(user) goes down.",
                "$(user) again?! That's $(raw_deaths).",
            ],
            "rare": [
                {
                    "text": "The lizard waddles towards $(user), gun in hand. Accidentally slipping on a banana, the gun flies through the air. A bunny catches it. Death #$(raw_deaths) for $(user).",
                    "emote": "bardGun",
                    "countdown": None,
                },
                {
                    "text": "The lizard throws the gun to Quagsire. $(user) goes down for the $(deaths) time.",
                    "emote": "bardA",
                    "countdown": None,
                },
            ],
        },
        (10, 24): {
            "cores": [
                "$(raw_deaths) deaths, $(user). The lizard is starting to recognize you.",
                "$(user), $(raw_deaths) times now. You might have a problem.",
                "The lizard nods at $(user). A familiar face. Death #$(raw_deaths).",
            ],
            "rare": [
                {
                    "text": "The lizard waddles towards $(user), gun in hand. Accidentally slipping on a banana, the gun flies through the air. A bunny catches it. Death #$(raw_deaths) for $(user).",
                    "emote": "bardGun",
                    "countdown": None,
                },
                {
                    "text": "The lizard throws the gun to Quagsire. Death #$(raw_deaths) for $(user).",
                    "emote": "bardA",
                    "countdown": None,
                },
            ],
        },
        (25, 49): {
            "cores": [
                "$(raw_deaths) deaths. $(user), the lizard has a punch card with your name on it.",
                "$(user) at $(raw_deaths). The lizard doesn't even aim anymore.",
                "Death #$(raw_deaths) for $(user). At this point it's a subscription.",
            ],
            "rare": [
                {
                    "text": "The lizard waddles towards $(user), gun in hand. Accidentally slipping on a banana, the gun flies through the air. A bunny catches it. Death #$(raw_deaths) for $(user).",
                    "emote": "bardGun",
                    "countdown": None,
                },
                {
                    "text": "The lizard throws the gun to Quagsire. $(user) at $(raw_deaths).",
                    "emote": "bardA",
                    "countdown": None,
                },
            ],
        },
        (50, 99): {
            "cores": [
                "$(raw_deaths). FIFTY-PLUS deaths, $(user). The lizard is concerned for your wellbeing.",
                "$(user), death #$(raw_deaths). The shadow realm has a reserved seat with your name on it.",
                "$(raw_deaths) times, $(user). The lizard is running out of bullets because of YOU.",
            ],
            "rare": [
                {
                    "text": "The lizard waddles towards $(user), gun in hand. Accidentally slipping on a banana, the gun flies through the air. A bunny catches it. Death #$(raw_deaths) for $(user).",
                    "emote": "bardGun",
                    "countdown": None,
                },
                {
                    "text": "The lizard throws the gun to Quagsire. $(user) at $(raw_deaths).",
                    "emote": "bardA",
                    "countdown": None,
                },
            ],
        },
        (100, None): {
            "cores": [
                "$(raw_deaths). $(user), you are CLINICALLY addicted to dying. The lizard is speechless.",
                "Death #$(raw_deaths) for $(user). The lizard has retired and been replaced twice since you started.",
                "$(user). $(raw_deaths) deaths. The lizard wrote a thesis about you.",
            ],
            "rare": [
                {
                    "text": "The lizard waddles towards $(user), gun in hand. Accidentally slipping on a banana, the gun flies through the air. A bunny catches it. Death #$(raw_deaths) for $(user).",
                    "emote": "bardGun",
                    "countdown": None,
                },
                {
                    "text": "The lizard throws the gun to Quagsire. $(user). $(raw_deaths).",
                    "emote": "bardA",
                    "countdown": None,
                },
            ],
        },
    },
    # ------------------------------------------------------------------
    # BORED
    # ------------------------------------------------------------------
    Mood.BORED: {
        (1, 1): {
            "cores": [
                "$(user). Dead.",
                "Oh, another one.",
                "$(user) goes down. Moving on.",
            ],
        },
        (2, 9): {
            "cores": [
                "$(user). $(raw_deaths) times now.",
                "$(raw_deaths). Next.",
                "$(user), again.",
            ],
        },
        (10, 24): {
            "cores": [
                "$(raw_deaths), $(user). You know the drill.",
                "$(user). $(raw_deaths). Same as always.",
                "The lizard waves $(user) to the shadow realm. $(raw_deaths).",
            ],
        },
        (25, 49): {
            "cores": [
                "$(raw_deaths), $(user). At this point it's a commute.",
                "$(user). $(raw_deaths). The lizard yawns.",
                "$(raw_deaths) deaths. $(user)'s practically furniture here.",
            ],
        },
        (50, 99): {
            "cores": [
                "$(raw_deaths). The lizard doesn't even look up.",
                "$(user). $(raw_deaths). gtfo already.",
                "$(raw_deaths) deaths, $(user). Filed under 'expected'.",
            ],
            "rare": [
                {
                    "text": "Oh, I'm sorry $(user), did you expect me to warn you that time? $(raw_deaths).",
                    "emote": "LizardWithAGun",
                    "countdown": None,
                    "timeout_first": True,
                },
                {
                    "text": "Whoops, finger slipped. That's $(raw_deaths), $(user).",
                    "emote": "LizardWithAGun",
                    "countdown": None,
                    "timeout_first": True,
                },
                {
                    "text": "That wasn't me, I swear. But that's $(raw_deaths), $(user).",
                    "emote": "LizardWithAGun",
                    "countdown": None,
                    "timeout_first": True,
                },
            ],
        },
        (100, None): {
            "cores": [
                "$(raw_deaths). $(user). The lizard has nothing left to say.",
                "$(user). $(raw_deaths). ...",
                "$(raw_deaths). The lizard respects the commitment. No wait, it doesn't.",
            ],
            "rare": [
                {
                    "text": "Oh, I'm sorry $(user), did you expect a warning? After $(raw_deaths) times?",
                    "emote": "LizardWithAGun",
                    "countdown": None,
                    "timeout_first": True,
                },
                {
                    "text": "Whoops, finger slipped. $(raw_deaths), $(user).",
                    "emote": "LizardWithAGun",
                    "countdown": None,
                    "timeout_first": True,
                },
                {
                    "text": "That wasn't me, I swear. But that's $(raw_deaths), $(user).",
                    "emote": "LizardWithAGun",
                    "countdown": None,
                    "timeout_first": True,
                },
                {
                    "text": "$(raw_deaths). The lizard didn't even bother picking up the gun this time, $(user).",
                    "emote": "LizardWithAGun",
                    "countdown": None,
                    "timeout_first": True,
                },
            ],
        },
    },
    # ------------------------------------------------------------------
    # IMPRESSED
    # ------------------------------------------------------------------
    Mood.IMPRESSED: {
        (1, 1): {
            "cores": [
                "$(user) steps up and goes down. Respect for trying.",
                "$(user)'s first death. Everyone remembers their first.",
                "The lizard nods at $(user). A worthy challenger. Once.",
            ],
        },
        (2, 9): {
            "cores": [
                "$(user) comes back for the $(deaths) time. The lizard respects the tenacity.",
                "$(raw_deaths) deaths and $(user) keeps returning. That takes guts.",
                "Death #$(raw_deaths) for $(user). Most people would've quit by now.",
            ],
        },
        (10, 24): {
            "cores": [
                "$(raw_deaths) deaths, $(user). The lizard has to admire the dedication.",
                "$(user) at $(raw_deaths). Not many make it this far into the record books.",
                "Death #$(raw_deaths). $(user) is becoming a legend, one death at a time.",
            ],
        },
        (25, 49): {
            "cores": [
                "$(raw_deaths), $(user). The lizard genuinely didn't think you'd keep going.",
                "$(user) at $(raw_deaths). The lizard raises its glass.",
                "Death #$(raw_deaths). $(user) has earned the lizard's grudging respect.",
            ],
        },
        (50, 99): {
            "cores": [
                "$(raw_deaths) deaths, $(user). The lizard is in awe of the commitment.",
                "$(user), death #$(raw_deaths). This is dedication the lizard hasn't seen before.",
                "$(raw_deaths). $(user), the lizard salutes you on the way to the shadow realm.",
            ],
        },
        (100, None): {
            "cores": [
                "$(raw_deaths). $(user), the lizard stands. You've earned it.",
                "Death #$(raw_deaths) for $(user). The lizard has never met anyone like you.",
                "$(user). $(raw_deaths). The lizard is genuinely moved.",
            ],
        },
    },
    # ------------------------------------------------------------------
    # SMUG
    # ------------------------------------------------------------------
    Mood.SMUG: {
        (1, 1): {
            "cores": [
                "$(user). The lizard knew.",
                "The lizard smirks. First blood, $(user).",
                "$(user) goes down. The lizard saw that coming.",
            ],
        },
        (2, 9): {
            "cores": [
                "$(user). $(raw_deaths). The lizard called it.",
                "$(deaths) time, $(user). Like clockwork.",
                "The lizard winks. $(raw_deaths), $(user). Right on schedule.",
            ],
        },
        (10, 24): {
            "cores": [
                "$(raw_deaths), $(user). The lizard had a feeling.",
                "$(user) at $(raw_deaths). The lizard is never wrong.",
                "Death #$(raw_deaths). The lizard's prediction was... accurate.",
            ],
        },
        (25, 49): {
            "cores": [
                "$(raw_deaths), $(user). The lizard already had the paperwork ready.",
                "$(user). $(raw_deaths). The lizard doesn't even need to aim at this point.",
                "Death #$(raw_deaths). $(user), the lizard wrote today's date on your file this morning.",
            ],
        },
        (50, 99): {
            "cores": [
                "$(raw_deaths). $(user), the lizard had a bet on this exact number.",
                "$(user) at $(raw_deaths). The lizard's smile says everything.",
                "$(raw_deaths) deaths. $(user), did you really think today would be different?",
            ],
        },
        (100, None): {
            "cores": [
                "$(raw_deaths). The lizard doesn't even need to look anymore, $(user).",
                "$(user). $(raw_deaths). The lizard wrote this obituary in advance.",
                "Death #$(raw_deaths). $(user), the lizard keeps a running tally. For fun.",
            ],
        },
    },
    # ------------------------------------------------------------------
    # CLINICAL
    # ------------------------------------------------------------------
    Mood.CLINICAL: {
        (1, 1): {
            "cores": [
                "Subject $(user). First death logged.",
                "$(user): initial termination event recorded.",
                "New file created for $(user). Death #1.",
            ],
        },
        (2, 9): {
            "cores": [
                "$(user). Death event #$(raw_deaths). Within normal range.",
                "Death #$(raw_deaths) logged for $(user). Consistent with profile.",
                "Subject $(user), $(raw_deaths) deaths. Trajectory nominal.",
            ],
        },
        (10, 24): {
            "cores": [
                "$(user). Death #$(raw_deaths). Entering frequent-flyer territory.",
                "$(raw_deaths) deaths for $(user). The lizard adjusts the projection.",
                "Subject $(user) at $(raw_deaths). Moved to high-frequency monitoring.",
            ],
        },
        (25, 49): {
            "cores": [
                "$(user). Death #$(raw_deaths). Profile classified: recurring.",
                "$(raw_deaths) for $(user). The lizard has a dedicated folder.",
                "Death #$(raw_deaths). $(user) now accounts for a measurable percentage.",
            ],
        },
        (50, 99): {
            "cores": [
                "$(user). Death #$(raw_deaths). Statistical outlier territory.",
                "$(raw_deaths) deaths. $(user)'s file is thicker than the manual.",
                "Subject $(user) at $(raw_deaths). The lizard is writing a case study.",
            ],
        },
        (100, None): {
            "cores": [
                "Death #$(raw_deaths). Subject $(user). The data speaks for itself.",
                "$(user). $(raw_deaths). The lizard's entire thesis is about you.",
                "$(raw_deaths) deaths. $(user) IS the dataset.",
            ],
        },
    },
    # ------------------------------------------------------------------
    # GLEEFUL
    # ------------------------------------------------------------------
    Mood.GLEEFUL: {
        (1, 1): {
            "cores": [
                "THERE we go! $(user) goes down! Welcome to the party!",
                "YES! $(user)! The lizard was WAITING for a newcomer!",
                "$(user), FINALLY someone with the guts to lose!",
            ],
        },
        (2, 9): {
            "cores": [
                "$(user) again! $(raw_deaths) times! The lizard LOVES a returning customer!",
                "$(deaths) time for $(user)! The lizard can't stop grinning!",
                "YES, $(user)! $(raw_deaths) deaths and counting! DELICIOUS!",
            ],
        },
        (10, 24): {
            "cores": [
                "$(raw_deaths) for $(user)! The lizard is THRIVING!",
                "$(user) at $(raw_deaths)! The lizard cackles!",
                "Death #$(raw_deaths)! $(user) keeps the lizard FED!",
            ],
        },
        (25, 49): {
            "cores": [
                "$(raw_deaths), $(user)! The lizard is doing a HAPPY DANCE!",
                "$(user) at $(raw_deaths)! The lizard has never been HAPPIER!",
                "Death #$(raw_deaths)! $(user) is the gift that keeps on GIVING!",
            ],
        },
        (50, 99): {
            "cores": [
                "$(raw_deaths)! FIFTY PLUS, $(user)! The lizard is IN TEARS of joy!",
                "$(user) at $(raw_deaths)! The lizard wrote a LOVE LETTER to your bad luck!",
                "$(raw_deaths) deaths! The lizard is throwing $(user) a PARTY!",
            ],
        },
        (100, None): {
            "cores": [
                "$(raw_deaths), $(user)! The lizard is composing a SYMPHONY in your honor!",
                "$(user)! $(raw_deaths)! The lizard has achieved ENLIGHTENMENT through your suffering!",
                "Death #$(raw_deaths)! The lizard BOWS to $(user), its most loyal patron!",
            ],
        },
    },
    # ------------------------------------------------------------------
    # DEADPAN
    # ------------------------------------------------------------------
    Mood.DEADPAN: {
        (1, 1): {
            "cores": ["no.", "$(user). bye.", "first time."],
        },
        (2, 9): {
            "cores": ["$(raw_deaths).", "again.", "$(user). $(raw_deaths)."],
        },
        (10, 24): {
            "cores": ["$(raw_deaths).", "you know.", "$(user)."],
        },
        (25, 49): {
            "cores": ["$(raw_deaths).", "at this point.", "$(user). really."],
        },
        (50, 99): {
            "cores": ["$(raw_deaths).", "...", "$(user)."],
        },
        (100, None): {
            "cores": ["$(raw_deaths).", ".", "$(user). ...$(raw_deaths)."],
        },
    },
}


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _substitute(message: str, ctx: MoodContext) -> str:
    """Replace all $(placeholder) variables in a message."""
    return (
        message.replace("$(user)", ctx.chatter_name)
        .replace("$(chemical)", ctx.chemical)
        .replace("$(streak)", str(ctx.streak))
        .replace("$(victim)", ctx.victim)
        .replace("$(deaths)", _ordinal(ctx.deaths))
        .replace("$(raw_deaths)", str(ctx.deaths))
    )


def _try_rare(
    pool: dict, ctx: MoodContext, as_death: bool = False
) -> DeathMessage | str | None:
    """Roll for a rare message.

    Returns DeathMessage (death path), str (survival path), or None.
    """
    rares = pool.get("rare")
    if not rares or random.random() >= RARE_CHANCE:
        return None
    entry = random.choice(rares)
    text = entry["text"]
    emote = entry.get("emote", "LizardWithAGun")
    countdown = entry.get("countdown")
    parts = [text]
    if countdown:
        parts.append(countdown)
    message = " ".join(parts) + f" {emote}"
    message = _substitute(message, ctx)
    if as_death:
        return DeathMessage(
            text=message, timeout_first=entry.get("timeout_first", False)
        )
    return message


def render_survival(mood: Mood, ctx: MoodContext) -> str:
    """Compose a survival message for the given mood and context."""
    behavior = MOOD_BEHAVIORS[mood]
    tier_key = _get_tier_key(SURVIVAL_TIER_RANGES, ctx.streak)
    pool = MOOD_SURVIVAL[mood][tier_key]
    cid = ctx.channel_id

    rare = _try_rare(pool, ctx)
    if rare:
        return rare

    opener = recency.pick(cid, pool["openers"])

    # Try a paired flow (body+clause written together) for natural transitions
    flows = pool.get("flows", [])
    use_flow = (
        flows
        and behavior.include_victim_clause
        and ctx.victim
        and random.random() < FLOW_CHANCE
    )

    if use_flow:
        flow_bodies = [f["body"] for f in flows]
        body = recency.pick(cid, flow_bodies)
        flow = next(f for f in flows if f["body"] == body)
        if ctx.is_self_victim and "self_victim" in flow:
            clause = flow["self_victim"]
        else:
            clause = flow["victim"]
        parts = [opener, body, clause]
    else:
        body = recency.pick(cid, pool["bodies"])
        parts = [opener, body]

        if behavior.include_victim_clause and ctx.victim:
            if ctx.is_self_victim and pool.get("self_victim_clauses"):
                parts.append(recency.pick(cid, pool["self_victim_clauses"]))
            elif pool.get("victim_clauses"):
                parts.append(recency.pick(cid, pool["victim_clauses"]))

    message = " ".join(parts) + " bardLizard"
    return _substitute(message, ctx)


def render_death(mood: Mood, ctx: MoodContext) -> DeathMessage:
    """Compose a death message for the given mood and context."""
    behavior = MOOD_BEHAVIORS[mood]
    tier_key = _get_tier_key(DEATH_TIER_RANGES, ctx.deaths)
    pool = MOOD_DEATH[mood][tier_key]
    cid = ctx.channel_id

    rare = _try_rare(pool, ctx, as_death=True)
    if rare:
        return rare

    core = recency.pick(cid, pool["cores"])
    parts = [core]

    if behavior.countdown:
        parts.append(behavior.countdown)

    message = " ".join(parts) + f" {behavior.emote}"
    return DeathMessage(
        text=_substitute(message, ctx),
        timeout_first=behavior.timeout_first,
    )

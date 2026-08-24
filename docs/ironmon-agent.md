# IronMON local agent — build plan

Status: proposed, nothing built. Written 2026-08-24.

Alys is moving to CachyOS, which retires Streamer.bot as the thing that
administrates channel-point actions during IronMON runs. This is the
plan to replace it with our own pieces.

## What we established first

Findings from live systems and source, so nobody re-derives them:

- **Redemption events are not client-ID gated.** Spoonee's channel has
  20 rewards, we can manage **zero** — and we have ingested 1,918
  redemption events including hers. Only *management* (update/delete a
  reward, fulfil/refund a redemption) requires the reward to have been
  created by our client ID. **Reacting to any redemption works today.**
- Of avalonstar's 8 rewards, 3 are enabled and we own exactly 1 (`Throw
  Something At Me`). `Throw Something At Me (Legacy)` and `(Synthform)`
  are abandoned duplicates from previous tool migrations — the cost this
  plan is meant to stop repeating.
- **The Tracker is BizHawk-only in practice.** mGBA support exists but
  renders to a text buffer in mGBA's scripting console
  (`MGBADisplay.lua`), not the graphical overlay, so it isn't usable on
  stream. The emulator is therefore settled, not a decision.
- **Stream Connect is file-mode only.** Its WebSocket and HTTP paths are
  stubbed (`if true then return ... end`) with the note "Not
  implemented. Requires asynchronous compatibility". We do not need it:
  ironmon-connect is ours and already speaks a JSON protocol over
  BizHawk's socket.
- **BizHawk's socket receive is synchronous.** `comm.socketServerResponse`
  exists, but blocks the emulation thread up to
  `comm.socketServerSetTimeout`. This is exactly why the Tracker devs
  punted, and it is the single most important constraint here.

## Architecture

```
Alys (CachyOS)
  BizHawk + ironmon-connect (Lua)
    │  send + response — blocking, but 127.0.0.1, sub-millisecond
    ▼
  local agent  (127.0.0.1:8080)
    │  async, buffered, tolerates Saya being slow or absent
    ▼
Saya
  synthfunc  (telemetry, questlog, overlays)
  synthhive  (redemption → action mapping)
    ▲
    └── Twitch EventSub
```

**The agent exists to keep the emulator off the network.** That is its
whole justification. A blocking read to Saya would turn any hiccup — a
deploy restarting a container, a wifi blip — into a frame stutter
mid-run. Against loopback it can't.

**The command channel is free.** ironmon-connect already sends
constantly during play (team updates, location, encounters, battle
damage). Every one of those is an opportunity for the agent to hand
back a queued command in the response. No polling loop, no second
connection.

## Phases

Each phase is independently shippable and independently revertible.

### Phase 0 — De-risk. Nothing is built until these are answered.

1. **Does BizHawk's socket server work under Linux?** Launch BizHawk on
   CachyOS with the socket arguments, load ironmon-connect, confirm
   synthfunc's TCP listener logs an `init`. Everything downstream
   assumes yes; nothing else is worth starting until it is verified.
2. **Were `Pick a Ball` and `Hydrate!` created by Streamer.bot or in the
   Twitch dashboard?** Dashboard-created rewards are manageable by
   nobody, so Streamer.bot only reacts to them too, and there is nothing
   to migrate. The tell is whether Streamer.bot can *edit* them.
3. **Inventory the Streamer.bot actions.** For each: does it only react
   (chat, overlay, tracker action) or does it fulfil/refund? Only the
   latter needs a reward we own.

### Phase 1 — Agent as a transparent pass-through

The agent listens on `127.0.0.1:8080`, speaks the existing
length-prefixed `LENGTH MESSAGE` protocol, and forwards everything to
synthfunc unchanged. ironmon-connect is repointed from Saya to
localhost — a one-line config change.

- **No protocol change, no synthfunc change**, so existing tests still
  cover the server side.
- Exit criteria: a full run's telemetry reaches questlog and the
  overlays exactly as before.
- Rollback: point ironmon-connect back at Saya.

This phase is deliberately boring. Its purpose is to put the agent in
the path while nothing depends on it yet.

### Phase 2 — Command channel

- Agent answers each forwarded message with a response payload: a
  queued command, or empty.
- ironmon-connect reads `comm.socketServerResponse()` and dispatches.
- Set `comm.socketServerSetTimeout` low (~50ms) as a backstop.
- Add a `tick` message so commands don't wait for gameplay during menus.
- Prove the loop with **one** harmless action end to end before adding
  more.

Exit criteria: a command issued by hand on Saya visibly takes effect in
the Tracker, with no measurable frame impact during a run.

### Phase 3 — Redemptions drive commands

- Synthhive maps a redemption to a command. Mapping lives **server-side**
  so it is configurable per tenant rather than baked into the agent.
- Transport Saya → agent: see open questions.
- Reward ownership is decided per action, not globally: only actions
  that fulfil or refund need us to own the reward.

### Phase 4 — Port the Streamer.bot actions

One at a time, each verified live before the next. Streamer.bot stays
installed until the last one is ported — it has an experimental Linux
build, which is a fallback, not a plan.

## Open questions

- **Saya → agent transport.** Agent polls synthhive over HTTP (simplest,
  no inbound firewall rule, survives NAT), SSE (synthhive already serves
  it), or Redis pub/sub over Tailscale (synthfunc already publishes).
  Leaning: agent holds an outbound SSE connection, since the
  infrastructure exists and it avoids polling latency.
- **Where does the agent live?** New repo, or a directory in
  ironmon-connect since they are two halves of one protocol.
- **Language and deploy.** Python matches the rest of the suite; a single
  binary is easier to run under systemd on Alys. Either way it wants
  `Restart=always`.
- **Command ordering and duplication.** If the agent restarts holding a
  queue, are commands lost or replayed? Redemptions are viewer-visible,
  so replay is worse than loss.

## Risks

- **Blocking read stalls emulation.** Mitigated by loopback plus a low
  timeout, but it is the failure mode to watch. Measure before trusting.
- **Agent down means telemetry stops**, where today the plugin talks to
  Saya directly. `Restart=always` plus the plugin's existing
  `socketServerIsConnected` handling covers this; it is still a new
  single point of failure on the streaming machine.
- **Nothing here is testable end to end without hardware.** The plugin
  needs BizHawk and a ROM. Phases 1 and 2 exist to keep the untestable
  surface as small as possible and to put a real run behind each step.

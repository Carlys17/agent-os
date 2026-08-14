#!/usr/bin/env python3
"""Live end-to-end check of the composer route pin against a running gateway.

Drives the SAME WebSocket RPC surface the web UI uses — `router.hold.set/get/
clear` plus `chat.send` — and reads the `session.event.router_decision` the
gateway emits for each turn. That event is what the UI paints, so asserting on
it proves the pin reached the router step rather than merely being stored.

Real provider calls that cost real money, so prompts are one word and only five
turns run. Uses a throwaway session key, deleted at the end, so nothing lands in
the operator's chat history.

Point it at an already-running gateway::

    uv run python scripts/live_route_pin_gateway_e2e.py

Exits non-zero if any check fails.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid

import websockets

URL = os.environ.get("AGENTOS_GATEWAY_WS", "ws://127.0.0.1:18791/ws")
SESSION = f"agent:main:webchat:e2e-{uuid.uuid4().hex[:8]}"
PROMPT = "Reply with the single word: ok"


class Rpc:
    def __init__(self, ws) -> None:
        self.ws = ws
        self.n = 0
        self.pending: dict[str, asyncio.Future] = {}
        self.decisions: list[dict] = []
        self.turn_done = asyncio.Event()
        self.errors: list[str] = []
        self.hello_id = "0"

    async def handshake(self) -> dict:
        """The gateway rejects any frame before a `connect` request."""

        self.n += 1
        self.hello_id = str(self.n)
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self.pending[self.hello_id] = fut
        await self.ws.send(
            json.dumps(
                {
                    "type": "req",
                    "id": self.hello_id,
                    "method": "connect",
                    "params": {
                        "minProtocol": 3,
                        "maxProtocol": 3,
                        "clientKind": "control",
                        "client": {"name": "agentos-e2e"},
                    },
                }
            )
        )
        return await asyncio.wait_for(fut, timeout=15)

    async def pump(self) -> None:
        async for raw in self.ws:
            data = json.loads(raw)
            if data.get("type") == "res":
                fut = self.pending.pop(str(data.get("id")), None)
                if fut and not fut.done():
                    if data.get("ok"):
                        fut.set_result(data.get("payload"))
                    else:
                        fut.set_exception(RuntimeError(json.dumps(data.get("error"))))
            elif data.get("protocol") is not None:
                # HelloOk answers the connect handshake; it carries no "type".
                fut = self.pending.pop(str(self.hello_id), None)
                if fut and not fut.done():
                    fut.set_result(data)
            elif data.get("type") == "event":
                event = str(data.get("event"))
                payload = data.get("payload") or {}
                if event == "session.event.router_decision":
                    self.decisions.append(payload)
                elif event in ("session.event.done", "session.event.complete"):
                    self.turn_done.set()
                elif event == "session.event.error":
                    self.errors.append(json.dumps(payload)[:200])
                    self.turn_done.set()

    async def call(self, method: str, params: dict | None = None):
        self.n += 1
        rid = str(self.n)
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self.pending[rid] = fut
        await self.ws.send(
            json.dumps({"type": "req", "id": rid, "method": method, "params": params or {}})
        )
        return await asyncio.wait_for(fut, timeout=30)

    async def turn(self, label: str) -> dict | None:
        """Send one real turn and return its routing decision."""

        self.decisions.clear()
        self.errors.clear()
        self.turn_done.clear()
        await self.call("chat.send", {"sessionKey": SESSION, "message": PROMPT})
        try:
            await asyncio.wait_for(self.turn_done.wait(), timeout=180)
        except TimeoutError:
            print(f"  [{label}] TIMEOUT waiting for the turn to finish")
        if self.errors:
            print(f"  [{label}] stream error: {self.errors[0]}")
        return self.decisions[-1] if self.decisions else None


results: list[tuple[bool, str]] = []


def check(ok: bool, detail: str) -> None:
    results.append((ok, detail))
    print(("  PASS  " if ok else "  FAIL  ") + detail)


async def main() -> int:
    async with websockets.connect(URL, max_size=None) as ws:
        rpc = Rpc(ws)
        pump = asyncio.create_task(rpc.pump())
        hello = await rpc.handshake()
        print(f"connected: protocol={hello.get('protocol')}")
        await rpc.call("sessions.subscribe")
        await rpc.call("sessions.messages.subscribe", {"key": SESSION})

        print(f"session: {SESSION}\n")

        state = await rpc.call("router.hold.get", {"key": SESSION})
        provider = state.get("provider")
        tiers = {t["tier"]: t["model"] for t in state.get("tiers", [])}
        print(f"provider={provider} tiers={tiers}\n")
        check(state.get("enabled") is True, "router reports enabled")
        check(state.get("hold") is None, "fresh session starts unpinned")

        # ── 1. pin a model that is NOT one of the tiers ─────────────────────
        # Chosen from the live catalog rather than hardcoded, both so the script
        # runs against any profile and so "routed to the pinned model" cannot be
        # satisfied by the router happening to pick that tier anyway.
        catalog = await rpc.call("models.list", {"provider": provider})
        off_tier = next(
            (m["id"] for m in catalog if m["id"] not in set(tiers.values())), None
        )
        if not off_tier:
            print("no off-tier model in the catalog; cannot test a model pin")
            return 1

        print(f"\n1. pin model {off_tier}")
        payload = await rpc.call("router.hold.set", {"key": SESSION, "model": off_tier})
        check(
            payload.get("model") == off_tier,
            f"hold.set echoes the model ({payload.get('model')})",
        )
        check(payload.get("targetType") == "model", "hold.set reports targetType=model")
        check(payload.get("sticky") is True, "the pin is sticky")

        read = await rpc.call("router.hold.get", {"key": SESSION})
        check((read.get("hold") or {}).get("model") == off_tier, "hold.get reads the model back")

        decision = await rpc.turn("model-pin")
        got = (decision or {}).get("model")
        check(got == off_tier, f"LIVE TURN routed to {off_tier} (got {got!r})")
        check(
            (decision or {}).get("source") == "router_control_hold",
            f"routing source is the hold (got {(decision or {}).get('source')!r})",
        )

        # ── 2. the pin holds across a second turn (sticky, no TTL) ──────────
        print("\n2. second turn keeps the pin")
        decision = await rpc.turn("model-pin-2")
        got = (decision or {}).get("model")
        check(got == off_tier, f"second turn still on {off_tier} (got {got!r})")

        # ── 3. switch to a tier pin ─────────────────────────────────────────
        print("\n3. pin tier c3")
        payload = await rpc.call("router.hold.set", {"key": SESSION, "tier": "c3"})
        check(payload.get("targetType") == "tier", "hold.set reports targetType=tier")
        expected = tiers.get("c3")
        decision = await rpc.turn("tier-pin")
        got = (decision or {}).get("model")
        check(got == expected, f"LIVE TURN routed to c3's model {expected!r} (got {got!r})")
        check((decision or {}).get("tier") == "c3", "decision reports tier c3")

        # ── 4. the catalog is the boundary of what can be pinned ────────────
        # OpenCAP's inference endpoint also answers to namespaced aliases
        # (`openrouter/gpt-5.4`), but its PUBLIC catalog publishes only bare
        # canonical ids. So aliases are neither offered nor pinnable — asserted
        # rather than assumed, because assuming the opposite is what this run
        # caught the first time.
        print("\n4. catalog scope")
        listed = await rpc.call("models.list", {"provider": provider})
        ids = {m["id"] for m in listed}
        check(
            not any("/" in i for i in ids),
            f"catalog carries no namespaced ids ({len(ids)} models)",
        )
        alias = "openrouter/gpt-5.4"
        try:
            await rpc.call("router.hold.set", {"key": SESSION, "model": alias})
            check(False, f"{alias} was pinned despite being outside the catalog")
        except RuntimeError as exc:
            check("unknown_model" in str(exc), f"{alias} refused — outside the catalog")

        # ── 5. a bogus model is refused ─────────────────────────────────────
        print("\n5. refuse an unknown model")
        try:
            await rpc.call("router.hold.set", {"key": SESSION, "model": "no-such-model-xyz"})
            check(False, "bogus model was accepted (should have been refused)")
        except RuntimeError as exc:
            check("unknown_model" in str(exc), f"bogus model refused ({str(exc)[:60]})")

        # ── 6. clear returns to automatic routing ───────────────────────────
        print("\n6. clear the pin")
        cleared = await rpc.call("router.hold.clear", {"key": SESSION})
        check(cleared.get("cleared") is True, "hold.clear reports cleared")
        read = await rpc.call("router.hold.get", {"key": SESSION})
        check(read.get("hold") is None, "hold.get reports no pin")

        decision = await rpc.turn("auto")
        source = (decision or {}).get("source")
        check(
            source not in (None, "router_control_hold"),
            f"LIVE TURN routed automatically (source={source!r}, "
            f"model={(decision or {}).get('model')!r})",
        )

        # ── cleanup ─────────────────────────────────────────────────────────
        try:
            await rpc.call("sessions.delete", {"key": SESSION})
            print("\n(throwaway session deleted)")
        except Exception as exc:  # noqa: BLE001 - cleanup is best-effort
            print(f"\n(could not delete throwaway session: {str(exc)[:80]})")

        pump.cancel()

    failed = [d for ok, d in results if not ok]
    print(f"\n{'=' * 60}\n{len(results) - len(failed)}/{len(results)} checks passed")
    for d in failed:
        print(f"  FAILED: {d}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

"""Simple economy system that updates wallets and inventories via events."""

from __future__ import annotations

import logging
from typing import Callable, Dict

from core.logging_config import get_logger, log_with_fields
from core.registry import Registry
from systems.event_bus import Event, EventBus
from systems.combat import CombatSystem
from world.entities import Item


class EconomySystem:
    """Responds to reward and purchase events."""

    def __init__(
        self,
        bus: EventBus,
        *,
        item_registry: Registry[Item],
        combat_system: CombatSystem,
    ) -> None:
        self.bus = bus
        self.item_registry = item_registry
        self.combat_system = combat_system
        self.wallets: Dict[str, int] = {}
        self.stores: Dict[str, Dict[str, int]] = {}
        self.logger = get_logger(__name__)

        self.bus.subscribe("quest.completed", self._handle_reward)
        self.bus.subscribe("economy.reward", self._handle_reward)
        self.bus.subscribe("economy.purchase", self._handle_purchase)
        self.bus.subscribe("economy.sell", self._handle_sell)
        self.bus.subscribe("economy.repair", self._handle_repair)
        self.bus.subscribe("trade.execute", self._handle_trade)

    def sync_wallet(self, name: str, gold: int) -> None:
        self.wallets[name] = gold
        log_with_fields(self.logger, logging.DEBUG, "Synced wallet", character=name, gold=gold)

    def register_store(self, store_name: str, price_lookup: Dict[str, int]) -> None:
        self.stores[store_name] = price_lookup
        log_with_fields(self.logger, logging.INFO, "Registered store", store=store_name, items=len(price_lookup))

    def _handle_reward(self, event: Event) -> Dict[str, int]:
        owner = event.payload.get("owner") or event.payload.get("recipient")
        reward = int(event.payload.get("reward_gold", event.payload.get("amount", 0)))
        if not owner:
            return {"gold": 0}
        self.wallets[owner] = self.wallets.get(owner, 0) + reward
        log_with_fields(self.logger, logging.INFO, "Granted reward", owner=owner, gold=self.wallets[owner])
        return {"gold": self.wallets[owner]}

    def _handle_purchase(self, event: Event) -> Dict[str, object]:
        buyer = event.payload["buyer"]
        store_name = event.payload["store"]
        item_name = event.payload["item"]
        modifier: Callable[[int], int] | None = event.payload.get("price_modifier")

        price_lookup = self.stores.get(store_name, {})
        base_price = price_lookup.get(item_name)
        if base_price is None:
            raise KeyError(f"{store_name} does not sell {item_name}")
        final_price = modifier(base_price) if modifier else base_price

        balance = self.wallets.get(buyer, 0)
        if balance < final_price:
            raise ValueError(f"{buyer} cannot afford {item_name}")

        self.wallets[buyer] = balance - final_price
        self.combat_system.add_item(buyer, item_name, reason="purchase")
        log_with_fields(
            self.logger,
            logging.INFO,
            "Purchase complete",
            buyer=buyer,
            store=store_name,
            item=item_name,
            remaining_gold=self.wallets[buyer],
        )
        return {"remaining_gold": self.wallets[buyer], "item": item_name}

    def _handle_sell(self, event: Event) -> Dict[str, object]:
        seller = event.payload["seller"]
        store_name = event.payload["store"]
        item_name = event.payload["item"]
        price_lookup = self.stores.get(store_name, {})
        base_price = price_lookup.get(item_name)
        if base_price is None:
            raise KeyError(f"{store_name} does not buy {item_name}")

        removed = self.combat_system.remove_item(seller, item_name)
        if not removed:
            raise ValueError(f"{seller} cannot sell what they do not own")

        payout = max(1, base_price // 2)
        self.wallets[seller] = self.wallets.get(seller, 0) + payout
        log_with_fields(
            self.logger,
            logging.INFO,
            "Item sold",
            seller=seller,
            store=store_name,
            item=item_name,
            payout=payout,
            balance=self.wallets[seller],
        )
        return {"payout": payout, "balance": self.wallets[seller]}

    def _handle_repair(self, event: Event) -> Dict[str, object]:
        owner = event.payload["owner"]
        item_name = event.payload["item"]
        rate = int(event.payload.get("rate", 1))
        details = self.combat_system.repair_item(owner, item_name)
        cost = details["restored"] * rate
        balance = self.wallets.get(owner, 0)
        if balance < cost:
            raise ValueError(f"{owner} cannot afford repairs for {item_name}")
        self.wallets[owner] = balance - cost
        log_with_fields(
            self.logger,
            logging.INFO,
            "Repaired gear",
            owner=owner,
            item=item_name,
            cost=cost,
            balance=self.wallets[owner],
        )
        return {"cost": cost, "balance": self.wallets[owner]}

    def _handle_trade(self, event: Event) -> Dict[str, object]:
        giver = event.payload["giver"]
        receiver = event.payload["receiver"]
        items: list[str] = event.payload.get("items", [])
        gold: int = int(event.payload.get("gold", 0))

        for item_name in items:
            item = self.combat_system.remove_item(giver, item_name)
            if item:
                self.combat_system.add_item(receiver, item_name, reason="trade")

        if gold:
            self.wallets[giver] = self.wallets.get(giver, 0) - gold
            self.wallets[receiver] = self.wallets.get(receiver, 0) + gold

        log_with_fields(
            self.logger,
            logging.INFO,
            "Trade completed",
            giver=giver,
            receiver=receiver,
            items=len(items),
            gold=gold,
        )
        return {"giver": giver, "receiver": receiver, "items": items, "gold": gold}

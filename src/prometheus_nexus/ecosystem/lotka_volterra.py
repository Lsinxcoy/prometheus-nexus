"""LotkaVolterra — Predator-prey ODE system with RK4 integration.

Based on the classic Lotka-Volterra equations:
    dx/dt = αx - βxy     (prey)
    dy/dt = δxy - γy     (predator)

Uses 4th-order Runge-Kutta for numerical stability (not bare Euler).
Supports multi-species chain predation.
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

import copy


class LotkaVolterra:
    """Predator-prey dynamics with RK4 ODE integration.

    Usage:
        lv = LotkaVolterra()
        lv.add_species("prey", initial_pop=100, growth_rate=1.0)
        lv.add_species("predator", initial_pop=20, growth_rate=0.5, prey="prey", predation_rate=0.01)
        result = lv.simulate(dt=0.01, steps=1000)
    """

    def __init__(self):
        self._species: dict[str, dict] = {}
        self._simulations: list[dict] = []
        self._history: dict[str, list[float]] = {}
        self._default_death_rate = 0.5

    def add_species(self, name: str, initial_pop: float = 100.0, growth_rate: float = 1.0,
                    prey: str | None = None, predation_rate: float = 0.1,
                    death_rate: float = 0.5):
        self._species[name] = {
            "pop": max(0.01, initial_pop),
            "growth_rate": growth_rate,
            "prey": prey,
            "predation_rate": predation_rate,
            "death_rate": death_rate,
        }
        self._history[name] = [max(0.01, initial_pop)]

    def _derivatives(self, pops: dict[str, float]) -> dict[str, float]:
        """Compute dpop/dt for each species."""
        derivs = {}
        for name, sp in self._species.items():
            pop = pops[name]
            if sp["prey"] and sp["prey"] in pops:
                prey_pop = pops[sp["prey"]]
                derivs[name] = sp["predation_rate"] * prey_pop * pop - sp["death_rate"] * pop
            else:
                total_predation = sum(
                    o["predation_rate"] * pops.get(n, 0)
                    for n, o in self._species.items() if o.get("prey") == name
                )
                derivs[name] = sp["growth_rate"] * pop - total_predation * pop
        return derivs

    def _rk4_step(self, pops: dict[str, float], dt: float) -> dict[str, float]:
        """4th-order Runge-Kutta integration step."""
        names = list(pops.keys())

        k1 = self._derivatives(pops)

        pops_k2 = {n: max(0.01, pops[n] + 0.5 * dt * k1.get(n, 0)) for n in names}
        k2 = self._derivatives(pops_k2)

        pops_k3 = {n: max(0.01, pops[n] + 0.5 * dt * k2.get(n, 0)) for n in names}
        k3 = self._derivatives(pops_k3)

        pops_k4 = {n: max(0.01, pops[n] + dt * k3.get(n, 0)) for n in names}
        k4 = self._derivatives(pops_k4)

        result = {}
        for n in names:
            new_pop = pops[n] + (dt / 6.0) * (k1.get(n, 0) + 2 * k2.get(n, 0) + 2 * k3.get(n, 0) + k4.get(n, 0))
            result[n] = max(0.01, new_pop)
        return result

    def simulate(self, dt: float = 0.01, steps: int = 100) -> dict:
        """Run RK4 simulation for given timesteps."""
        pops = {name: sp["pop"] for name, sp in self._species.items()}

        for _ in range(steps):
            pops = self._rk4_step(pops, dt)
            for name, pop in pops.items():
                self._species[name]["pop"] = pop
                self._history[name].append(pop)

        result = {name: sp["pop"] for name, sp in self._species.items()}
        self._simulations.append(result)
        return result

    def get_history(self, name: str) -> list[float]:
        return list(self._history.get(name, []))

    def get_phase_portrait(self, prey: str, predator: str) -> list[tuple[float, float]]:
        """Get (prey, predator) trajectory for phase portrait plotting."""
        prey_hist = self._history.get(prey, [])
        pred_hist = self._history.get(predator, [])
        return list(zip(prey_hist, pred_hist))

    def get_stats(self) -> dict:
        return {
            "species": len(self._species),
            "simulations": len(self._simulations),
            "history_length": max((len(h) for h in self._history.values()), default=0),
        }

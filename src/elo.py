"""Modul 2 — elo.py

Kronologisk Elo for tennis, både samlet og underlags-spesifikt
(Hard/Clay/Grass). K-faktor avtar med antall spilte kamper (Betfair/538-
formelen referert av evsnts-repoet):

    K(n) = K_FACTOR / (n + K_SHIFT) ** K_DECAY

Sannsynlighet via logistisk (Elo-)formel:

    P(A slår B) = 1 / (1 + 10 ** ((R_B - R_A) / 400))

Tre prediksjoner eksponeres: ren samlet, ren underlag, og en blanding
(vekt ELO_SURFACE_WEIGHT på underlag). Hvilken som er best avgjøres empirisk
i Modul 3 (calibrate).

Tilstanden (rating + kampteller pr. spiller pr. dimensjon) lagres til disk
slik at Elo kan oppdateres inkrementelt dag for dag uten full re-trening.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from . import config

# Dimensjonene vi rater: samlet ("all") + ett rating pr. underlag.
DIMENSIONS = ("all", *config.SURFACES)


def expected_score(r_a: float, r_b: float) -> float:
    """Forventet score (= P(A vinner)) gitt to ratinger."""
    return 1.0 / (1.0 + 10.0 ** ((r_b - r_a) / 400.0))


def k_factor(n_matches: int) -> float:
    """Avtagende K som funksjon av spilte kamper i den dimensjonen."""
    return config.ELO_K_FACTOR / (n_matches + config.ELO_K_SHIFT) ** config.ELO_K_DECAY


def _valid_rank(rank: object) -> bool:
    return rank is not None and not pd.isna(rank) and rank >= 1


def fit_rank_seed(matches: pd.DataFrame) -> tuple[float, float]:
    """Fit elo0 = A + B*ln(rank) på etablerte spillere (>=30 kamper) i datasettet.

    Brukes til å seede nye spillere fra inngangsrankingen. Fittes kun på det
    datasettet som sendes inn (kalibreringen sender treningsdata for å unngå
    lekkasje fra test-perioden).
    """
    model = EloModel(rank_seed=None)  # rå walk uten seeding for å samle (rank, elo)
    xs: list[float] = []
    ys: list[float] = []
    for row in matches.itertuples(index=False):
        w, l = int(row.winner_id), int(row.loser_id)
        for pid, rk in ((w, row.winner_rank), (l, row.loser_rank)):
            if model.count["all"][pid] >= 30 and _valid_rank(rk):
                xs.append(math.log(float(rk)))
                ys.append(model.rating["all"][pid])
        model.update_match(w, l, row.surface)
    if len(xs) < 100:
        return config.RANK_SEED_A, config.RANK_SEED_B
    b, a = np.polyfit(np.array(xs), np.array(ys), 1)
    return float(a), float(b)


class EloModel:
    """Holder Elo-tilstand og oppdaterer den kronologisk."""

    def __init__(self, rank_seed: tuple[float, float] | None = (config.RANK_SEED_A, config.RANK_SEED_B)) -> None:
        # Samlet ("all") rating starter alle på 1500, MEN nye spillere seedes fra
        # inngangsrankingen via rank_seed=(A,B): elo0 = A + B*ln(rank). Slik
        # unngår vi at en debutant ranket #80 starter likt med en futures-spiller.
        # Underlags-ratinger seedes fra spillerens samlede rating ved første kamp
        # på underlaget (ikke flatt 1500).
        self.rating: dict[str, dict[int, float]] = {"all": defaultdict(lambda: config.ELO_INIT)}
        self.count: dict[str, dict[int, int]] = {"all": defaultdict(int)}
        for s in config.SURFACES:
            self.rating[s] = {}
            self.count[s] = {}
        self.rank_seed = rank_seed
        self.last_date: pd.Timestamp | None = None
        self.n_matches: int = 0

    def _maybe_seed(self, player: int, rank: object) -> None:
        """Seed en spillers samlede rating fra rank ved aller første kamp."""
        if self.rank_seed is None or player in self.rating["all"]:
            return
        if _valid_rank(rank):
            a, b = self.rank_seed
            seed = a + b * math.log(float(rank))
            self.rating["all"][player] = float(min(max(seed, config.SEED_MIN), config.SEED_MAX))

    # --- oppslag ------------------------------------------------------------
    def _rating(self, dim: str, player: int) -> float:
        """Rating i en dimensjon. Underlag seedes fra samlet rating før første kamp."""
        if dim == "all":
            return self.rating["all"][player]
        if player in self.rating[dim]:
            return self.rating[dim][player]
        return self.rating["all"][player]  # seed fra samlet

    def _count(self, dim: str, player: int) -> int:
        if dim == "all":
            return self.count["all"][player]
        return self.count[dim].get(player, 0)

    def get(self, dim: str, player: int) -> float:
        return self._rating(dim, player)

    def probabilities(self, player_a: int, player_b: int, surface: str) -> dict[str, float]:
        """Rå modell-sannsynligheter for at A slår B på gitt underlag."""
        p_overall = expected_score(self._rating("all", player_a), self._rating("all", player_b))
        p_surface = expected_score(self._rating(surface, player_a), self._rating(surface, player_b))
        w = config.ELO_SURFACE_WEIGHT
        p_blend = w * p_surface + (1.0 - w) * p_overall
        return {"p_overall": p_overall, "p_surface": p_surface, "p_blend": p_blend}

    # --- oppdatering --------------------------------------------------------
    def _update_dim(self, dim: str, winner: int, loser: int) -> None:
        r_w = self._rating(dim, winner)
        r_l = self._rating(dim, loser)
        e_w = expected_score(r_w, r_l)  # forventet score for vinner
        k_w = k_factor(self._count(dim, winner))
        k_l = k_factor(self._count(dim, loser))
        # Vinner faktisk = 1, taper faktisk = 0. Asymmetrisk K pr. spiller.
        self.rating[dim][winner] = r_w + k_w * (1.0 - e_w)
        self.rating[dim][loser] = r_l + k_l * (0.0 - (1.0 - e_w))
        self.count[dim][winner] = self._count(dim, winner) + 1
        self.count[dim][loser] = self._count(dim, loser) + 1

    def update_match(
        self,
        winner: int,
        loser: int,
        surface: str,
        winner_rank: object = None,
        loser_rank: object = None,
    ) -> None:
        """Oppdater både samlet og underlags-Elo for én ferdigspilt kamp."""
        self._maybe_seed(winner, winner_rank)
        self._maybe_seed(loser, loser_rank)
        self._update_dim("all", winner, loser)
        self._update_dim(surface, winner, loser)
        self.n_matches += 1

    # --- kjøring over en match-tabell --------------------------------------
    def process(self, matches: pd.DataFrame, *, collect: bool = False) -> pd.DataFrame | None:
        """Gå kronologisk gjennom kampene.

        For hver kamp: (valgfritt) registrer en prediksjon laget FØR kampen
        med daværende ratinger, og oppdater så ratingene med utfallet.

        collect=True returnerer en DataFrame med én rad pr. kamp der spillerne
        er ordnet deterministisk (a = lavest id, b = høyest id) for å unngå
        label-lekkasje, label = 1 hvis a vant. Brukes til kalibrering.
        """
        records: list[dict] = [] if collect else []

        # itertuples er ~10x raskere enn iterrows for 100k+ rader.
        for row in matches.itertuples(index=False):
            winner = int(row.winner_id)
            loser = int(row.loser_id)
            surface = row.surface

            # Seed nye spillere FØR prediksjon, slik at en debutants rank
            # gjenspeiles i den aller første prediksjonen om ham.
            self._maybe_seed(winner, getattr(row, "winner_rank", None))
            self._maybe_seed(loser, getattr(row, "loser_rank", None))

            if collect:
                a, b = (winner, loser) if winner < loser else (loser, winner)
                label = 1 if a == winner else 0
                probs = self.probabilities(a, b, surface)
                records.append(
                    {
                        "date": row.date,
                        "season": row.season,
                        "tour": row.tour,
                        "surface": surface,
                        "a_id": a,
                        "b_id": b,
                        "label": label,
                        "winner_id": winner,
                        "loser_id": loser,
                        "winner_name": getattr(row, "winner_name", None),
                        "loser_name": getattr(row, "loser_name", None),
                        **probs,
                    }
                )

            self.update_match(winner, loser, surface)
            self.last_date = row.date

        return pd.DataFrame.from_records(records) if collect else None

    # --- persistens ---------------------------------------------------------
    def save(self, state_path: Path | None = None, meta_path: Path | None = None) -> None:
        state_path = state_path or config.ELO_STATE_PARQUET
        meta_path = meta_path or config.ELO_META_JSON
        rows = []
        for dim in DIMENSIONS:
            for player, rating in self.rating[dim].items():
                rows.append(
                    {
                        "player_id": player,
                        "dim": dim,
                        "rating": rating,
                        "count": self.count[dim][player],
                    }
                )
        pd.DataFrame(rows).to_parquet(state_path, index=False)
        meta = {
            "last_date": None if self.last_date is None else str(self.last_date),
            "n_matches": self.n_matches,
            "rank_seed": list(self.rank_seed) if self.rank_seed is not None else None,
        }
        meta_path.write_text(json.dumps(meta, indent=2))

    @classmethod
    def load(cls, state_path: Path | None = None, meta_path: Path | None = None) -> "EloModel":
        state_path = state_path or config.ELO_STATE_PARQUET
        meta_path = meta_path or config.ELO_META_JSON
        model = cls()
        if not Path(state_path).exists():
            return model
        df = pd.read_parquet(state_path)
        for row in df.itertuples(index=False):
            model.rating[row.dim][int(row.player_id)] = float(row.rating)
            model.count[row.dim][int(row.player_id)] = int(row.count)
        if Path(meta_path).exists():
            meta = json.loads(Path(meta_path).read_text())
            model.last_date = pd.Timestamp(meta["last_date"]) if meta.get("last_date") else None
            model.n_matches = int(meta.get("n_matches", 0))
            if meta.get("rank_seed") is not None:
                model.rank_seed = tuple(meta["rank_seed"])
        return model


def build_elo(matches: pd.DataFrame | None = None, *, save: bool = True, verbose: bool = True) -> EloModel:
    """Tren Elo kronologisk på hele tabellen og lagre tilstanden."""
    if matches is None:
        from .ingest import load_matches

        matches = load_matches()
    rank_seed = fit_rank_seed(matches)
    model = EloModel(rank_seed=rank_seed)
    model.process(matches, collect=False)
    if save:
        model.save()
    if verbose:
        print(
            f"  Elo trent på {model.n_matches:,} kamper t.o.m. {model.last_date}, "
            f"-> {config.ELO_STATE_PARQUET}",
            flush=True,
        )
    return model


def main() -> int:
    from .ingest import load_matches

    matches = load_matches()
    model = build_elo(matches)
    # Liten fornuftssjekk: topp 10 samlet Elo med navn fra siste forekomst.
    last_name = {}
    for row in matches.itertuples(index=False):
        last_name[int(row.winner_id)] = row.winner_name
        last_name[int(row.loser_id)] = row.loser_name
    top = sorted(model.rating["all"].items(), key=lambda kv: kv[1], reverse=True)[:10]
    print("Topp 10 samlet Elo (ved datasettets slutt):")
    for pid, r in top:
        print(f"  {r:7.1f}  {last_name.get(pid, pid)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

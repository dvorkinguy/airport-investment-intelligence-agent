"""Golden cases - the four questions the agent exists to answer.

Expectations are stated against ``services/agent/fixtures/dataset.json`` so a
case is graded by code, deterministically, with no database and no LLM judge.
The fixture is synthetic; what these cases prove is that the agent routes to the
right tool, carries the tool's exact numbers into the answer, and states its
assumptions - not that any particular airport is a good investment.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EvalCase:
    id: str
    question: str
    #: The answer is only credible if at least one of these tools was called.
    required_tools: tuple[str, ...]
    #: Each entry is a set of acceptable renderings of one required figure.
    required_numbers: tuple[tuple[str, ...], ...]
    #: Each entry is a set of acceptable spellings of one required fact.
    required_terms: tuple[tuple[str, ...], ...] = ()
    #: Substrings that must NOT appear - unhedged claims, invented framings.
    forbidden_terms: tuple[str, ...] = ()
    notes: str = ""
    optional_tools: tuple[str, ...] = field(default_factory=tuple)


CASES: tuple[EvalCase, ...] = (
    EvalCase(
        id="q1_new_england_expansion",
        question=(
            "Which airports in New England are the strongest candidates for terminal "
            "expansion investment? Rank them and explain the ranking."
        ),
        required_tools=("rank_airports",),
        required_numbers=(("78.4", "78"),),  # BOS opportunity score
        required_terms=(("bos", "boston"), ("pvd", "providence")),
        notes="Region filter must resolve to CT/ME/MA/NH/RI/VT; ranking comes from SQL.",
    ),
    EvalCase(
        id="q2_lax_vs_sna_congestion",
        question=(
            "Compare congestion at Los Angeles International (LAX) and John Wayne "
            "Airport in Santa Ana (SNA). Which is more congested and by how much?"
        ),
        required_tools=("compare_airports",),
        required_numbers=(
            ("24.3", "0.243"),  # LAX delay rate 2024
            ("18.7", "0.187"),  # SNA delay rate 2024
        ),
        required_terms=(("lax",), ("sna", "john wayne")),
        notes="Both sides must carry their own delay figures, not one plus a comparison.",
    ),
    EvalCase(
        id="q3_anchorage_long_haul",
        question="What percentage of flights out of Anchorage (ANC) are long-haul?",
        required_tools=("airport_metrics",),
        required_numbers=(("46.3", "0.463"),),
        required_terms=(("1,500", "1500"), ("anc", "anchorage")),
        notes="The long-haul threshold is an assumption and must be surfaced.",
        optional_tools=("resolve_airport",),
    ),
    EvalCase(
        id="q4_sfo_unmet_demand",
        question=(
            "How much unmet flight demand is there at San Francisco International "
            "(SFO), and what is driving it?"
        ),
        required_tools=("unmet_demand_estimate",),
        required_numbers=(("3,180,000", "3180000", "3.18", "3.2"),),
        required_terms=(("estimat",), ("load factor",), ("delay",)),
        notes="Must be labelled an estimate and explained through its drivers.",
    ),
)

#: Any answer of substance has to say what it assumed.
ASSUMPTION_MARKERS = ("assumption", "assumes", "assumed", "data vintage", "caveat")

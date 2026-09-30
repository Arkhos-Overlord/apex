"""The knowledge web: concepts as nodes, typed relations as edges.

apex originally modelled learning as a prerequisite *ladder*: each skill
listed the skills it depended on, and the only traversal available was
"what comes next". That renders as a chain, not a web, and it cannot
express the things a learner actually wants to know -- what is related to
what, what is easy to confuse with what, and where a concept sits inside a
larger subject.

So relations are typed here, and a skill is one node among several kinds:

* **skills** carry exercises and get mastery tracked against them.
* **concepts** are knowledge with no exercises yet. They are the frontier
  the graph grows into, which is what lets the curriculum be open-ended
  rather than a fixed list somebody wrote down.

Deliberately implemented on the standard library. A graph of this size
needs adjacency lookups, breadth-first traversal and a topological order,
all of which are a few lines each; pulling in NetworkX would make apex
fail to import on a machine that has not installed it, for no gain.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Iterator


class Relation(str, Enum):
    """The kinds of tie that can exist between two concepts.

    Subclasses ``str`` so a relation serialises into JSON as its value
    without a custom encoder, which matters because the dashboard sends
    these straight to the browser.
    """

    PREREQ = "prereq"
    """Hard dependency: you cannot read B before A."""

    RELATED = "related"
    """Adjacent material. Neither requires the other, but they illuminate
    each other -- variables and conditionals, loops and recursion."""

    CONTRASTS = "contrasts-with"
    """Two things learners routinely mix up. The edge is the warning."""

    PART_OF = "part-of"
    """Containment: sorting is part-of algorithms."""

    APPLIES_TO = "applies-to"
    """A technique used in a context -- exception handling applies-to
    parsing user input, not to arithmetic."""

    def __str__(self) -> str:
        return self.value


#: Relations that constrain what a learner may attempt. Everything else is
#: context: useful for navigation, irrelevant for ordering.
BLOCKING: frozenset[Relation] = frozenset({Relation.PREREQ})


@dataclass(frozen=True)
class Concept:
    """A node in the knowledge web.

    Attributes:
        id: Slug, unique across the graph.
        name: Display name.
        kind: ``"skill"`` (has exercises, gets mastery) or ``"concept"``
            (knowledge the graph can grow into).
        summary: One-line description.
        prereqs: Ids this concept depends on.
        related: Ids of adjacent concepts.
        contrasts: Ids of commonly-confused concepts.
        part_of: Ids of the broader subjects containing this concept.
        applies_to: Ids of contexts this concept is used in.
    """

    id: str
    name: str
    kind: str = "skill"
    summary: str = ""
    prereqs: tuple[str, ...] = ()
    related: tuple[str, ...] = ()
    contrasts: tuple[str, ...] = ()
    part_of: tuple[str, ...] = ()
    applies_to: tuple[str, ...] = ()

    def is_skill(self) -> bool:
        """Whether this concept carries exercises and mastery."""
        return self.kind == "skill"

    def edges(self) -> Iterator[tuple[Relation, str]]:
        """Every outgoing edge as ``(relation, target_id)``."""
        for relation, targets in (
            (Relation.PREREQ, self.prereqs),
            (Relation.RELATED, self.related),
            (Relation.CONTRASTS, self.contrasts),
            (Relation.PART_OF, self.part_of),
            (Relation.APPLIES_TO, self.applies_to),
        ):
            for target in targets:
                yield relation, target


@dataclass
class Edge:
    """A directed, typed tie between two concepts.

    Attributes:
        source: Origin concept id.
        target: Destination concept id.
        relation: How they are tied.
        confirmed: Whether a learner has accepted this edge. ``None`` means
            the edge came from the curated content and is assumed true;
            ``True``/``False`` are the learner's own verdicts.
    """

    source: str
    target: str
    relation: Relation
    confirmed: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "relation": self.relation.value,
            "confirmed": self.confirmed,
        }


class GraphError(Exception):
    """Raised when the graph is asked something it cannot answer."""


@dataclass
class KnowledgeGraph:
    """Concepts and their typed relations, with the traversals a learner needs.

    Attributes:
        concepts: Every node, keyed by id.
        edges: Every edge, keyed by ``(source, target, relation)``.
    """

    concepts: dict[str, Concept] = field(default_factory=dict)
    edges: dict[tuple[str, str, Relation], Edge] = field(default_factory=dict)

    # ── construction ─────────────────────────────────────────────────────

    def add_concept(self, concept: Concept) -> None:
        """Add a node, or replace one with the same id."""
        self.concepts[concept.id] = concept

    def add_edge(
        self,
        source: str,
        target: str,
        relation: Relation,
        confirmed: bool | None = None,
    ) -> None:
        """Add a typed edge between two concepts.

        Raises:
            GraphError: If either endpoint is not in the graph, or the
                relation is self-referential.
        """
        if source not in self.concepts:
            raise GraphError(f"unknown concept: {source!r}")
        if target not in self.concepts:
            raise GraphError(f"unknown concept: {target!r}")
        if source == target:
            raise GraphError(f"self-referential {relation.value} edge on {source!r}")
        self.edges[(source, target, relation)] = Edge(source, target, relation, confirmed)

    def set_confirmed(self, source: str, target: str, relation: Relation, confirmed: bool) -> None:
        """Record a learner's verdict on an existing edge.

        Raises:
            GraphError: If the edge does not exist. A verdict on an edge that
                was never proposed would silently do nothing otherwise.
        """
        key = (source, target, relation)
        if key not in self.edges:
            raise GraphError(f"no such edge: {source} -{relation.value}-> {target}")
        self.edges[key].confirmed = confirmed

    # ── queries ──────────────────────────────────────────────────────────

    def get(self, concept_id: str) -> Concept | None:
        return self.concepts.get(concept_id)

    def neighbours(
        self,
        concept_id: str,
        relation: Relation | None = None,
        *,
        include_incoming: bool = False,
    ) -> list[str]:
        """Ids reachable from *concept_id*.

        Args:
            concept_id: Where to start.
            relation: Restrict to one relation. ``None`` means any.
            include_incoming: Also follow edges pointing *at* this node,
                which is how you find what a concept is a prerequisite of.
        """
        out: list[str] = []
        for (src, tgt, rel) in self.edges:
            if rel in BLOCKING and relation is not None and rel is not relation:
                continue
            if relation is not None and rel is not relation:
                continue
            if src == concept_id:
                out.append(tgt)
            elif include_incoming and tgt == concept_id:
                out.append(src)
        return out

    def prereqs_of(self, concept_id: str) -> list[str]:
        return self.neighbours(concept_id, Relation.PREREQ)

    def dependents_of(self, concept_id: str) -> list[str]:
        """Concepts that require *concept_id*."""
        return self.neighbours(concept_id, Relation.PREREQ, include_incoming=True)

    def ancestors(self, concept_id: str) -> set[str]:
        """Every concept transitively required before *concept_id*."""
        seen: set[str] = set()
        queue = deque(self.prereqs_of(concept_id))
        while queue:
            current = queue.popleft()
            if current in seen:
                continue
            seen.add(current)
            queue.extend(self.prereqs_of(current))
        return seen

    def descendants(self, concept_id: str) -> set[str]:
        """Everything transitively unlocked by *concept_id*."""
        seen: set[str] = set()
        queue = deque(self.dependents_of(concept_id))
        while queue:
            current = queue.popleft()
            if current in seen:
                continue
            seen.add(current)
            queue.extend(self.dependents_of(current))
        return seen

    def is_unlocked(
        self,
        concept_id: str,
        mastered: Iterable[str],
        gates: Callable[[str], list[str]] | None = None,
    ) -> bool:
        """Whether every *blocking* prerequisite of *concept_id* is mastered.

        Args:
            concept_id: The node to test.
            mastered: Ids the learner has mastered.
            gates: Optional policy returning the subset of prerequisites
                that actually block.  ``None`` means every prerequisite
                blocks.  Supplying this matters when some prerequisites are
                orientation rather than examinations: if they are left to
                the default, a concept node that never accumulates mastery
                would lock its entire subtree away forever.

        Raises:
            GraphError: If *concept_id* is not a node.
        """
        if concept_id not in self.concepts:
            raise GraphError(f"unknown concept: {concept_id!r}")
        done = set(mastered)
        blocking = gates(concept_id) if gates is not None else self.prereqs_of(concept_id)
        return all(p in done for p in blocking)

    def frontier(
        self,
        mastered: Iterable[str],
        gates: Callable[[str], list[str]] | None = None,
    ) -> list[str]:
        """Un-mastered concepts whose blocking prerequisites are all satisfied.

        This is the growth edge of the web: what the learner is one step
        away from.  Ordering is stable by id so the UI does not reshuffle
        between refreshes.

        Args:
            mastered: Ids the learner has mastered.
            gates: See :meth:`is_unlocked`.
        """
        done = set(mastered)
        return sorted(
            cid
            for cid in self.concepts
            if cid not in done and self.is_unlocked(cid, done, gates)
        )


    def neighbourhoods(self, concept_id: str, depth: int = 1) -> list[str]:
        """Ids within *depth* hops, following non-blocking relations.

        Prerequisites are excluded: they are handled by
        :meth:`ancestors`, and following them here would walk the whole
        curriculum rather than the local neighbourhood the learner is
        actually looking at.
        """
        if concept_id not in self.concepts:
            raise GraphError(f"unknown concept: {concept_id!r}")
        seen = {concept_id}
        frontier = {concept_id}
        for _ in range(max(0, depth)):
            nxt: set[str] = set()
            for node in frontier:
                for (src, tgt, rel) in self.edges:
                    if rel in BLOCKING:
                        continue
                    for candidate in (src, tgt):
                        if candidate in seen:
                            continue
                        if src == node or tgt == node:
                            nxt.add(candidate)
            seen |= nxt
            frontier = nxt
        return sorted(seen - {concept_id})

    def skill_ids(self) -> list[str]:
        return [cid for cid, c in self.concepts.items() if c.is_skill()]

    def concept_ids(self) -> list[str]:
        return [cid for cid, c in self.concepts.items() if not c.is_skill()]

    # ── diagnostics ──────────────────────────────────────────────────────

    def find_cycles(self) -> list[list[str]]:
        """Prerequisite cycles, as node-id paths.

        A cycle in ``prereq`` means two concepts each require the other, so
        neither can ever be unlocked and the learner silently cannot reach
        them.
        """
        cycles: list[list[str]] = []
        state: dict[str, int] = {}  # 0 = visiting, 1 = done

        def walk(node: str, stack: list[str]) -> None:
            if state.get(node) == 1:
                return
            if node in stack:
                start = stack.index(node)
                cycles.append(stack[start:] + [node])
                return
            stack.append(node)
            state[node] = 0
            for nxt in self.prereqs_of(node):
                if nxt in self.concepts:
                    walk(nxt, stack)
            stack.pop()
            state[node] = 1

        for cid in self.concepts:
            walk(cid, [])
        return cycles

    def topological_order(self) -> list[str]:
        """All concept ids ordered so prerequisites come first.

        Raises:
            GraphError: If a prerequisite cycle exists, since no valid
                order does.
        """
        cycles = self.find_cycles()
        if cycles:
            raise GraphError(f"prerequisite cycle: {' -> '.join(cycles[0])}")

        indegree = {cid: len(self.prereqs_of(cid)) for cid in self.concepts}
        queue = deque(sorted(cid for cid, deg in indegree.items() if deg == 0))
        order: list[str] = []
        while queue:
            node = queue.popleft()
            order.append(node)
            for nxt in self.dependents_of(node):
                indegree[nxt] -= 1
                if indegree[nxt] == 0:
                    queue.append(nxt)
        return order

    def unreachable(self) -> list[str]:
        """Concepts no learner could ever reach from any entry point.

        Walks forward from every prerequisite-free node through
        ``dependents_of``.  Anything not reached is dead content -- a
        concept whose prerequisites include an unreachable node, so no
        amount of study unlocks it.  Surfaced by the health check.
        """
        reachable: set[str] = set()
        queue = deque(cid for cid in self.concepts if not self.prereqs_of(cid))
        while queue:
            node = queue.popleft()
            if node in reachable:
                continue
            reachable.add(node)
            queue.extend(self.dependents_of(node))
        return sorted(set(self.concepts) - reachable)

    def stats(self) -> dict[str, Any]:
        """Counts used by the dashboard and the eval harness."""
        by_relation: dict[str, int] = {}
        for (_, _, rel) in self.edges:
            by_relation[rel.value] = by_relation.get(rel.value, 0) + 1
        return {
            "concepts": len(self.concepts),
            "skills": len(self.skill_ids()),
            "concepts_only": len(self.concept_ids()),
            "edges": len(self.edges),
            "edges_by_relation": by_relation,
            "density": (
                round(2 * len(self.edges) / (len(self.concepts) * (len(self.concepts) - 1)), 4)
                if len(self.concepts) > 1
                else 0.0
            ),
        }

    def to_json(self) -> dict[str, Any]:
        """Serialise to the shape the dashboard consumes."""
        return {
            "nodes": [
                {
                    "id": c.id,
                    "name": c.name,
                    "kind": c.kind,
                    "summary": c.summary,
                }
                for c in self.concepts.values()
            ],
            "edges": [edge.to_dict() for edge in self.edges.values()],
            "stats": self.stats(),
        }

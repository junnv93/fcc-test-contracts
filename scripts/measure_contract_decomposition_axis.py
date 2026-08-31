"""Measure which decomposition axis a contract surface's history actually wants.

A contract surface (``HEADLESS_API_*``, ``PLATFORM_API_*``) is a set of tables
keyed in parallel by operation id -- routes, permissions, path parameters,
operation contracts -- plus the component schemas those operations reference.
There are two obvious ways to cut such a surface into modules:

*table axis*
    One module per kind of table. Every route declaration together, every
    schema together, every DTO together. This is what the file names suggest,
    and it is what both surfaces in this repository were first split along.

*surface axis*
    One module per route family. A single operation's route, permission,
    schema and contract entry live in one file, and different route families
    live in different files.

**Which one is right is not a matter of taste, and it is not readable off the
file listing.** It is a property of how the surface is actually edited, and
that property is in the git history. On 2026-08-29 the central surface was
measured this way and the answer overturned the shape it already had: the
table axis put 34 of 82 commits across four or more regions, while the surface
axis kept 48 of the 52 operation-touching commits (92%) inside one family.

That measurement was done by hand and thrown away, so the next surface had to
rebuild it -- which is this file. It is a script rather than a notebook cell
because the question recurs once per surface, and an answer nobody can re-run
is an anecdote.

## What it does

For every non-merge commit that touched the surface, each changed line is
mapped to the **top-level AST region that contained it in that commit's own
tree** -- not in today's tree. Line numbers move; declarations do not. Regions
are resolved two levels deep, so a hunk inside a dict literal resolves to the
dict *key* it landed in, which is what makes per-operation attribution
possible at all.

Each region is then classified on both axes and two statistics come out:

``table_axis``
    How many commits touched N or more distinct table regions. High is bad:
    it means the table axis forces one logical change across many files.

``surface_axis``
    Of the commits that touched operation-attributable regions, how many
    stayed inside exactly one route family. High is good.

## What it deliberately does not do

It does not name the tables, the modules or the route families. Every one of
those is derived -- the routes table is *the top-level dict whose values are
(method, path) pairs*, the operation tables are *the dicts keyed by the route
table's keys*, and the route families are *literal path segments*, measured at
every depth so the data picks the granularity instead of the author.

Nor does it decide anything. It prints numbers. Whether they justify moving a
surface is a judgement made in an evaluation document, against the cost of
moving it.
"""
from __future__ import annotations

import argparse
import ast
from collections import defaultdict
from dataclasses import dataclass, field
import json
from fnmatch import fnmatch
from pathlib import Path
import re
import subprocess
import sys
from typing import Iterable, Iterator, Optional

#: A path segment that names an instance rather than a resource family.
#: ``/projects/{project_id}/test-plan`` is one family however many projects
#: exist, so the parameter segment carries no grouping information and is
#: dropped before a prefix is taken.
_PARAM_SEGMENT = re.compile(r'^\{.+\}$')

#: ``git diff -U0`` hunk header. Zero context on purpose: with context lines a
#: one-line edit reports as touching its neighbours, which at a dict-key
#: granularity means touching the neighbouring *operations*.
_HUNK = re.compile(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@')

#: How many distinct regions a single commit must touch before that commit is
#: evidence *against* the axis being measured. Four is the threshold the
#: central-surface measurement used; it is exposed so a re-run can show the
#: whole curve rather than one point on it.
DEFAULT_SCATTER_THRESHOLD = 4


# ----------------------------------------------------------------- git I/O

class Git:
    """Every subprocess call lives here so the analysis below is pure."""

    def __init__(self, repo: Path) -> None:
        self.repo = repo

    def _run(self, *args: str, binary: bool = False):
        result = subprocess.run(
            ['git', '-C', str(self.repo), *args],
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            return b'' if binary else ''
        return result.stdout if binary else result.stdout.decode('utf-8', 'replace')

    def history(self, paths: Iterable[str]) -> dict[str, set[str]]:
        """Commit -> the surface paths it touched, **as named in that commit**.

        Two different things move a contract surface's files and only one of
        them is a rename:

        *move* -- the file changes path (central's shared-kernel move). Git
        detects it, and without ``--follow`` the walk stops dead at the move:
        measured here, that is 83 commits with it and **2** without.

        *split* -- declarations leave for new modules while the original
        survives as a facade (headless's cleanup-B2). Git sees additions, not a
        rename, so ``--follow`` finds nothing to follow and the pre-split
        history stays attached to the original path.

        Following per path and taking the union handles both, because the
        pre-split path is itself part of the surface. The returned path is the
        historical one, so a blob can actually be fetched at that revision --
        intersecting against *today's* paths would silently drop every commit
        from before a move.
        """
        touched: dict[str, set[str]] = defaultdict(set)
        for path in paths:
            out = self._run(
                'log', '--no-merges', '--follow', '--name-status',
                '--format=%x01%H', '--', path,
            )
            commit = None
            for line in out.splitlines():
                if line.startswith('\x01'):
                    commit = line[1:].strip()
                    continue
                if not line.strip() or commit is None:
                    continue
                fields = line.split('\t')
                if len(fields) < 2:
                    continue
                touched[commit].add(fields[-1].strip())
        return dict(touched)

    def order(self, commits: Iterable[str]) -> list[str]:
        """Oldest first, using the repository's own topology."""
        wanted = set(commits)
        walked = self._run('rev-list', '--no-merges', '--reverse', 'HEAD').splitlines()
        seen = [c.strip() for c in walked if c.strip() in wanted]
        return seen + sorted(wanted - set(seen))

    def commit_meta(self, commit: str) -> tuple[str, str]:
        out = self._run('log', '-1', '--format=%ad%x00%s', '--date=short', commit)
        date, _, subject = out.partition('\x00')
        return date.strip(), subject.strip()

    def file_at(self, commit: str, path: str) -> Optional[str]:
        blob = self._run('show', f'{commit}:{path}', binary=True)
        if not blob:
            return None
        return blob.decode('utf-8', 'replace')

    def surface_files_at(self, commit: str, directories: Iterable[str],
                         pattern: str) -> list[str]:
        """Every surface file that EXISTED at this commit.

        The surface model has to be rebuilt per revision, so it needs the whole
        surface as of that revision -- not just the files the commit touched. A
        commit that edits only the schema module still has to be read against
        the routes table that existed alongside it.
        """
        found: list[str] = []
        for directory in directories:
            out = self._run('ls-tree', '--name-only', f'{commit}:{directory}')
            for entry in out.splitlines():
                name = entry.strip()
                if name and fnmatch(name, pattern):
                    found.append(f'{directory}/{name}')
        return found

    def hunks(self, commit: str, path: str) -> list[tuple[range, range]]:
        """(before-lines, after-lines) touched by this commit in this path."""
        out = self._run(
            'diff', '-U0', '--no-color', f'{commit}^', commit, '--', path
        )
        if not out:
            # Root commit, or an addition with no parent to diff against.
            out = self._run(
                'diff', '-U0', '--no-color',
                '4b825dc642cb6eb9a060e54bf8d69288fbee4904', commit, '--', path
            )
        spans: list[tuple[range, range]] = []
        for line in out.splitlines():
            match = _HUNK.match(line)
            if not match:
                continue
            old_start, old_len, new_start, new_len = match.groups()
            old_count = 1 if old_len is None else int(old_len)
            new_count = 1 if new_len is None else int(new_len)
            spans.append((
                range(int(old_start), int(old_start) + old_count),
                range(int(new_start), int(new_start) + new_count),
            ))
        return spans


# ------------------------------------------------------- region resolution

@dataclass(frozen=True)
class Region:
    """Where a changed line landed, in declaration terms.

    ``key`` is the dict key when the top-level statement is a dict literal --
    the granularity at which an operation can be told from its neighbours.
    """

    name: str
    key: Optional[str] = None
    module: str = ''

    def __str__(self) -> str:
        base = f'{self.name}[{self.key}]' if self.key else self.name
        return f'{self.module}:{base}' if self.module else base


class RegionIndex:
    """Maps a line number to its declaration, for ONE revision of ONE file."""

    def __init__(self, source: str, module: str = '') -> None:
        self._spans: list[tuple[int, int, Region]] = []
        self._module = module
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return
        for node in tree.body:
            name = _binding_name(node)
            if name is None:
                continue
            start, end = node.lineno, getattr(node, 'end_lineno', node.lineno)
            for key, key_start, key_end in _dict_key_spans(node):
                self._spans.append((key_start, key_end, Region(name, key, module)))
            self._spans.append((start, end, Region(name, None, module)))

    def resolve(self, line: int) -> Optional[Region]:
        """Innermost enclosing declaration, or None for module-level noise.

        None is a real answer, not a failure: imports, the module docstring and
        blank space between declarations belong to no contract entry, and
        counting them as one would make every import bump look like a
        cross-region change.
        """
        best: Optional[tuple[int, Region]] = None
        for start, end, region in self._spans:
            if start <= line <= end:
                width = end - start
                if best is None or width < best[0]:
                    best = (width, region)
        return best[1] if best else None


def _binding_name(node: ast.stmt) -> Optional[str]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return node.name
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name):
                return target.id
        return None
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return node.target.id
    return None


def _dict_key_spans(node: ast.stmt) -> Iterator[tuple[str, int, int]]:
    """Line span of each entry in a top-level dict literal."""
    value = getattr(node, 'value', None)
    if not isinstance(value, ast.Dict):
        return
    for key_node, value_node in zip(value.keys, value.values):
        if not isinstance(key_node, ast.Constant) or not isinstance(key_node.value, str):
            continue
        start = key_node.lineno
        end = getattr(value_node, 'end_lineno', value_node.lineno)
        yield key_node.value, start, end


# ---------------------------------------------------- surface introspection

@dataclass
class SurfaceModel:
    """The tables a contract surface declares, discovered rather than named."""

    routes: dict[str, tuple[str, str]]
    op_keyed_tables: set[str]
    schema_table: Optional[str]
    schema_refs: dict[str, set[str]]
    operation_schemas: dict[str, set[str]]
    module_of: dict[str, str] = field(default_factory=dict)

    @property
    def operations(self) -> set[str]:
        return set(self.routes)


def build_surface_model(module_sources: dict[str, str]) -> SurfaceModel:
    """Derive the surface's shape from its own source.

    Nothing here is a literal table name. The routes table is recognised by its
    *values* being ``(method, path)`` pairs; the operation-keyed tables by
    their keys matching the routes table's; the schema table by its values
    looking like JSON Schema. A surface that renames its tables is measured
    unchanged, and a surface that has no such tables reports so instead of
    silently measuring nothing.
    """
    literals: dict[tuple[str, str], ast.Dict] = {}
    module_of: dict[str, str] = {}
    for module, source in module_sources.items():
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in tree.body:
            name = _binding_name(node)
            if name is None:
                continue
            module_of.setdefault(name, module)
            value = getattr(node, 'value', None)
            if isinstance(value, ast.Dict):
                literals.setdefault((module, name), value)

    # Every routes-shaped table, merged. A surface that has been split along
    # the surface axis declares one small local table per module and assembles
    # them on a facade, so taking the first -- or the largest -- would measure
    # one route family and call it the surface. Merging is also what the facade
    # itself does, which is the point: the operation set is the union.
    routes: dict[str, tuple[str, str]] = {}
    routes_names: set[str] = set()
    for (_module, name), node in literals.items():
        pairs = _string_pair_entries(node)
        if pairs and len(pairs) == len(node.keys):
            routes.update(pairs)
            routes_names.add(name)

    op_keyed: set[str] = set(routes_names)
    if routes:
        for (_module, name), node in literals.items():
            if name in routes_names:
                continue
            keys = {
                k.value for k in node.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)
            }
            if keys and keys <= set(routes):
                op_keyed.add(name)

    # The schema map is the largest JSON-Schema-shaped table that is NOT keyed
    # by operation ids. The exclusion is load-bearing: a path-parameter map is
    # also a dict of dicts and was picked up as the schema table before it.
    schema_table = None
    best = 0
    for (_module, name), node in literals.items():
        if name in op_keyed:
            continue
        if _looks_like_schema_map(node) and len(node.keys) > best:
            schema_table, best = name, len(node.keys)

    return SurfaceModel(
        routes=routes,
        op_keyed_tables=op_keyed,
        schema_table=schema_table,
        schema_refs={},
        operation_schemas={},
        module_of=module_of,
    )


def _string_pair_entries(node: ast.Dict) -> dict[str, tuple[str, str]]:
    entries: dict[str, tuple[str, str]] = {}
    for key_node, value_node in zip(node.keys, node.values):
        if not (isinstance(key_node, ast.Constant) and isinstance(key_node.value, str)):
            continue
        if not isinstance(value_node, ast.Tuple) or len(value_node.elts) != 2:
            continue
        first, second = value_node.elts
        if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
            continue
        if not (isinstance(second, ast.Constant) and isinstance(second.value, str)):
            continue
        if not second.value.startswith('/'):
            continue
        entries[key_node.value] = (first.value, second.value)
    return entries


def _looks_like_schema_map(node: ast.Dict) -> bool:
    schemaish = 0
    for value_node in node.values:
        if not isinstance(value_node, ast.Dict):
            continue
        keys = {
            k.value for k in value_node.keys
            if isinstance(k, ast.Constant) and isinstance(k.value, str)
        }
        if keys & {'type', 'properties', 'allOf', 'anyOf', '$ref', 'enum'}:
            schemaish += 1
    return schemaish >= 2 and schemaish >= len(node.values) // 2


# ------------------------------------------------------------- axis mapping

def literal_segments(path: str) -> list[str]:
    """Path segments that name a resource family, parameters removed."""
    return [
        seg for seg in path.strip('/').split('/')
        if seg and not _PARAM_SEGMENT.match(seg)
    ]


def family_at_depth(path: str, depth: int) -> str:
    segments = literal_segments(path)
    return '/' + '/'.join(segments[:depth]) if segments else '/'


# --------------------------------------------------------------- reporting

@dataclass
class CommitObservation:
    commit: str
    date: str
    subject: str
    regions: set[Region]
    table_regions: set[str]
    modules: set[str]
    families: dict[int, set[str]]
    paths: dict[str, str]
    operations: set[str]
    operations_in_surface: int = 0
    table_names: frozenset[str] = frozenset()

    @property
    def operation_fraction(self) -> float:
        """Share of the surface's operations this one commit touched.

        A commit that creates the surface, or moves all of it, touches nearly
        every operation whatever axis the files are cut along -- so it carries
        no information about the axis while still landing in both the numerator
        and the denominator. Naming those commits by hand would be the bias
        this whole measurement exists to avoid, so they are named by this ratio
        instead.
        """
        if not self.operations_in_surface:
            return 0.0
        return len(self.operations) / self.operations_in_surface


def observe(
    git: Git,
    history: dict[str, set[str]],
    order: list[str],
    pattern: str,
    depths: range,
) -> list[CommitObservation]:
    """One observation per commit, each read against ITS OWN revision.

    The surface model is rebuilt per commit rather than taken from today. Table
    names move (``PLATFORM_API_ROUTES`` became a per-surface local ``ROUTES``
    on 2026-08-29) and so do route paths, so classifying a 2026-05 hunk with
    2026-08 vocabulary silently drops it into the unattributable bucket.
    """
    observations: list[CommitObservation] = []
    for commit in order:
        touched = sorted(history.get(commit, ()))
        if not touched:
            continue
        directories = sorted({p.rsplit('/', 1)[0] for p in touched})
        present = git.surface_files_at(commit, directories, pattern)
        sources: dict[str, str] = {}
        for path in present:
            blob = git.file_at(commit, path)
            if blob is not None:
                sources[path] = blob
        model = build_surface_model(sources)
        regions: set[Region] = set()
        for path in touched:
            after = git.file_at(commit, path)
            before = git.file_at(f'{commit}^', path)
            after_index = RegionIndex(after, path) if after is not None else None
            before_index = RegionIndex(before, path) if before is not None else None
            for old_span, new_span in git.hunks(commit, path):
                if before_index is not None:
                    for line in old_span:
                        found = before_index.resolve(line)
                        if found:
                            regions.add(found)
                if after_index is not None:
                    for line in new_span:
                        found = after_index.resolve(line)
                        if found:
                            regions.add(found)
        if not regions:
            continue
        date, subject = git.commit_meta(commit)
        operations = {
            r.key for r in regions
            if r.name in model.op_keyed_tables and r.key in model.operations
        }
        families = {
            d: {
                family_at_depth(model.routes[op][1], d)
                for op in operations
            }
            for d in depths
        }
        observations.append(CommitObservation(
            commit=commit,
            date=date,
            subject=subject,
            regions=regions,
            table_regions={r.name for r in regions},
            modules={r.module for r in regions if r.module},
            families=families,
            paths={op: model.routes[op][1] for op in operations},
            operations=operations,
            operations_in_surface=len(model.routes),
            table_names=frozenset(
                model.op_keyed_tables
                | ({model.schema_table} if model.schema_table else set())
            ),
        ))
    return observations


def render(observations: list[CommitObservation], depths: range, threshold: int,
           whole_surface_at: float) -> dict:
    total = len(observations)
    scatter_curve = {
        n: sum(1 for o in observations if len(o.table_regions) >= n)
        for n in range(2, 9)
    }
    module_curve = {
        n: sum(1 for o in observations if len(o.modules) >= n)
        for n in range(2, 7)
    }
    op_touching = [o for o in observations if o.operations]
    evolution = [o for o in op_touching if o.operation_fraction < whole_surface_at]
    whole_surface = [o for o in op_touching if o.operation_fraction >= whole_surface_at]

    def _family_stats(population: list[CommitObservation]) -> dict:
        stats = {}
        for d in depths:
            single = sum(1 for o in population if len(o.families[d]) == 1)
            stats[d] = {
                'single_family_commits': single,
                'op_touching_commits': len(population),
                'ratio': round(single / len(population), 4) if population else None,
                'distinct_families': len({
                    f for o in population for f in o.families[d]
                }),
            }
        return stats

    family_stats = _family_stats(op_touching)
    # The decision the caller actually faces is not "how many tables" -- table
    # counts are not comparable between surfaces that HAVE different numbers of
    # tables (four here, seven there, so "touched four" means "touched all" on
    # one side and "touched over half" on the other). It is: on the SAME
    # population of commits, how often does today's split keep a change in one
    # file, and how often would the surface axis?
    current_single_module = sum(1 for o in evolution if len(o.modules) == 1)
    return {
        'commits_analysed': total,
        'axis_comparison_on_one_population': {
            'population': 'operation-touching evolution commits',
            'commits': len(evolution),
            'current_split_single_module': current_single_module,
            'current_split_ratio': (
                round(current_single_module / len(evolution), 4)
                if evolution else None
            ),
            'current_split_modules_touched_median': (
                sorted(len(o.modules) for o in evolution)[len(evolution) // 2]
                if evolution else None
            ),
        },
        'table_axis': {
            'scatter_curve_regions': scatter_curve,
            'at_threshold': scatter_curve.get(threshold),
            'threshold': threshold,
            'scatter_curve_modules': module_curve,
        },
        'surface_axis': family_stats,
        'surface_axis_evolution_only': _family_stats(evolution),
        'operation_touching_commits': len(op_touching),
        'per_commit': [
            {
                'commit': o.commit[:8],
                'date': o.date,
                'modules': sorted(m.rsplit('/', 1)[-1] for m in o.modules),
                'tables': sorted(o.table_regions & o.table_names),
                'operations': sorted(o.operations),
                'families_d2': sorted(o.families.get(2, set())),
                'paths': o.paths,
                'whole_surface': o.operation_fraction >= whole_surface_at,
                'subject': o.subject[:80],
            }
            for o in observations
        ],
        'whole_surface_commits': {
            'threshold_fraction': whole_surface_at,
            'count': len(whole_surface),
            'commits': [
                {
                    'commit': o.commit[:8],
                    'date': o.date,
                    'operations_touched': len(o.operations),
                    'operations_in_surface': o.operations_in_surface,
                    'subject': o.subject[:70],
                }
                for o in whole_surface
            ],
        },
    }


# ------------------------------------------------------- co-change clustering

def cluster_curve(
    observations: list[CommitObservation],
    depth: int,
    whole_surface_at: float,
) -> list[dict]:
    """How well the surface axis can do at every possible module count.

    A route *family* is not a module. The surfaces this repository actually
    landed own several prefixes each -- ``artifact_custody`` and
    ``reference_catalog`` were named that way precisely because they carry a
    domain's project side and chamber side together. So comparing one surface's
    hand-designed grouping against another's raw depth-N buckets understates
    the second one, and the fix is to derive the grouping the same way the axis
    itself was derived: from what actually changes together.

    Families are merged greedily along the heaviest co-change edge. Merging is
    monotone -- fewer groups can only raise the single-group ratio, and the
    ratio reaches 100% when one group remains -- so the answer is not a number
    but the curve, and the judgement is where on it a surface should sit.
    """
    population = [
        o for o in observations
        if o.operations and o.operation_fraction < whole_surface_at
    ]
    groups: list[frozenset[str]] = [
        frozenset({f}) for f in sorted({
            f for o in population for f in o.families[depth]
        })
    ]
    if not groups:
        return []

    def ratio(current: list[frozenset[str]]) -> float:
        index = {f: i for i, g in enumerate(current) for f in g}
        single = sum(
            1 for o in population
            if len({index[f] for f in o.families[depth]}) == 1
        )
        return single / len(population)

    curve = [{
        'groups': len(groups),
        'single_group_ratio': round(ratio(groups), 4),
        'grouping': [sorted(g) for g in groups],
    }]
    while len(groups) > 1:
        best_pair, best_weight = None, -1
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                weight = sum(
                    1 for o in population
                    if (o.families[depth] & groups[i])
                    and (o.families[depth] & groups[j])
                )
                if weight > best_weight:
                    best_pair, best_weight = (i, j), weight
        i, j = best_pair
        merged = groups[i] | groups[j]
        groups = [g for k, g in enumerate(groups) if k not in (i, j)] + [merged]
        curve.append({
            'groups': len(groups),
            'single_group_ratio': round(ratio(groups), 4),
            'merged_weight': best_weight,
            'grouping': [sorted(g) for g in groups],
        })
    return curve


def table_bucket_scatter(
    observations: list[CommitObservation],
) -> dict[int, int]:
    """Scatter counted over CONTRACT TABLES only, not every declaration.

    The two granularities answer different questions and disagree by design: a
    commit that edits one operation touches its route, its permission and its
    contract entry (three tables) plus whatever helpers and constants moved
    with it (more declarations). Reporting only the finer one makes a surface
    look more tangled than its tables are.
    """
    counts: dict[int, int] = {}
    for n in range(2, 8):
        counts[n] = sum(
            1 for o in observations
            if len(o.table_regions & o.table_names) >= n
        )
    return counts


def score_grouping(
    observations: list[CommitObservation],
    grouping: dict[str, str],
    whole_surface_at: float,
) -> dict:
    """Score ONE proposed partition, resolving each commit against its own tree.

    ``grouping`` maps a route prefix to a module name; the longest matching
    prefix wins, exactly as a landed split resolves a path. Paths come from the
    commit's own route table, so an operation that has since been deleted still
    counts in the commit that touched it -- scoring against today's table drops
    it silently and inflates the result.
    """
    population = [
        o for o in observations
        if o.operations and o.operation_fraction < whole_surface_at
    ]

    def module_of(path: str) -> Optional[str]:
        best, best_len = None, -1
        for prefix, module in grouping.items():
            if (path == prefix or path.startswith(prefix + '/')) and len(prefix) > best_len:
                best, best_len = module, len(prefix)
        return best

    unresolved: set[str] = set()
    single = 0
    crossings: list[dict] = []
    for observation in population:
        modules = set()
        for op, path in observation.paths.items():
            module = module_of(path)
            if module is None:
                unresolved.add(path)
            else:
                modules.add(module)
        if len(modules) == 1:
            single += 1
        elif len(modules) > 1:
            crossings.append({
                'commit': observation.commit[:8],
                'modules': sorted(modules),
                'subject': observation.subject[:60],
            })
    return {
        'commits': len(population),
        'single_module_commits': single,
        'ratio': round(single / len(population), 4) if population else None,
        'unresolved_paths': sorted(unresolved),
        'crossings': crossings,
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--repo', default='.', type=Path)
    parser.add_argument(
        '--glob', required=True,
        help='repo-relative glob naming the surface, '
             'e.g. src/application/headless/api_contract*.py',
    )
    parser.add_argument('--threshold', type=int, default=DEFAULT_SCATTER_THRESHOLD)
    parser.add_argument('--max-depth', type=int, default=5)
    parser.add_argument('--json', type=Path, default=None)
    parser.add_argument('--per-commit', action='store_true')
    parser.add_argument(
        '--grouping', type=Path, default=None,
        help='JSON file mapping route prefix -> module name; scored on the '
             'same population as the derived curve',
    )
    parser.add_argument(
        '--cluster-depth', type=int, default=2,
        help='path depth whose route families are merged by co-change',
    )
    parser.add_argument(
        '--whole-surface-at', type=float, default=0.5,
        help='a commit touching at least this share of the operations that '
             'existed at its own revision is a birth/move, not an evolution',
    )
    args = parser.parse_args(argv)

    repo = args.repo.resolve()
    paths = sorted(
        str(p.relative_to(repo)).replace('\\', '/')
        for p in repo.glob(args.glob)
    )
    if not paths:
        print(f'no files matched {args.glob!r} under {repo}', file=sys.stderr)
        return 2

    sources = {p: (repo / p).read_text(encoding='utf-8') for p in paths}
    model = build_surface_model(sources)

    git = Git(repo)
    history = git.history(paths)
    order = git.order(history)
    depths = range(1, args.max_depth + 1)
    observations = observe(git, history, order, args.glob.rsplit('/', 1)[-1], depths)
    if not any(o.operations for o in observations):
        # Deliberately judged on the HISTORY, not on today's tree. A surface
        # whose facade assembles its tables declares no dict literal today, so
        # asking today's source whether a routes table exists answers "no" for
        # a surface that has had one in every revision being measured.
        print(
            'no commit resolved to an operation-keyed table — either this is '
            'not an operation-keyed contract surface, or the glob is too '
            'narrow to include the module that declares its routes',
            file=sys.stderr,
        )
        return 2
    report = render(observations, depths, args.threshold, args.whole_surface_at)
    report['table_axis']['scatter_curve_tables_only'] = table_bucket_scatter(
        observations
    )
    report['cluster_curve'] = {
        d: cluster_curve(observations, d, args.whole_surface_at)
        for d in (args.cluster_depth,)
    }
    if args.grouping:
        report['proposed_grouping'] = score_grouping(
            observations,
            json.loads(args.grouping.read_text(encoding='utf-8')),
            args.whole_surface_at,
        )
    report['surface'] = {
        'glob': args.glob,
        'modules': paths,
        'operations': len(model.routes),
        'op_keyed_tables': sorted(model.op_keyed_tables),
        'schema_table': model.schema_table,
    }

    print(json.dumps(report, indent=2, ensure_ascii=False))
    if args.per_commit:
        print('\n--- per commit ---', file=sys.stderr)
        for o in observations:
            print(
                f'{o.commit[:8]} {o.date} regions={len(o.table_regions):2} '
                f'modules={len(o.modules)} ops={len(o.operations):2} '
                f'fam@2={len(o.families.get(2, set()))} {o.subject[:60]}',
                file=sys.stderr,
            )
    if args.json:
        args.json.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

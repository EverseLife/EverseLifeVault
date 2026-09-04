# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""Surgical editing of a YAML file that is a list of blocks, with its comments kept.

Two files of the vault are shaped alike: `data/world.yaml` holds nodes and
`data/plants.yaml` holds cultures, and both are lists of entries where every
entry is a block of fields and half the file's worth is in the comments
between them. A YAML dumper would flatten those on the first save, so the
editing here happens at the line level: the lines of one field are found and
exactly those are replaced, and everything around them stays byte for byte.

What is generic lives here, and what is a file's own -- which key opens an
entry, which order its fields lie in, which of them are lists -- is passed in.
Written as one module rather than copied twice: the rules that keep a comment
standing over the thing it explains are subtle, they were arrived at by
breaking them, and two copies would drift apart on the first fix.

The safety net belongs to the callers and is the same three checks: the block
is parsed back and compared with what it was rendered from, the whole file is
parsed after the edit and must show exactly the intended change, and the file
must not have moved on disk while it was open.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import yaml
from vaultfile import VaultError, _comparable

#: Where a section begins: a key at the left margin.
SECTION = re.compile(r"^(\w+):\s*$")


@dataclass(frozen=True, slots=True)
class Block:
    """Where something lies in the file: the half-open line span `[start, end)`."""

    start: int
    end: int


@dataclass(frozen=True, slots=True)
class Entry:
    """One entry of a block list, with the comment that introduces it.

    Two spans, and the difference is what keeps the file readable. `lead` is
    where the comment above the entry begins; `start` is the entry's own line.
    **Replacing** an entry touches `[start, end)` and leaves the comment above
    it standing; **removing** one takes `[lead, end)`, because a comment left
    behind would then explain the machine below it, which it does not.
    """

    lead: int
    start: int
    end: int


#: One edit of the file: what to replace, with what, and which field it belongs
#: to. The rank settles the order of two edits that start on the same line.
Edit = tuple[Block, list[str], int]


def trim(lines: list[str], start: int, stop: int) -> int:
    """Where a span really ends: past its own last line of substance.

    Blank lines and the comments below them introduce what comes next, not what
    came before -- the comment explaining the floodplain stands under the mine's
    last vein, and a span that swallowed it would take the blank line with it
    every time that vein was edited.
    """
    while stop > start + 1 and (
        not lines[stop - 1].strip() or lines[stop - 1].lstrip().startswith("#")
    ):
        stop -= 1
    return stop


def scan_sections(lines: list[str]) -> dict[str, Block]:
    """Where each top-level section lies. `end` is past its last non-blank line."""
    heads: list[tuple[str, int]] = [
        (found.group(1), number)
        for number, line in enumerate(lines)
        if (found := SECTION.match(line))
    ]
    found_sections: dict[str, Block] = {}
    for index, (name, start) in enumerate(heads):
        stop = heads[index + 1][1] if index + 1 < len(heads) else len(lines)
        #: Blank lines and the next section's comments belong to what follows.
        found_sections[name] = Block(start + 1, trim(lines, start + 1, stop))
    return found_sections


def scan_blocks(lines: list[str], section: Block | None, head: re.Pattern[str]) -> dict[str, Block]:
    """Entry key -> the span of its block, the comments above it excluded.

    An entry's own comments stay put on an edit: the block starts at its head
    line, so whatever explains it above is never rewritten.
    """
    if section is None:
        return {}
    heads = [
        (found.group(1).strip(), number)
        for number in range(section.start, section.end)
        if (found := head.match(lines[number]))
    ]
    blocks: dict[str, Block] = {}
    for index, (key, start) in enumerate(heads):
        stop = heads[index + 1][1] if index + 1 < len(heads) else section.end
        #: Back off the blank lines and the next entry's comments.
        blocks[key] = Block(start, trim(lines, start, stop))
    return blocks


def scan_fields(lines: list[str], block: Block) -> dict[str, Entry]:
    """Field name -> the span of its lines inside one entry's block.

    A block-list field (`machines`, `feeding`) spans its header and every entry
    under it, comments between the entries included: those lines belong to the
    list, and the entry-wise edit below keeps them.
    """
    heads: list[tuple[str, int]] = []
    for number in range(block.start, block.end):
        line = lines[number]
        if number == block.start:
            body = line.removeprefix("  - ")
        elif line.startswith("    ") and not line.startswith("     "):
            #: A field of the entry sits at four spaces exactly: deeper than
            #: that is a line of a list or of a nested map, not a field.
            body = line[4:]
        else:
            continue
        if body.lstrip().startswith("#"):
            continue
        name, sep, _ = body.partition(":")
        if sep and name and not name.startswith(" "):
            heads.append((name.strip(), number))
    fields: dict[str, Entry] = {}
    floor = block.start + 1
    for index, (name, start) in enumerate(heads):
        stop = heads[index + 1][1] if index + 1 < len(heads) else block.end
        #: The comment block directly above introduces **this** field, and goes
        #: with it if it goes: left behind it would stand over the next field
        #: and explain something else -- «лес и каменистая земля у шахты» over
        #: the mine's veins. The same rule an entry of a list lives by, and for
        #: the same reason.
        lead = start
        while lead > floor and lines[lead - 1].lstrip().startswith("#"):
            lead -= 1
        end = trim(lines, start, stop)
        fields[name] = Entry(lead, start, end)
        floor = end
    return fields


def scan_entries(lines: list[str], block: Block) -> list[Entry]:
    """Every entry of a block list, and where its introducing comment starts."""
    heads = [
        number for number in range(block.start + 1, block.end) if lines[number].startswith("      - ")
    ]
    entries: list[Entry] = []
    for index, start in enumerate(heads):
        stop = heads[index + 1] if index + 1 < len(heads) else block.end
        #: The comment block directly above, back to the previous entry.
        floor = entries[-1].end if entries else block.start + 1
        lead = start
        while lead > floor and lines[lead - 1].lstrip().startswith("#"):
            lead -= 1
        entries.append(Entry(lead, start, trim(lines, start, stop)))
    return entries


def identity(entry: dict, keys: tuple[str, ...]) -> str:
    """What makes an entry itself: the thing it names.

    Entries are matched by this rather than by position, so removing the second
    machine of seven does not shift the other six onto each other's comments --
    the survivors are recognised and left exactly where they lie.

    Every naming key that the entry carries goes into it, not the first one
    alone: a machine has either a name or a class and one key is enough there,
    but a feeding row is named by its stage **and** its fertilizer -- the brome
    is fed twice in one stage, and the stage alone would call both rows the
    same thing.
    """
    said = [f"{key}:{entry[key]}" for key in keys if entry.get(key)]
    return "|".join(said)


def pair(was: list, now: list, keys: tuple[str, ...]) -> list[int | None]:
    """For each entry of `now`, which entry of `was` it is -- or None if it is new.

    Identity first, position second. Identity alone would treat a **renamed**
    machine as a removal and an addition, which loses its place in the list and
    the comment above it; position alone is what put those comments on the
    wrong machines to begin with. So the named survivors are pinned first, and
    whatever is left over on both sides is paired in order -- which is exactly
    the rename case.
    """
    taken: set[int] = set()
    found: list[int | None] = [None] * len(now)
    by_identity: dict[str, list[int]] = {}
    for index, entry in enumerate(was):
        by_identity.setdefault(identity(entry, keys), []).append(index)
    for index, entry in enumerate(now):
        queue = by_identity.get(identity(entry, keys)) or []
        while queue:
            candidate = queue.pop(0)
            if candidate not in taken:
                taken.add(candidate)
                found[index] = candidate
                break
    spare = [index for index in range(len(was)) if index not in taken]
    for index, at in enumerate(found):
        if at is None and spare:
            found[index] = spare.pop(0)
    return found


def edit_entries(
    lines: list[str],
    span: Block,
    key: str,
    was: list,
    now: list,
    rank: int,
    *,
    order: tuple[str, ...],
    names: tuple[str, ...],
) -> list[Edit]:
    """The changes to one block list, entry by entry."""
    entries = scan_entries(lines, span)
    #: A list the scan cannot see entry by entry -- one folded into block
    #: mappings by hand, say -- is **refused**, not rewritten whole. Rewriting
    #: it would drop every comment inside it silently, and this module exists
    #: to keep those. A refusal costs one hand edit; a silent loss costs the
    #: reason the file was written the way it was.
    if len(entries) != len(was):
        raise VaultError(
            f"список «{key}» записан не по одной записи в строку — "
            "правьте его в файле, иначе комментарии внутри пропадут"
        )

    paired = pair(was, now, names)
    edits: list[Edit] = []
    for index, at in enumerate(paired):
        if at is None:
            continue
        if _comparable(was[at]) != _comparable(now[index]):
            entry = entries[at]
            made = [render_flow(now[index], order, indent="      - ")]
            edits.append((Block(entry.start, entry.end), made, rank))
    for index, entry in enumerate(entries):
        if index not in {at for at in paired if at is not None}:
            #: Gone, and its comment with it: left behind, it would stand over
            #: the next entry and explain something else entirely.
            edits.append((Block(entry.lead, entry.end), [], rank))
    fresh = [now[index] for index, at in enumerate(paired) if at is None]
    if fresh:
        at = entries[-1].end if entries else span.end
        edits.append(
            (Block(at, at), [render_flow(one, order, indent="      - ") for one in fresh], rank)
        )
    return edits


def edit_fields(
    lines: list[str],
    block: Block,
    was: dict,
    now: dict,
    *,
    order: tuple[str, ...],
    head_key: str,
    render: Any,
    block_lists: tuple[str, ...] = (),
    entry_orders: dict[str, tuple[str, ...]] | None = None,
    entry_names: tuple[str, ...] = (),
) -> list[str]:
    """Apply one entry's changes line by line, leaving everything else untouched.

    Edits are applied **from the bottom up**, so an insertion never shifts a
    span below it. Two edits can start on the same line -- a field inserted
    right before the field that follows it -- and then the order matters twice
    over, which is what the sort key is for:

    * a **replacement** goes before an **insertion** at the same line (`end`
      decides): applied the other way round, the insertion would be written
      over by the replacement that follows it;
    * of two **insertions** at the same line, the later field goes first
      (`rank` decides), so the earlier one ends up above it and the block comes
      out in the canonical order rather than backwards.
    """
    fields = scan_fields(lines, block)
    edits: list[Edit] = []
    #: Where a field that is new to this entry goes: after the last field that
    #: precedes it in the canonical order and is already in the file.
    seat = block.start + 1
    for rank, key in enumerate(order):
        span = fields.get(key)
        if key in now and _comparable(now.get(key)) == _comparable(was.get(key)):
            if span is not None:
                seat = span.end
            continue
        if key not in now:
            if span is not None:
                #: From `lead`, so the field's own comment leaves with it.
                edits.append((Block(span.lead, span.end), [], rank))
            continue
        if span is None:
            edits.append((Block(seat, seat), render(key, now[key], head=(key == head_key)), rank))
            continue
        if key in block_lists:
            edits.extend(
                edit_entries(
                    lines,
                    Block(span.start, span.end),
                    key,
                    was.get(key) or [],
                    now[key],
                    rank,
                    #: A list without an order would render every entry as an
                    #: empty mapping -- the data gone without a word. Named
                    #: here rather than defaulted, so the mistake is a refusal.
                    order=_order_of(entry_orders, key),
                    names=entry_names,
                )
            )
        else:
            #: From `start`, not `lead`: the field stays, and so does what
            #: explains it.
            edits.append(
                (Block(span.start, span.end), render(key, now[key], head=(key == head_key)), rank)
            )
        seat = span.end
    out = list(lines)
    for span, made, _ in sorted(
        edits, key=lambda one: (one[0].start, one[0].end, one[2]), reverse=True
    ):
        out[span.start : span.end] = made
    return out


# ----------------------------------------------------------------- rendering


def _order_of(orders: dict[str, tuple[str, ...]] | None, key: str) -> tuple[str, ...]:
    order = (orders or {}).get(key)
    if not order:
        raise VaultError(f"список «{key}»: не задан порядок ключей записи")
    return order


def render_flow(data: dict, order: tuple[str, ...], *, indent: str) -> str:
    """One entry as a flow mapping on a single line."""
    body = ", ".join(f"{key}: {scalar(data[key])}" for key in order if key in data)
    return f"{indent}{{{body}}}"


def mapping(value: dict) -> str:
    return "{" + ", ".join(f"{name}: {scalar(one)}" for name, one in value.items()) + "}"


#: Words YAML reads as something other than a string, and so must be quoted.
_RESERVED = {"true", "false", "null", "yes", "no", "on", "off", "~", ""}
#: Characters that end a scalar inside a flow mapping, or start a special one.
_NEEDS_QUOTES = re.compile(r"^[-?:,\[\]{}#&*!|>'\"%@`]|[:,\[\]{}]|^\s|\s$")
#: The same, for a value that stands alone on its line: a comma and a brace are
#: ordinary text there, and quoting them would put quotes around half the notes
#: in the file. What still ends a value is a colon followed by a space, a hash
#: after one, a trailing colon, and the indicators that start something special.
_NEEDS_QUOTES_BLOCK = re.compile(r"^[-?:,\[\]{}#&*!|>'\"%@`]|:\s|\s#|:$|^\s|\s$")


def scalar(value: Any, *, flow: bool = True) -> str:
    """One value as YAML writes it. `flow` is "inside `{...}`", where more bites."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return f"{value:g}" if isinstance(value, float) else str(value)
    if isinstance(value, dict):
        return mapping(value)
    if isinstance(value, list):
        return "[" + ", ".join(scalar(one) for one in value) + "]"
    text = str(value)
    numeric = re.fullmatch(r"[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?", text)
    bites = _NEEDS_QUOTES if flow else _NEEDS_QUOTES_BLOCK
    if text.lower() in _RESERVED or numeric or bites.search(text):
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text


def round_trip(rendered: list[str], data: Any, what: str) -> None:
    """The rendered lines must read back as exactly what they were made from."""
    body = "\n".join(line[2:] if line.startswith("  ") else line for line in rendered)
    try:
        read = yaml.safe_load(body)
    except yaml.YAMLError as error:
        raise VaultError(f"{what} не читается обратно: {error}") from error
    if isinstance(read, list) and len(read) == 1 and not isinstance(data, list):
        read = read[0]
    if _comparable(read) != _comparable(data):
        raise VaultError(f"{what} записался бы не тем, чем задуман: {read} != {data}")


# ------------------------------------------------------------------ checking


def text_of(value: Any, what: str) -> str:
    said = str(value or "").strip()
    if not said:
        raise VaultError(f"{what}: пусто")
    return said


def number_of(
    value: Any,
    what: str,
    *,
    above: float | None = None,
    at_least: float | None = None,
    below: float | None = None,
) -> float:
    """A number the form sent, checked against the bounds the vault keeps.

    Two lower bounds because two things are meant and the difference bites:
    `above` is **strictly** greater -- a road of nought seconds and a vein of
    nought ore are not small, they are nonsense -- while `at_least` admits its
    own value, which is what a scale of one to five is. One parameter for both
    would make every caller's meaning a guess.
    """
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise VaultError(f"{what}: нужно число, а не «{value}»") from error
    if above is not None and number <= above:
        raise VaultError(f"{what}: больше {above:g}")
    if at_least is not None and number < at_least:
        raise VaultError(f"{what}: не меньше {at_least:g}")
    if below is not None and number > below:
        raise VaultError(f"{what}: не больше {below:g}")
    return int(number) if number.is_integer() else number

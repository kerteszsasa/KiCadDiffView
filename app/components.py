"""Snapshot-only extraction of physical KiCad components and semantic changes."""

from collections import defaultdict
import math
from pathlib import Path
import re

from .sexpr import children, first, loads


def _value(node, tag, default=''):
    item = first(node, tag)
    return item[1] if item and len(item) > 1 else default


def _properties(node):
    return {p[1]: p[2] for p in children(node, 'property') if len(p) >= 3}


def _natural(text):
    return tuple(int(p) if p.isdigit() else p.casefold() for p in re.split(r'(\d+)', text))


def _sort(record):
    return (_natural(record['reference']), record['sheet'], record['id'])


def _contained(root, path):
    path = path.resolve()
    if not path.is_relative_to(root):
        raise ValueError(f'Path escapes revision snapshot: {path}')
    return path


def _read(path, expected):
    try:
        node = loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(f'Cannot read {path.name}: {exc}') from exc
    if not node or node[0] != expected:
        raise ValueError(f'{path.name}: expected {expected} document')
    return node


def _flags(node):
    attr = first(node, 'attr', [])
    return {
        'dnp': _value(node, 'dnp', 'no') == 'yes' or 'dnp' in attr,
        'bom_excluded': _value(node, 'in_bom', 'yes') == 'no' or 'exclude_from_bom' in attr,
        'board_excluded': _value(node, 'on_board', 'yes') == 'no',
    }


def _number(text):
    try:
        number = float(text)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'Invalid placement number: {text!r}') from exc
    if not math.isfinite(number):
        raise ValueError(f'Invalid placement number: {text!r}')
    return int(number) if number.is_integer() else number


def _pcb(node):
    records = []
    for footprint in children(node, 'footprint') + children(node, 'module'):
        fields = _properties(footprint)
        for text in children(footprint, 'fp_text'):
            if len(text) > 2 and text[1] in ('reference', 'value'):
                fields.setdefault(text[1].capitalize(), text[2])
        reference = fields.get('Reference', '')
        if reference.startswith('#'):
            continue
        fields.setdefault('Footprint', footprint[1] if len(footprint) > 1 and isinstance(footprint[1], str) else '')
        for token, field in [('descr', 'Description'), ('tags', 'Tags')]:
            item = first(footprint, token)
            if item and len(item) > 1:
                fields.setdefault(field, item[1])
        path = _value(footprint, 'path')
        sheet = fields.get('Sheetname', path.rsplit('/', 1)[0] if '/' in path else '/') or '/'
        uuid = _value(footprint, 'uuid') or _value(footprint, 'tstamp')
        identity = f'pcb:{uuid}' if uuid else f'pcb:{sheet}:{reference}'
        at = first(footprint, 'at', ['at', '0', '0'])
        if len(at) < 3:
            raise ValueError(f'Invalid footprint placement: {reference}')
        layer = _value(footprint, 'layer')
        side = layer.split('.')[0] if layer in ('F.Cu', 'B.Cu') else layer
        records.append(dict(id=identity, reference=reference, sheet=sheet, fields=fields,
                            flags=_flags(footprint), placement={
                                'x': _number(at[1]), 'y': _number(at[2]),
                                'rotation': _number(at[3] if len(at) > 3 else '0'), 'side': side}))
    return sorted(records, key=_sort)


def _path_key(path):
    return '/' + '/'.join(p for p in path.split('/') if p)


def _instance_reference(symbol, project_name, instance_path):
    instances = first(symbol, 'instances', [])
    projects = children(instances, 'project')
    selected = [p for p in projects if len(p) > 1 and p[1] == project_name]
    if not selected:
        selected = [p for p in projects if len(p) > 1 and p[1] == '']
    for project in selected:
        for path in children(project, 'path'):
            if len(path) > 1 and _path_key(path[1]) == instance_path:
                reference = first(path, 'reference')
                if reference and len(reference) > 1:
                    return reference[1]
    return None



def _merge_unit_values(members):
    """Keep common fields simple and retain every conflicting member value.

    Member paths provide stable provenance without changing the record schema.
    Missing properties have no provenance entry, preserving absent versus empty.
    """
    members = sorted(members, key=lambda member: member[0])
    names = set().union(*(fields.keys() for _, fields, _ in members))
    fields = {}
    flags = {}
    missing = object()

    def provenance(member, category, name, value):
        key = f'unit[{member}].{category}.{name}'
        # All original custom properties survive even if a name happens to use
        # the provenance namespace. Prefix collisions deterministically.
        while key in names or key in fields:
            key = '@' + key
        fields[key] = value

    for name in sorted(names):
        values = [unit_fields.get(name, missing) for _, unit_fields, _ in members]
        fields[name] = next(value for value in values if value is not missing)
        if any(value != values[0] for value in values[1:]):
            for (member, _, _), value in zip(members, values):
                if value is not missing:
                    provenance(member, 'fields', name, value)
    for name in ('dnp', 'bom_excluded', 'board_excluded'):
        values = [unit_flags[name] for _, _, unit_flags in members]
        flags[name] = any(values)
        if any(value != values[0] for value in values[1:]):
            for (member, _, _), value in zip(members, values):
                provenance(member, 'flags', name, 'yes' if value else 'no')
    return fields, flags


def _schematic(root, root_path, project_name):
    cache = {}
    root_node = _read(root_path, 'kicad_sch')
    cache[root_path] = root_node
    root_uuid = _value(root_node, 'uuid')
    root_instance = '/' + root_uuid if root_uuid else '/'
    components = []
    legacy = {}

    def visit(path, instance_path, sheet_name, ancestors):
        if path in ancestors:
            raise ValueError(f'Cyclic schematic sheet reference: {path.name}')
        if not path.is_file():
            raise ValueError(f'Missing schematic sheet: {path.name}')
        if path not in cache:
            cache[path] = _read(path, 'kicad_sch')
        node = cache[path]
        local_legacy = dict(legacy)
        for entry in children(first(node, 'symbol_instances', []), 'path'):
            if len(entry) > 1:
                local_legacy[_path_key(entry[1])] = entry
        grouped = {}
        for symbol in children(node, 'symbol'):
            fields = _properties(symbol)
            uuid = _value(symbol, 'uuid') or _value(symbol, 'tstamp')
            reference = _instance_reference(symbol, project_name, instance_path)
            full_path = _path_key(instance_path + '/' + uuid)
            if reference is None and full_path in local_legacy:
                reference = _value(local_legacy[full_path], 'reference', None)
            if reference is None:
                reference = fields.get('Reference', '')
            lib_id = _value(symbol, 'lib_id')
            if reference.startswith('#') or lib_id.casefold().startswith('power:'):
                continue
            fields['Reference'] = reference
            if first(symbol, 'lib_id'):
                fields['lib_id'] = lib_id
            # Units sharing the annotated reference on this instance are one
            # physical component. Unannotated parts must retain separate IDs.
            group_key = (reference, lib_id, fields.get('Footprint')) if reference and not reference.endswith('?') else (reference, uuid)
            flags = _flags(symbol)
            member = full_path if uuid else _path_key(instance_path + '/ref:' + reference)
            unit = _value(symbol, 'unit', None)
            if group_key in grouped:
                record, members, units, member_values = grouped[group_key]
                members.add(member)
                units.add(unit)
                member_values.append((member, fields.copy(), flags.copy()))
                for name, value in fields.items():
                    record['fields'].setdefault(name, value)
                for name, value in flags.items():
                    record['flags'][name] |= value
            else:
                record = dict(id='', reference=reference, sheet=sheet_name,
                              fields=fields, flags=flags, placement={})
                grouped[group_key] = (record, {member}, {unit}, [(member, fields.copy(), flags.copy())])
        for record, members, units, member_values in grouped.values():
            record['id'] = 'sch:' + '+'.join(sorted(members))
            components.append((record, units, path, member_values))
        # Root symbol_instances (KiCad 6) can contain every descendant path.
        previous = dict(legacy)
        legacy.update(local_legacy)
        try:
            for index, sheet in enumerate(children(node, 'sheet')):
                props = _properties(sheet)
                filename = props.get('Sheetfile', props.get('Sheet file', ''))
                if not filename:
                    raise ValueError(f'{path.name}: sheet has no Sheetfile property')
                if '${KIPRJMOD}' in filename:
                    filename = filename.replace('${KIPRJMOD}', str(root_path.parent))
                sub_path = _contained(root, path.parent / filename)
                uuid = _value(sheet, 'uuid') or _value(sheet, 'tstamp') or f'sheet-{index}:{filename}'
                name = props.get('Sheetname', props.get('Sheet name', Path(filename).stem))
                child_instance = _path_key(instance_path + '/' + uuid)
                child_name = sheet_name.rstrip('/') + '/' + name
                visit(sub_path, child_instance, child_name, ancestors | {path})
        finally:
            legacy.clear()
            legacy.update(previous)

    visit(root_path, _path_key(root_instance), '/', set())
    # A physical package can have its logic and power units on different sheets.
    # Only merge unambiguous complementary units of the same library component.
    # Overlapping unit numbers or repeated source sheets indicate separate or
    # ambiguous instances, and must not collapse merely because refs coincide.
    candidates = defaultdict(list)
    for record, units, source, member_values in components:
        key = (record['reference'], record['fields'].get('lib_id'), record['fields'].get('Footprint'))
        candidates[key].append((record, units, source, member_values))
    records = []
    for (reference, lib_id, _), group in candidates.items():
        unit_sets = [units for _, units, _, _ in group]
        all_units = set().union(*unit_sets)
        distinct_units = None not in all_units and len(all_units) == sum(map(len, unit_sets))
        distinct_sources = len({source for _, _, source, _ in group}) == len(group)
        if len(group) < 2 or not reference or reference.endswith('?') or not lib_id or not distinct_units or not distinct_sources:
            for record, _, _, member_values in group:
                record['fields'], record['flags'] = _merge_unit_values(member_values)
                records.append(record)
            continue
        merged = group[0][0]
        merged['id'] = 'sch:' + '+'.join(sorted(record['id'][4:] for record, _, _, _ in group))
        merged['sheet'] = '; '.join(sorted({record['sheet'] for record, _, _, _ in group}))
        member_values = [member for _, _, _, values in group for member in values]
        merged['fields'], merged['flags'] = _merge_unit_values(member_values)
        records.append(merged)
    return sorted(records, key=_sort)


def extract_components(snapshot: Path, project_rel: str, kind: str) -> list[dict]:
    """Extract ``sch`` or ``pcb`` components using only files in ``snapshot``.

    Missing revision root files return an empty list. Missing children, cycles,
    invalid syntax, and paths resolving outside the snapshot raise ValueError.
    Schematic placement is empty: unit drawing coordinates are not PCB placement.
    """
    if kind not in ('sch', 'pcb'):
        raise ValueError(f'Unsupported component kind: {kind!r}')
    root = Path(snapshot).resolve()
    project = _contained(root, root / project_rel)
    document = _contained(root, project.with_suffix('.kicad_' + kind))
    if not document.exists():
        return []
    if kind == 'pcb':
        return _pcb(_read(document, 'kicad_pcb'))
    return _schematic(root, document, project.stem)


def compare_components(before: list, after: list) -> list[dict]:
    """Match identity, then unambiguous reference+sheet, and compare values.

    Identity metadata is used for matching, never reported as an electrical
    field change. Absent and explicitly empty property values remain distinct.
    """
    unmatched_before = set(range(len(before)))
    unmatched_after = set(range(len(after)))
    pairs = []
    for key in (lambda r: r.get('id'), lambda r: (r.get('reference'), r.get('sheet'))):
        left, right = defaultdict(list), defaultdict(list)
        for i in unmatched_before:
            left[key(before[i])].append(i)
        for i in unmatched_after:
            right[key(after[i])].append(i)
        for identity in left.keys() & right.keys():
            if identity is not None and len(left[identity]) == len(right[identity]) == 1:
                i, j = left[identity][0], right[identity][0]
                pairs.append((before[i], after[j]))
                unmatched_before.remove(i)
                unmatched_after.remove(j)
    pairs.extend((before[i], None) for i in sorted(unmatched_before))
    pairs.extend((None, after[i]) for i in sorted(unmatched_after))
    result = []
    for old, new in pairs:
        changes = []
        if old is not None and new is not None:
            for name in ('reference', 'sheet'):
                if old.get(name) != new.get(name):
                    changes.append(dict(field=name, before=old.get(name), after=new.get(name), category='field'))
            for group in ('fields', 'flags', 'placement'):
                old_values, new_values = old.get(group, {}), new.get(group, {})
                for name in sorted(old_values.keys() | new_values.keys()):
                    if old_values.get(name) != new_values.get(name):
                        changes.append(dict(field=group + '.' + name,
                                            before=old_values.get(name), after=new_values.get(name),
                                            category='placement' if group == 'placement' else 'field'))
        status = 'added' if old is None else 'removed' if new is None else 'changed' if changes else 'unchanged'
        current = new if new is not None else old
        result.append(dict(id=current['id'], reference=current['reference'], status=status,
                           before=old, after=new, changes=changes))
    return sorted(result, key=lambda r: _sort(r['after'] if r['after'] is not None else r['before']))

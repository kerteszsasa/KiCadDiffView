import copy
from pathlib import Path
import tempfile
import unittest

from app.sexpr import loads, children, first
from app.components import extract_components, compare_components


class SExpressionTests(unittest.TestCase):
    def test_strings_comments_and_direct_children(self):
        node = loads('; comment\n(root (property "árvíz" "a\\\"b\\\\c\\n") (n 1 -2.5) (nested (n 3)))')
        self.assertEqual(first(node, 'property')[1:], ['árvíz', 'a"b\\c\n'])
        self.assertEqual(children(node, 'n'), [['n', '1', '-2.5']])
        self.assertIsNone(first(node, 'missing'))
        self.assertEqual(first(node, 'missing', ['fallback']), ['fallback'])

    def test_malformed_input_is_rejected(self):
        for text in ['', '(x', '(x))', '(x) (y)', 'atom', '(x "unterminated)', '(x "trailing\\']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                loads(text)

    def test_deep_input_avoids_recursive_parser_limit(self):
        node = loads('(x ' * 1500 + 'a' + ')' * 1500)
        for _ in range(1499):
            node = node[1]
        self.assertEqual(node, ['x', 'a'])


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parents[1] / 'data' / 'test-tmp'
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def sch(self, body, name='demo.kicad_sch', uuid='root'):
        return self.write(name, f'(kicad_sch (uuid "{uuid}") {body})')

    def symbol(self, ref='R1', uuid='r1', extra='', instances='', unit=1):
        return f'''(symbol (lib_id "Device:R") (uuid "{uuid}") (unit {unit})
          (property "Reference" "{ref}") (property "Value" "10k")
          (property "Footprint" "R:0603") {extra} {instances})'''

    def extract(self, kind='sch'):
        return extract_components(self.root, 'demo.kicad_pro', kind)

    def test_absent_root_and_invalid_kind(self):
        self.assertEqual(self.extract(), [])
        self.assertEqual(self.extract('pcb'), [])
        with self.assertRaises(ValueError):
            self.extract('pdf')

    def test_schematic_properties_flags_and_virtual_omission(self):
        self.sch(self.symbol(extra='(property "Custom" "árvíz") (property "Empty" "") (dnp yes) (in_bom no) (on_board no)') + self.symbol('#PWR01', 'p'))
        records = self.extract()
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(set(record), {'id', 'reference', 'sheet', 'fields', 'flags', 'placement'})
        self.assertEqual(record['fields']['Custom'], 'árvíz')
        self.assertEqual(record['fields']['Empty'], '')
        self.assertEqual(record['fields']['lib_id'], 'Device:R')
        self.assertEqual(record['flags'], {'dnp': True, 'bom_excluded': True, 'board_excluded': True})
        self.assertEqual(record['sheet'], '/')
        self.assertEqual(record['placement'], {})
        self.assertIn('r1', record['id'])

    def test_repeated_sheet_instances_use_instance_reference(self):
        sheets = ''.join(f'(sheet (uuid "{uid}") (property "Sheetname" "{label}") (property "Sheetfile" "child.kicad_sch"))' for uid, label in [('a', 'Left'), ('b', 'Right')])
        self.sch(sheets)
        instances = '''(instances (project "another" (path "/root/a" (reference "WRONG")))
          (project "demo" (path "/root/a" (reference "R2")) (path "/root/b" (reference "R10"))))'''
        self.sch(self.symbol(instances=instances), 'child.kicad_sch', 'child-root')
        records = self.extract()
        self.assertEqual([r['reference'] for r in records], ['R2', 'R10'])
        self.assertEqual([r['sheet'] for r in records], ['/Left', '/Right'])
        self.assertEqual([r['fields']['Reference'] for r in records], ['R2', 'R10'])
        self.assertEqual(len({r['id'] for r in records}), 2)

    def test_multiunit_component_is_merged_and_identity_ignores_reference(self):
        self.sch(self.symbol('U1', 'unit-b', unit=2) + self.symbol('U1', 'unit-a'))
        before = self.extract()
        self.assertEqual(len(before), 1)
        self.assertIn('unit-a', before[0]['id'])
        self.assertIn('unit-b', before[0]['id'])
        self.sch(self.symbol('U9', 'unit-b', unit=2) + self.symbol('U9', 'unit-a'))
        after = self.extract()
        self.assertEqual(before[0]['id'], after[0]['id'])
        self.assertEqual(compare_components(before, after)[0]['status'], 'changed')

    def test_physical_multiunit_spanning_sheets_has_all_member_identities(self):
        child = '(sheet (uuid "power-sheet") (property "Sheetname" "Power") (property "Sheetfile" "power.kicad_sch"))'
        self.sch(self.symbol('U1', 'logic-unit', unit=1) + child)
        self.sch(self.symbol('U1', 'power-unit', '(property "PowerOnly" "yes") (dnp yes)', unit=3), 'power.kicad_sch', 'power-root')
        records = self.extract()
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertIn('/root/logic-unit', record['id'])
        self.assertIn('/root/power-sheet/power-unit', record['id'])
        self.assertIn('/Power', record['sheet'])
        self.assertEqual(record['fields']['PowerOnly'], 'yes')
        self.assertTrue(record['flags']['dnp'])
        self.sch(self.symbol('U9', 'logic-unit', unit=1) + child)
        self.sch(self.symbol('U9', 'power-unit', '(property "PowerOnly" "yes") (dnp yes)', unit=3), 'power.kicad_sch', 'power-root')
        after = self.extract()
        self.assertEqual(after[0]['id'], record['id'])
        self.assertEqual(compare_components(records, after)[0]['status'], 'changed')

    def test_same_sheet_conflicting_unit_property_keeps_member_provenance(self):
        def snapshot(value):
            self.sch(self.symbol('U1', 'a', '(property "Custom" "first")') + self.symbol('U1', 'b', f'(property "Custom" "{value}")', unit=2))
            return self.extract()
        before = snapshot('second')
        after = snapshot('changed')
        self.assertEqual(before[0]['fields']['Custom'], 'first')
        self.assertEqual(before[0]['fields']['unit[/root/a].fields.Custom'], 'first')
        self.assertEqual(before[0]['fields']['unit[/root/b].fields.Custom'], 'second')
        self.assertFalse(any(key.endswith('.fields.Value') for key in before[0]['fields']))
        change = {c['field']: c for c in compare_components(before, after)[0]['changes']}
        self.assertEqual(change['fields.unit[/root/b].fields.Custom']['before'], 'second')
        self.assertEqual(change['fields.unit[/root/b].fields.Custom']['after'], 'changed')

    def test_cross_sheet_conflicting_unit_property_keeps_member_provenance(self):
        child = '(sheet (uuid "power") (property "Sheetname" "Power") (property "Sheetfile" "power.kicad_sch"))'
        self.sch(self.symbol('U1', 'logic', '(property "Custom" "first")') + child)
        def snapshot(value):
            self.sch(self.symbol('U1', 'supply', f'(property "Custom" "{value}")', unit=3), 'power.kicad_sch', 'power-root')
            return self.extract()
        before = snapshot('second')
        after = snapshot('changed')
        self.assertEqual(len(before), 1)
        self.assertEqual(before[0]['fields']['unit[/root/power/supply].fields.Custom'], 'second')
        changes = {c['field']: c for c in compare_components(before, after)[0]['changes']}
        self.assertEqual(changes['fields.unit[/root/power/supply].fields.Custom']['after'], 'changed')

    def test_unit_flag_changes_are_visible_when_combined_flag_stays_true(self):
        def snapshot(dnp):
            self.sch(self.symbol('U1', 'a', '(dnp yes)') + self.symbol('U1', 'b', f'(dnp {dnp})', unit=2))
            return self.extract()
        before = snapshot('no')
        after = snapshot('yes')
        self.assertTrue(before[0]['flags']['dnp'])
        self.assertTrue(after[0]['flags']['dnp'])
        self.assertEqual(before[0]['fields']['unit[/root/b].flags.dnp'], 'no')
        self.assertNotIn('unit[/root/b].flags.dnp', after[0]['fields'])
        self.assertEqual(compare_components(before, after)[0]['status'], 'changed')

    def test_missing_unit_property_is_distinct_from_empty(self):
        self.sch(self.symbol('U1', 'a', '(property "Custom" "")') + self.symbol('U1', 'b', unit=2))
        before = self.extract()
        self.sch(self.symbol('U1', 'a', '(property "Custom" "")') + self.symbol('U1', 'b', '(property "Custom" "")', unit=2))
        after = self.extract()
        self.assertEqual(before[0]['fields']['unit[/root/a].fields.Custom'], '')
        self.assertNotIn('unit[/root/b].fields.Custom', before[0]['fields'])
        self.assertEqual(compare_components(before, after)[0]['status'], 'changed')

    def test_same_reference_same_unit_on_distinct_sheets_stays_separate(self):
        self.sch(self.symbol('U1', 'root-unit') + '(sheet (uuid "child") (property "Sheetname" "Child") (property "Sheetfile" "child.kicad_sch"))')
        self.sch(self.symbol('U1', 'child-unit'), 'child.kicad_sch', 'child-root')
        records = self.extract()
        self.assertEqual(len(records), 2)
        self.assertEqual({r['sheet'] for r in records}, {'/', '/Child'})

    def test_repeated_sheet_same_reference_keeps_multiunit_instances_separate(self):
        self.sch(''.join(f'(sheet (uuid "{uid}") (property "Sheetname" "{name}") (property "Sheetfile" "child.kicad_sch"))' for uid, name in [('left', 'Left'), ('right', 'Right')]))
        self.sch(self.symbol('U1', 'unit-a') + self.symbol('U1', 'unit-b', unit=2), 'child.kicad_sch', 'child-root')
        records = self.extract()
        self.assertEqual(len(records), 2)
        self.assertEqual({r['sheet'] for r in records}, {'/Left', '/Right'})
        self.assertEqual(len({r['id'] for r in records}), 2)

    def test_legacy_global_symbol_instances_override_reference(self):
        self.sch(self.symbol('R?', 'r1') + '(symbol_instances (path "/root/r1" (reference "R7") (unit 1) (value "old")))')
        self.assertEqual(self.extract()[0]['reference'], 'R7')

    def test_missing_and_cyclic_sheets_raise_useful_errors(self):
        self.sch('(sheet (uuid "a") (property "Sheetfile" "missing.kicad_sch"))')
        with self.assertRaisesRegex(ValueError, 'missing.kicad_sch'):
            self.extract()
        self.sch('(sheet (uuid "a") (property "Sheetfile" "demo.kicad_sch"))')
        with self.assertRaisesRegex(ValueError, '[Cc]ycl'):
            self.extract()

    def test_snapshot_paths_cannot_escape(self):
        with self.assertRaises(ValueError):
            extract_components(self.root, '../outside.kicad_pro', 'sch')
        self.sch('(sheet (uuid "a") (property "Sheetfile" "../outside.kicad_sch"))')
        with self.assertRaises(ValueError):
            self.extract()
        self.sch('(sheet (uuid "a") (property "Sheetfile" "escape/outside.kicad_sch"))')
        (self.root / 'escape').symlink_to(self.root.parent, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.extract()

    def test_pcb_placement_fields_flags_and_legacy_identity(self):
        self.write('demo.kicad_pcb', '''(kicad_pcb
          (footprint "R:0603" (uuid "stable") (layer "B.Cu") (at 1.20 2)
            (property "Reference" "R2") (property "Value" "") (property "Custom" "ő")
            (attr smd exclude_from_bom dnp))
          (module "Legacy:Part" (tstamp abc) (layer F.Cu) (at -1 3 0)
            (fp_text reference R10) (fp_text value old)))''')
        records = self.extract('pcb')
        self.assertEqual([r['reference'] for r in records], ['R2', 'R10'])
        self.assertEqual(records[0]['placement'], {'x': 1.2, 'y': 2, 'rotation': 0, 'side': 'B'})
        self.assertEqual(records[0]['fields']['Footprint'], 'R:0603')
        self.assertEqual(records[0]['fields']['Custom'], 'ő')
        self.assertEqual(records[0]['flags']['dnp'], True)
        self.assertEqual(records[0]['flags']['bom_excluded'], True)
        self.assertIn('abc', records[1]['id'])
        self.assertEqual(records[1]['fields']['Value'], 'old')


    def test_board_only_footprint_remains_included_on_board(self):
        self.write('demo.kicad_pcb', '(kicad_pcb (footprint "Fiducial" (uuid "f") (property "Reference" "FID1") (attr board_only exclude_from_pos_files)))')
        self.assertFalse(self.extract('pcb')[0]['flags']['board_excluded'])

    def test_missing_and_explicit_zero_pcb_rotation_compare_equally(self):
        template = '(kicad_pcb (footprint "R" (uuid "r") (layer "F.Cu") (property "Reference" "R1") (at 1 2%s)))'
        self.write('demo.kicad_pcb', template % '')
        before = self.extract('pcb')
        self.write('demo.kicad_pcb', template % ' 0.000')
        self.assertEqual(compare_components(before, self.extract('pcb'))[0]['status'], 'unchanged')

    def test_missing_symbol_uuid_falls_back_to_reference_and_sheet(self):
        self.sch('(symbol (lib_id "Device:R") (property "Reference" "R1") (property "Value" "10k"))')
        record = self.extract()[0]
        self.assertIn('R1', record['id'])
        self.assertEqual(record['reference'], 'R1')

    def test_root_legacy_instances_include_descendant_references(self):
        self.sch('(sheet (uuid "child") (property "Sheetname" "Child") (property "Sheetfile" "child.kicad_sch")) (symbol_instances (path "/root/child/r1" (reference "R9")))')
        self.sch(self.symbol('R?', 'r1'), 'child.kicad_sch', 'child-root')
        self.assertEqual(self.extract()[0]['reference'], 'R9')


class CompareTests(unittest.TestCase):
    def component(self, identity='a', ref='R1', sheet='/', **kwargs):
        return dict(id=identity, reference=ref, sheet=sheet, fields=kwargs.get('fields', {'Value': '10k'}), flags=kwargs.get('flags', {'dnp': False}), placement=kwargs.get('placement', {}))

    def test_all_statuses_and_natural_sort(self):
        before = [self.component('a', 'R10'), self.component('b', 'R2'), self.component('c', 'C1')]
        after = [self.component('b', 'R2'), self.component('d', 'R3'), self.component('a', 'R10', fields={'Value': '22k'})]
        changes = compare_components(before, after)
        self.assertEqual([(r['reference'], r['status']) for r in changes], [('C1', 'removed'), ('R2', 'unchanged'), ('R3', 'added'), ('R10', 'changed')])
        self.assertIsNone(changes[0]['after'])
        self.assertIsNone(changes[2]['before'])
        self.assertEqual(set(changes[0]), {'id', 'reference', 'status', 'before', 'after', 'changes'})

    def test_field_add_delete_empty_flags_rename_and_placement(self):
        before = self.component(fields={'Value': '10k', 'Deleted': '', 'Empty': 'yes'}, placement={'x': 1, 'rotation': 0})
        after = self.component(ref='R8', fields={'Value': '22k', 'Added': '', 'Empty': ''}, flags={'dnp': True}, placement={'x': 2, 'rotation': 0})
        original = copy.deepcopy([before, after])
        result = compare_components([before], [after])[0]
        changes = {c['field']: c for c in result['changes']}
        self.assertEqual(changes['fields.Added']['before'], None)
        self.assertEqual(changes['fields.Added']['after'], '')
        self.assertEqual(changes['fields.Deleted']['before'], '')
        self.assertEqual(changes['fields.Deleted']['after'], None)
        self.assertEqual(changes['flags.dnp']['category'], 'field')
        self.assertEqual(changes['placement.x']['category'], 'placement')
        self.assertIn('reference', changes)
        self.assertNotIn('placement.rotation', changes)
        self.assertEqual([before, after], original)

    def test_unique_reference_sheet_fallback_does_not_report_id_change(self):
        result = compare_components([self.component('old')], [self.component('new')])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['status'], 'unchanged')
        self.assertEqual(result[0]['changes'], [])

    def test_reference_fallback_does_not_cross_sheets_or_ambiguous_duplicates(self):
        result = compare_components([self.component('old', sheet='/A')], [self.component('new', sheet='/B')])
        self.assertEqual(sorted(r['status'] for r in result), ['added', 'removed'])
        result = compare_components([self.component('a'), self.component('b')], [self.component('c')])
        self.assertEqual(len(result), 3)


if __name__ == '__main__':
    unittest.main()

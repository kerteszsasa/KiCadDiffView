"""KiCad SVG export with a shared physical viewport and vector color masks."""
import hashlib
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

from .sexpr import loads, children

NS = 'http://www.w3.org/2000/svg'
ET.register_namespace('', NS)
ET.register_namespace('xlink', 'http://www.w3.org/1999/xlink')


def union_canvas(boxes):
    if not boxes:
        return [0, 0, 297, 210]
    x = min(b[0] for b in boxes)
    y = min(b[1] for b in boxes)
    return [x, y, max(b[0]+b[2] for b in boxes)-x, max(b[1]+b[3] for b in boxes)-y]


def svg_box(path):
    values = [float(x) for x in ET.parse(path).getroot().attrib['viewBox'].split()]
    if len(values) != 4 or min(values[2:]) <= 0:
        raise ValueError(f'Invalid SVG canvas: {path.name}')
    return values


def normalize_svg(path, box):
    tree = ET.parse(path)
    root = tree.getroot()
    root.set('viewBox', ' '.join(format(x, '.12g') for x in box))
    root.set('width', format(box[2], '.12g')+'mm')
    root.set('height', format(box[3], '.12g')+'mm')
    tree.write(path, encoding='utf-8', xml_declaration=True)


def colored_svg(before, after, destination, box):
    x, y, width, height = (format(v, '.12g') for v in box)
    bounds = f'x="{x}" y="{y}" width="{width}" height="{height}"'
    viewport = ' '.join(format(v, '.12g') for v in box)

    def embedded(path, identifier):
        if path is None:
            source = ET.Element(f'{{{NS}}}svg')
        else:
            source = ET.parse(path).getroot()
        # Keep source geometry inline: SVG images cannot reliably fetch nested
        # image resources, even when those resources are data-URI SVGs.
        identifiers = {node.get('id'): identifier+'-'+node.get('id')
                       for node in source.iter() if node.get('id')}
        for node in source.iter():
            for key, value in list(node.attrib.items()):
                if key == 'id':
                    node.set(key, identifiers[value])
                else:
                    for old, new in identifiers.items():
                        value = value.replace('url(#'+old+')', 'url(#'+new+')')
                        if value == '#'+old:
                            value = '#'+new
                    node.set(key, value)
        source.set('id', identifier)
        source.set('x', x); source.set('y', y)
        source.set('width', width); source.set('height', height)
        source.set('viewBox', viewport)
        return ET.tostring(source, encoding='unicode')

    mask_attributes = bounds+' maskUnits="userSpaceOnUse" maskContentUnits="userSpaceOnUse"'
    white = '0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 1 0'
    black = '0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 1 0'
    svg = f'''<svg xmlns="{NS}" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="{viewport}" width="{width}mm" height="{height}mm">
<defs>{embedded(before, 'source-before')}{embedded(after, 'source-after')}
<filter id="white" {bounds} filterUnits="userSpaceOnUse" color-interpolation-filters="sRGB"><feColorMatrix type="matrix" values="{white}"/></filter>
<filter id="black" {bounds} filterUnits="userSpaceOnUse" color-interpolation-filters="sRGB"><feColorMatrix type="matrix" values="{black}"/></filter>
<mask id="before" {mask_attributes}><use xlink:href="#source-before" filter="url(#white)"/></mask>
<mask id="after" {mask_attributes}><use xlink:href="#source-after" filter="url(#white)"/></mask>
<mask id="not-before" {mask_attributes}><rect {bounds} fill="white"/><use xlink:href="#source-before" filter="url(#black)"/></mask>
<mask id="not-after" {mask_attributes}><rect {bounds} fill="white"/><use xlink:href="#source-after" filter="url(#black)"/></mask>
</defs>
<g mask="url(#before)"><rect {bounds} fill="#807F7F" mask="url(#after)"/></g>
<g mask="url(#before)"><rect {bounds} fill="#880808" mask="url(#not-after)"/></g>
<g mask="url(#after)"><rect {bounds} fill="#40FF40" mask="url(#not-before)"/></g>
</svg>'''
    Path(destination).parent.mkdir(parents=True, exist_ok=True)
    Path(destination).write_text(svg)


def board_layers(path):
    text = Path(path).read_text()
    start = text.find('(layers')
    if start < 0:
        return []
    depth, quoted, escaped = 0, False, False
    end = start
    for end in range(start, len(text)):
        char = text[end]
        if quoted:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char == '(':
            depth += 1
        elif char == ')':
            depth -= 1
            if depth == 0:
                break
    node = loads(text[start:end+1])
    return [{'id': str(row[1]), 'name': str(row[3] if len(row) > 3 else row[1])}
            for row in node[1:] if isinstance(row, list) and len(row) >= 3]


def fingerprint(path):
    if path is None:
        return None
    root = ET.parse(path).getroot()
    for element in list(root):
        if element.tag.rsplit('}', 1)[-1] in ('title', 'desc'):
            root.remove(element)
    return hashlib.sha256(ET.tostring(root)).hexdigest()


class Exporter:
    def __init__(self, env, progress, cli='kicad-cli'):
        self.env, self.progress, self.cli = env, progress, cli

    def run(self, args):
        result = subprocess.run([self.cli, *args], env=self.env, capture_output=True, text=True)
        if result.returncode:
            raise ValueError((result.stderr+result.stdout)[-5000:] or 'KiCad export failed.')

    @staticmethod
    def safe(snapshot, relative):
        root = Path(snapshot).resolve()
        path = (root/relative).resolve()
        if not path.is_relative_to(root):
            raise ValueError('The project file points outside the revision snapshot.')
        return path

    def schematic(self, snapshots, project, output):
        relative = str(Path(project).with_suffix('.kicad_sch'))
        side_pages = {}
        for side, snapshot in snapshots.items():
            source = self.safe(snapshot, relative)
            if not source.is_file():
                side_pages[side] = {}
                continue
            self.progress(f'Schematic export: {side}')
            folder = output/side/'schematics'
            folder.mkdir(parents=True)
            self.run(['sch', 'export', 'svg', '--no-background-color', '--exclude-drawing-sheet',
                      '-o', str(folder)+'/', str(source)])
            side_pages[side] = {p.stem: p for p in sorted(folder.glob('*.svg'))}
            if not side_pages[side]:
                raise ValueError(f'No schematic SVG was generated: {side}')
        names = sorted(set().union(*(pages.keys() for pages in side_pages.values())))
        if not names:
            return None
        stem = Path(project).stem
        names.sort(key=lambda name: (name != stem, name.casefold()))
        box = union_canvas([svg_box(p) for pages in side_pages.values() for p in pages.values()])
        pages = []
        for index, name in enumerate(names):
            before, after = (side_pages[side].get(name) for side in ('before','after'))
            pages.append(self.item(name, name, before, after, output/'colored'/f'sheet-{index}.svg', box, output))
        return {'id': 'schematic', 'type': 'sch', 'name': Path(relative).name,
                'path': relative, 'pages': pages, 'canvas': box}

    def pcb(self, snapshots, relative, output, number):
        side_layers, paths = {}, {}
        for side, snapshot in snapshots.items():
            source = self.safe(snapshot, relative)
            if not source.is_file():
                side_layers[side] = []
                continue
            layers = board_layers(source)
            side_layers[side] = layers
            if not layers:
                raise ValueError(f'No PCB layers found: {relative}')
            self.progress(f'PCB export ({len(layers)} layers): {side} / {Path(relative).name}')
            raw = output/side/f'pcb-{number}'
            raw.mkdir(parents=True)
            self.run(['pcb','export','svg','--mode-multi','--page-size-mode','1',
                      '--exclude-drawing-sheet','--layers',','.join(l['id'] for l in layers),
                      '-o',str(raw)+'/',str(source)])
            for layer in layers:
                candidates = [raw/f'{source.stem}-{name.replace(".", "_")}.svg'
                              for name in (layer['name'],layer['id'])]
                exported = next((p for p in candidates if p.is_file()), None)
                if exported is None:
                    # Explicit filenames avoid relying on KiCad's sanitization of
                    # custom layer names or its version-specific filename aliases.
                    exported = raw/('layer-'+hashlib.sha256(layer['id'].encode()).hexdigest()[:12]+'.svg')
                    self.run(['pcb','export','svg','--mode-single','--page-size-mode','1',
                              '--exclude-drawing-sheet','--layers',layer['id'],'-o',str(exported),str(source)])
                paths[(side,layer['id'])] = exported
        if not paths:
            return None
        box = union_canvas([svg_box(p) for p in paths.values()])
        names = {l['id']: l['name'] for side in ('before','after') for l in side_layers[side]}
        layers = []
        for index, (identifier, name) in enumerate(names.items()):
            layers.append(self.item(identifier, name, paths.get(('before',identifier)),
                                    paths.get(('after',identifier)), output/'colored'/f'pcb-{number}-layer-{index}.svg', box, output))
        return {'id': f'pcb-{number}', 'type': 'pcb', 'name': Path(relative).name,
                'path': relative, 'layers': layers, 'canvas': box}

    @staticmethod
    def item(identifier, name, before, after, colored, box, output):
        for path in (before, after):
            if path:
                normalize_svg(path, box)
        colored_svg(before, after, colored, box)
        return {'id': identifier, 'name': name,
                'before': before.relative_to(output).as_posix() if before else None,
                'after': after.relative_to(output).as_posix() if after else None,
                'colored': colored.relative_to(output).as_posix(),
                'changed': fingerprint(before) != fingerprint(after)}

    def export(self, snapshots, project, output):
        output = Path(output)
        output.mkdir(parents=True, exist_ok=True)
        files = []
        schematic = self.schematic(snapshots, project, output)
        if schematic:
            files.append(schematic)
        directory = Path(project).parent
        pcbs = set()
        for snapshot in snapshots.values():
            folder = self.safe(snapshot, str(directory))
            if folder.is_dir():
                pcbs.update((directory/p.name).as_posix() for p in folder.glob('*.kicad_pcb'))
        for index, relative in enumerate(sorted(pcbs)):
            pcb = self.pcb(snapshots, relative, output, index)
            if pcb:
                files.append(pcb)
        if not files:
            raise ValueError('Neither revision contains exportable design files for this project.')
        return files

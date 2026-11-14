#!/usr/bin/env python3
"""Turn a git repository's history into a 3D city. See README.md."""
import argparse
import collections
import json
import math
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))

DEFAULT_CONFIG = {
    'name': None,
    'package_roots': ['packages', 'apps', 'libs', 'services', 'modules', 'crates', 'frontend/packages', 'backend/packages'],
    'exclude': [r'(^|/)node_modules/', r'(^|/)vendor/', r'\.lock$', r'lock\.json$', r'\.snap$', r'(^|/)dist/', r'\.min\.(js|css)$'],
    'fix_pattern': r'\b(fix|fixes|fixed|bug|hotfix|broken|crash)',
    'hotfix_pattern': r'\bhotfix',
    'releases': {'tags': True, 'merge_pattern': None},
    'districts': {},
    'rows': {},
    'zones': [],
    'rails': None,
}

ZONES = ['residential', 'shop', 'office', 'civic', 'factory', 'warehouse', 'waterworks', 'infra', 'park', 'campus', 'monument']

DEFAULT_ZONE_RULES = [
    (r'(^|/)(cypress|__tests__|tests?|spec|e2e|playground|fixtures|__mocks__)/|\.(test|spec)\.[a-z]+$|(^|/)test_[^/]+\.py$|_test\.(go|py|rb)$', 'factory'),
    (r'^\.(claude|cursor|ai)/|(^|/)(prompts|skills)/', 'campus'),
    (r'\.(md|mdx|rst|adoc)$|^docs?/|(^|/)docs?/', 'park'),
    (r'\.sql$|(^|/)migrations?/', 'waterworks'),
    (r'\.(tf|tfvars|ya?ml|sh|toml|ini|cfg)$|(^|/)\.github/|dockerfile|docker-compose|(^|/)\.circleci/|(^|/)terraform/|(^|/)helm/|(^|/)k8s/', 'infra'),
    (r'\.(svg|png|jpe?g|gif|ico|webp|avif|woff2?|ttf|otf|mp4|mp3|wav)$|(^|/)(public|static|assets)/', 'monument'),
    (r'\.(json|csv|html?|txt|xml|tsv)$', 'warehouse'),
    (r'(^|/)(api|server|services?|jobs|workers?|controllers?|handlers?|routes?|resolvers?|graphql)/|\.graphql$|(^|/)(backend|server|client)\.[a-z]+$', 'office'),
    (r'(^|/)(pages|app|views|screens)/', 'shop'),
    (r'\.(tsx|jsx|vue|svelte|astro)$|(^|/)components?/', 'residential'),
]

DOMINANT_SUFFIX = {
    'office': 'Business District', 'residential': 'Heights', 'shop': 'High Street', 'civic': 'Town',
    'factory': 'Industrial Estate', 'warehouse': 'Docks', 'waterworks': 'Waterworks', 'infra': 'Depot',
    'park': 'Gardens', 'campus': 'Campus', 'monument': 'Square',
}
SOUTH_ZONES = {'waterworks', 'infra', 'warehouse'}
GAPS = [9.0, 3.0, 1.6, 0.9, 0.6]
LOT_SIDE = 3.4


def git(repo, *args):
    return subprocess.run(['git', '-c', 'core.quotePath=false', '-C', repo, *args], capture_output=True, text=True, check=True).stdout


def load_config(path):
    config = json.loads(json.dumps(DEFAULT_CONFIG))
    if path:
        user = json.load(open(path))
        for key, value in user.items():
            if isinstance(value, dict) and isinstance(config.get(key), dict):
                config[key].update(value)
            else:
                config[key] = value
    return config


class Zoner:
    def __init__(self, extra_rules):
        self.rules = [(re.compile(r['pattern'], re.I), r['zone']) for r in extra_rules] + [(re.compile(p, re.I), z) for p, z in DEFAULT_ZONE_RULES]

    def __call__(self, path):
        for pattern, zone in self.rules:
            if pattern.search(path):
                return zone
        return 'civic'


class Districter:
    def __init__(self, roots):
        self.roots = sorted(roots, key=len, reverse=True)

    def __call__(self, path):
        for root in self.roots:
            prefix = root.rstrip('/') + '/'
            if path.startswith(prefix):
                rest = path[len(prefix):]
                if '/' in rest:
                    name, rel = rest.split('/', 1)
                    return name, rel
        if '/' not in path:
            return 'root', path
        top, rel = path.split('/', 1)
        return top, rel


def unquote(path):
    if len(path) >= 2 and path[0] == '"' and path[-1] == '"':
        return path[1:-1].encode('latin-1', 'backslashreplace').decode('unicode_escape').encode('latin-1').decode('utf-8', 'replace')
    return path


def expand_rename(path):
    m = re.match(r'(.*)\{(.*) => (.*)\}(.*)', path)
    if m:
        pre, old, new, post = m.groups()
        clean = lambda s: re.sub(r'/+', '/', s).strip('/')
        return clean(pre + old + post), clean(pre + new + post)
    if ' => ' in path:
        old, new = path.split(' => ', 1)
        return old, new
    return None, path


def month_range(first, last):
    y, m = map(int, first.split('-'))
    out = []
    while f'{y}-{m:02d}' <= last:
        out.append(f'{y}-{m:02d}')
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def walk_history(repo, config, zoner, districter):
    exclude = [re.compile(p, re.I) for p in config['exclude']]
    fix_re = re.compile(config['fix_pattern'], re.I)
    log = git(repo, 'log', '--reverse', '--no-merges', '-M', '--format=@%ad|%s', '--date=format:%Y-%m', '--numstat', '--summary')
    files, by_path, commits = {}, {}, []
    state = {'month': None, 'subject': '', 'touch': collections.Counter(), 'lines': [0, 0]}

    def close():
        if state['month'] is not None:
            commits.append((state['month'], state['subject'], dict(state['touch']), state['lines'][:]))

    for line in log.splitlines():
        if line.startswith('@'):
            close()
            state['month'], state['subject'] = line[1:].split('|', 1)
            state['touch'], state['lines'] = collections.Counter(), [0, 0]
            continue
        if not line.strip():
            continue
        if line.startswith(' delete mode'):
            path = unquote(line.split(' ', 4)[-1])
            f = by_path.pop(path, None)
            if f:
                f['died'] = state['month']
            continue
        if line.startswith(' '):
            continue
        parts = line.split('\t')
        if len(parts) != 3 or parts[0] == '-':
            continue
        old, path = expand_rename(unquote(parts[2]))
        if any(p.search(path) for p in exclude):
            continue
        add, rem = int(parts[0]), int(parts[1])
        f = None
        if old and old in by_path:
            f = by_path.pop(old)
            f['path'] = path
            by_path[path] = f
        f = f or by_path.get(path)
        if f is None:
            f = {'id': len(files), 'path': path, 'loc': 0, 'peak': 0, 'series': {}, 'touches': set(), 'fixes': set(), 'died': None}
            files[f['id']] = f
            by_path[path] = f
        f['loc'] = max(0, f['loc'] + add - rem)
        f['peak'] = max(f['peak'], f['loc'])
        f['series'][state['month']] = f['loc']
        f['touches'].add(state['month'])
        if fix_re.search(state['subject']):
            f['fixes'].add(state['month'])
        district, _ = districter(path)
        state['touch'][district] += add + rem
        state['lines'][0] += add
        state['lines'][1] += rem
    close()
    for f in files.values():
        if f['died']:
            f['series'][f['died']] = 0
    return [f for f in files.values() if f['peak'] > 0], commits


def monthly_series(repo, config, months):
    fix_re = re.compile(config['fix_pattern'], re.I)
    hot_re = re.compile(config['hotfix_pattern'], re.I)
    merge_re = re.compile(config['releases']['merge_pattern'], re.I) if config['releases'].get('merge_pattern') else None
    idx = {m: i for i, m in enumerate(months)}
    series = {k: [0] * len(months) for k in ('commits', 'fixes', 'releases', 'hotfixes')}
    for line in git(repo, 'log', '--format=%ad|%s', '--date=format:%Y-%m').splitlines():
        month, subject = line.split('|', 1)
        i = idx.get(month)
        if i is None:
            continue
        series['commits'][i] += 1
        if fix_re.search(subject):
            series['fixes'][i] += 1
        if hot_re.search(subject):
            series['hotfixes'][i] += 1
        if merge_re and merge_re.search(subject):
            series['releases'][i] += 1
    if config['releases'].get('tags', True):
        for month in git(repo, 'for-each-ref', 'refs/tags', '--format=%(creatordate:format:%Y-%m)').split():
            if month in idx:
                series['releases'][idx[month]] += 1
    return series


def squarify(items, x, y, w, h):
    items = sorted(items, key=lambda it: -it[1])
    total = sum(it[1] for it in items) or 1
    rest = [(key, weight * (w * h) / total) for key, weight in items]
    out = []
    while rest:
        short = min(w, h) or 1e-6
        row, i = [rest[0]], 1

        def worst(r):
            s = sum(a for _, a in r)
            return max(max(s * s / (short * short * a), short * short * a / (s * s)) for _, a in r)
        while i < len(rest) and worst(row + [rest[i]]) <= worst(row):
            row.append(rest[i])
            i += 1
        s = sum(a for _, a in row)
        if w >= h:
            cw = s / h if h else 0
            cy = y
            for key, a in row:
                ch = a / cw if cw else 0
                out.append((key, x, cy, cw, ch))
                cy += ch
            x, w = x + cw, w - cw
        else:
            ch = s / w if w else 0
            cx = x
            for key, a in row:
                cw = a / ch if ch else 0
                out.append((key, cx, y, cw, ch))
                cx += cw
            y, h = y + ch, h - ch
        rest = rest[i:]
    return out


def lot_weight(f):
    base = max(6, min(f['peak'], 3500)) ** 0.6 + 3
    wide = 1.6 if f['zone'] in ('warehouse', 'factory') else 1.0
    return base * wide * (1.4 if f['zone'] == 'park' else 1.0)


def build_tree(files, districter):
    tree = {}
    for f in files:
        district, rel = districter(f['path'])
        parts = [p for p in rel.split('/') if p != 'src']
        node = tree.setdefault(district, {'children': {}, 'files': []})
        for part in parts[:-1]:
            node = node['children'].setdefault(part, {'children': {}, 'files': []})
        node['files'].append(f)

    def collapse(node):
        for key, child in list(node['children'].items()):
            collapse(child)
            if not child['files'] and len(child['children']) == 1:
                (ck, cc), = child['children'].items()
                node['children'][f'{key}/{ck}'] = cc
                del node['children'][key]

    def weigh(node):
        node['w'] = sum(lot_weight(f) for f in node['files']) + sum(weigh(c) for c in node['children'].values())
        return node['w']
    for node in tree.values():
        collapse(node)
        weigh(node)
    return tree


def layout_city(tree, files, config, shared):
    lots, blocks = {}, []

    def layout(node, x, y, w, h, depth):
        items = [(('d', k), c['w']) for k, c in node['children'].items()] + [(('f', f['id']), lot_weight(f)) for f in node['files']]
        has_dirs = bool(node['children'])
        for (kind, key), cx, cy, cw, ch in squarify(items, x, y, w, h):
            if kind == 'f':
                pad = 0.3 if has_dirs else 0.14
                lots[key] = [cx + pad, cy + pad, max(0.2, cw - 2 * pad), max(0.2, ch - 2 * pad)]
                continue
            g = GAPS[min(depth, len(GAPS) - 1)] / 2
            bx, by, bw, bh = cx + g, cy + g, max(0.3, cw - 2 * g), max(0.3, ch - 2 * g)
            blocks.append([bx, by, bw, bh, depth])
            layout(node['children'][key], bx, by, bw, bh, depth + 1)

    weights = {d: n['w'] for d, n in tree.items()}
    total = sum(weights.values())
    mean_lot = sum(lot_weight(f) for f in files) / len(files)
    area = total * LOT_SIDE ** 2 / mean_lot * 1.9
    width = math.sqrt(area * 1.45)
    height = area / width
    dominant = {}
    for f in files:
        d = f['district']
        dominant.setdefault(d, collections.Counter())[f['zone']] += 0.4 if f['zone'] == 'factory' else 1
    rows = {'north': [], 'centre': [], 'south': []}
    ranked = sorted(weights, key=lambda d: -weights[d])
    for rank, d in enumerate(ranked):
        if d in config['rows']:
            rows[config['rows'][d]].append(d)
        elif d in shared or rank < 3:
            rows['centre'].append(d)
        elif dominant[d].most_common(1)[0][0] in SOUTH_ZONES:
            rows['south'].append(d)
        else:
            rows['north' if sum(weights[x] for x in rows['north']) <= sum(weights[x] for x in rows['south']) else 'south'].append(d)
    rects, y = {}, 0
    for row in ('north', 'centre', 'south'):
        names = sorted(rows[row], key=lambda d: -weights[d])
        if row == 'centre' and shared:
            hubs = [n for n in names if n in shared]
            others = [n for n in names if n not in shared]
            names = others[:2] + hubs + others[2:]
        row_weight = sum(weights[d] for d in names)
        if not row_weight:
            continue
        row_height = height * row_weight / total
        x = 0
        for d in names:
            dw = width * weights[d] / row_weight
            g = GAPS[0] / 2
            rects[d] = [x + g, y + g, dw - 2 * g, row_height - 2 * g]
            x += dw
        y += row_height
    for d, (x, y0, w, h) in rects.items():
        blocks.append([x, y0, w, h, 0])
        layout(tree[d], x, y0, w, h, 1)
    names = {d: config['districts'].get(d) or f"{d.strip('.').replace('-', ' ').replace('_', ' ').title()} {DOMINANT_SUFFIX[dominant[d].most_common(1)[0][0]]}" for d in rects}
    if 'root' in rects and 'root' not in config['districts']:
        names['root'] = 'Town Hall'
    return lots, blocks, rects, names, (width, height)


def find_rails(repo, files, districter, config):
    if config['rails'] is not None:
        return [tuple(r) for r in config['rails']]
    package_names = {}
    head_files = set(git(repo, 'ls-files').splitlines())
    for path in head_files:
        if path.endswith('package.json') and 'node_modules' not in path:
            district, rel = districter(path)
            if rel == 'package.json':
                try:
                    name = json.load(open(os.path.join(repo, path))).get('name')
                except (OSError, ValueError) as err:
                    print(f'skipping {path}: {err}', file=sys.stderr)
                    continue
                if name:
                    package_names[name] = district
    if not package_names:
        return []
    pattern = re.compile(r'''(?:from\s+|require\(\s*|import\(\s*|import\s+)['"](''' + '|'.join(re.escape(n) for n in sorted(package_names, key=len, reverse=True)) + r''')(?:/[^'"]*)?['"]''')
    counts = collections.Counter()
    for path in head_files:
        if not re.search(r'\.(m?[jt]sx?|vue|svelte|astro)$', path):
            continue
        consumer, _ = districter(path)
        try:
            text = open(os.path.join(repo, path), encoding='utf-8', errors='ignore').read()
        except OSError:
            continue
        for match in pattern.finditer(text):
            target = package_names[match.group(1)]
            if target != consumer:
                counts[(target, consumer)] += 1
    return [(t, c, n) for (t, c), n in counts.most_common()]


def load_metrics(path, months):
    if not path:
        return None
    raw = json.load(open(path))
    labels = {'ships': 'Ships', 'containers': 'Containers', 'visitors': 'Visitors', **raw.get('labels', {})}
    series = {k: [int(raw.get('months', {}).get(m, {}).get(k, 0)) for m in months] for k in ('ships', 'containers', 'visitors')}
    return {'labels': labels, 'per_container': raw.get('per_container', 250), **series}


def collect(repo, config):
    zoner = Zoner(config['zones'])
    districter = Districter(config['package_roots'])
    files, commits = walk_history(repo, config, zoner, districter)
    if not files:
        sys.exit('No files with history found.')
    months = month_range(min(c[0] for c in commits), max(c[0] for c in commits))
    midx = {m: i for i, m in enumerate(months)}
    for f in files:
        f['zone'] = zoner(f['path'])
        f['district'] = districter(f['path'])[0]
    tree = build_tree(files, districter)
    rails = find_rails(repo, files, districter, config)
    shared = {t for t, _, _ in rails if t in tree}
    lots, blocks, rects, names, (width, height) = layout_city(tree, files, config, shared)
    district_list = sorted(rects)
    didx = {d: i for i, d in enumerate(district_list)}
    cx, cy = width / 2, height / 2
    fix_re = re.compile(config['fix_pattern'], re.I)
    per_district = {k: [[0] * len(months) for _ in district_list] for k in ('commits', 'fixes')}
    big = []
    for month, subject, touch, (added, removed) in commits:
        for d in touch:
            if d in didx:
                per_district['commits'][didx[d]][midx[month]] += 1
                if fix_re.search(subject):
                    per_district['fixes'][didx[d]][midx[month]] += 1
        if added + removed >= 5000 and touch:
            top = max(touch, key=touch.get)
            big.append([month, added, removed, subject[:100], didx.get(top, -1)])
    r2 = lambda v: round(v, 2)
    return {
        'name': config['name'] or os.path.basename(os.path.abspath(repo)),
        'generated': datetime.now(timezone.utc).strftime('%d %b %Y'),
        'head': git(repo, 'rev-parse', '--short', 'HEAD').strip(),
        'months': months,
        'zones': ZONES,
        'districts': [[d, names[d], [r2(rects[d][0] - cx), r2(rects[d][1] - cy), r2(rects[d][2]), r2(rects[d][3])]] for d in district_list],
        'blocks': [[r2(b[0] - cx), r2(b[1] - cy), r2(b[2]), r2(b[3]), b[4]] for b in blocks],
        'files': [[f['path'], didx[f['district']], ZONES.index(f['zone']),
                   [r2(lots[f['id']][0] - cx), r2(lots[f['id']][1] - cy), r2(lots[f['id']][2]), r2(lots[f['id']][3])],
                   sorted([midx[m], v] for m, v in f['series'].items()),
                   sorted(midx[m] for m in f['touches']), sorted(midx[m] for m in f['fixes'])]
                  for f in sorted(files, key=lambda f: f['id']) if f['id'] in lots],
        'rails': [[didx[t], didx[c], n] for t, c, n in rails if t in didx and c in didx],
        'district_commits': per_district['commits'],
        'district_fixes': per_district['fixes'],
        'monthly': monthly_series(repo, config, months),
        'big': sorted(big, key=lambda b: -(b[1] + b[2]))[:40],
        'size': [round(width, 1), round(height, 1)],
    }


def main():
    parser = argparse.ArgumentParser(description='Turn a git repository into a 3D city.')
    parser.add_argument('repo', help='path to a local git repository')
    parser.add_argument('-o', '--out', default='city.html', help='output HTML file (default: city.html)')
    parser.add_argument('-c', '--config', help='optional JSON config, see README.md')
    parser.add_argument('-m', '--metrics', help='optional JSON of monthly metrics for the port, see README.md')
    parser.add_argument('--json', help='also write the collected data to this path')
    args = parser.parse_args()
    config = load_config(args.config)
    data = collect(args.repo, config)
    data['metrics'] = load_metrics(args.metrics, data['months'])
    payload = json.dumps(data, separators=(',', ':')).replace('</', '<\\/')
    template = open(os.path.join(HERE, 'city.template.html'), encoding='utf-8').read()
    open(args.out, 'w', encoding='utf-8').write(template.replace('__CITY__', payload))
    if args.json:
        json.dump(data, open(args.json, 'w'), separators=(',', ':'))
    print(f"{data['name']}: {len(data['files'])} buildings, {len(data['districts'])} districts, {len(data['months'])} months -> {args.out}")


if __name__ == '__main__':
    main()

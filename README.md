# git-city

Turn any git repository's history into a living 3D city. Every file is a building and every package is a district.
The city grows and shrinks month by month as the code does, from the first commit to today.

One Python script reads `git log` and writes a single self-contained HTML page. It needs no dependencies, makes no
network calls and uses no AI, so you can rebuild it on a schedule for free.

A demo built from [vite](https://github.com/vitejs/vite)'s history is in [`demo/index.html`](demo/index.html).
Download it and open it in a browser.

## Quick start

```sh
git clone https://github.com/jackherizsmith/git-city
python3 git-city/git_city.py /path/to/your/repo -o city.html
open city.html
```

You need Python 3.8+ and git. The page loads three.js (r128) from cdnjs and its fonts from Google Fonts. A repo with
about 10,000 commits takes a few seconds.

In the page, press Play to watch the city grow. Drag to orbit, shift-drag to pan and scroll to zoom. Hover a building
to see its file, line count, when it was built, when it was last worked on and how many fix commits touched it.
Click a headline in the chronicle to jump to that month.

## How code becomes a city

| Code | City |
| --- | --- |
| Lines of code | Population |
| File | Building. Height grows with the square root of its current line count |
| The most lines a file ever had | Plot size, so plots stay put while buildings rise and fall |
| Package in a workspace, or top-level folder | District |
| Folders | Blocks and streets, with wider roads between higher levels of the tree |
| Components (`.tsx`, `.vue`, `.svelte`, `components/`) | Housing |
| Pages and routes | High-street shops |
| API, server, services, jobs, handlers | Glass office towers |
| Other source files | Civic buildings |
| Tests, fixtures, playgrounds | Factories, with chimneys that smoke when tests change |
| JSON, HTML, CSV, text | Warehouses |
| SQL and migrations | Storage tanks |
| CI, Docker, Terraform, YAML | Utility depots |
| Docs and Markdown | Parks |
| Images, fonts, static assets | Monuments |
| `.claude`, `.cursor`, prompts | A university campus |
| Packages that others import | Metro interchanges, with a coloured line to every importer and more trains for more imports |
| Commits that month | Car traffic in the districts they touched |
| New files | Cranes |
| Deleted files | Rubble for two months |
| Fix commits | Rooftop fires on the buildings they touched |
| Recent work | Lit windows at night, fading over the following months |
| Untouched for two years | Derelict, greyed buildings with dark windows |
| A district emptied of files | Grass, with only its streets left |
| Releases (tags, or merges you choose) | Planes taking off from the airport |
| Hotfixes | Helicopters circling the district with the most fixes |
| Your own business metrics (optional) | Ships in port, containers on the quay, visitors in the HUD |

### City news

A small set of fixed rules writes the headlines:

- a district is founded or demolished
- the biggest single commits, named by their subject
- the population passes a 100k mark and stays above it for six months
- rush hours: a month with 150+ commits and 1.9 times the trailing year's pace
- fire storms: a new record for fix commits
- the airport's first flight and its busiest month
- metric records, when you pass a metrics file

## Configuration

Everything is optional. Pass a JSON file with `--config`; anything you leave out keeps its default.
See [`examples/config.example.json`](examples/config.example.json).

| Key | Default | What it does |
| --- | --- | --- |
| `name` | the repo folder's name | The city's name |
| `package_roots` | `packages`, `apps`, `libs`, `services`, `modules`, `crates`, … | Folders whose children are each a district. Everything else becomes a district per top-level folder |
| `exclude` | lock files, snapshots, `node_modules`, `vendor`, `dist`, minified files | Regexes for paths to leave out |
| `fix_pattern` | `\b(fix\|fixes\|fixed\|bug\|hotfix\|broken\|crash)` | Commit subjects that count as fixes |
| `hotfix_pattern` | `\bhotfix` | Commit subjects that send a helicopter |
| `releases.tags` | `true` | Count tags as releases, by the month they were created |
| `releases.merge_pattern` | none | Also count commits whose subject matches, such as `Merge pull request .* from .*/release/` |
| `districts` | generated | District display names, such as `{"api": "Financial District"}`. By default a district is named after its folder and its most common building, as in "Web Heights" or "Docs Gardens" |
| `rows` | automatic | Pin a district to the `north`, `centre` or `south` row. The south row is the waterfront |
| `zones` | none | Extra rules tried before the built-in ones: `[{"pattern": "regex", "zone": "office"}]` |
| `rails` | worked out from `package.json` names | Metro lines as `[["shared-district", "importing-district", weight]]` |

Zones are `residential`, `shop`, `office`, `civic`, `factory`, `warehouse`, `waterworks`, `infra`, `park`, `campus`
and `monument`.

### Metrics

Use `--metrics` to bring the port to life with numbers from outside git, such as sign-ups, orders or projects. The file
holds a value per month; months you leave out count as zero. See
[`examples/metrics.example.json`](examples/metrics.example.json).

```json
{
  "labels": { "ships": "Projects launched", "containers": "Sign-ups", "visitors": "Active users" },
  "per_container": 250,
  "months": {
    "2024-07": { "ships": 6, "containers": 5400, "visitors": 3900 }
  }
}
```

- `ships`: ships docked that month, up to 30
- `containers`: added up over time, with one container stacked for every `per_container`
- `visitors`: shown in the HUD, with a record headline

## How it works

`git_city.py` walks `git log --numstat --summary -M` once. It follows renames and deletions, so each file has a line
count for every month and a list of the months it was touched and fixed. Each path is zoned by the rules above. The
folder tree is laid out as a squarified treemap with a street gap at each level, and districts are arranged in three
rows. Packages built mostly from infrastructure, data or migrations go to the waterfront. The metro comes from imports
of workspace package names (from each package's `package.json`) at the latest commit.

The collected data is embedded in a copy of `city.template.html`. The page draws the city with instanced three.js
meshes and a custom shader for windows, fires and decay, so several thousand buildings stay smooth while they animate.

Use `--json data.json` to keep the collected data as well, if you want to build something else from it.

## Limitations

- Metro lines use the imports at the latest commit, and only JavaScript and TypeScript package imports are detected.
- Plots are sized from each file's largest-ever size, so a district that once held a huge file keeps a big plot.
- Binary files are skipped, because git doesn't count lines for them.
- Very large repositories (hundreds of thousands of files) will make a heavy page.

## Licence

MIT

"""Embedded source text must not satisfy executable module export checks."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src/desktop'))
from build_compatibility import require_named_imports

assets = {'fixture.js': 'const text="export{registry as Bce}";export{registry as G6n};\n//# sourceMappingURL=fixture.js.map'}
require_named_imports('import {G6n as manager} from "./fixture.js";', assets)
for source in ('import {Bce as manager} from "./fixture.js";',
               'import {G6n as manager, absent as other} from "./fixture.js";'):
    try:
        require_named_imports(source, assets)
    except RuntimeError:
        pass
    else:
        raise AssertionError('Missing executable export accepted')
print('PASS: only executable exports satisfy named imports; embedded tables and mixed invalid imports are rejected.')

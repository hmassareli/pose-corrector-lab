import sys
from pathlib import Path
sys.path.insert(0, 'scripts')
import check_body_fidelity as cbf
from check_palm_fidelity import Handler as Base

OLD = Path('experiments/_solver_spine_zigzag.js').resolve()

class H(Base):
    def translate_path(self, path):
        from urllib.parse import unquote, urlparse
        if unquote(urlparse(path).path) == '/static/mikapo_mixamo_solver.js':
            return str(OLD)
        return super().translate_path(path)

cbf.Handler = H
raise SystemExit(cbf.main())

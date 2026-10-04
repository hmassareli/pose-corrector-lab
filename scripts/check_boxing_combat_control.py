"""Run the existing combat fixture with the new KO behavior disabled in a
test-only browser route. This isolates pre-KO combat assertions without editing
the served files or weakening the existing test expectations.
"""
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
control=(ROOT/'viewer/boxing.js').read_text(encoding='utf-8')
control=control.replace('  prepareKnockout(a);','')
control=control.replace('const knockedOut=ko?.victim===i && !!a.knockout;', 'const knockedOut=false;')
control=re.sub(r'  if \(victim !== null && actors\[victim\]\) \{.*?\n  \}', '', control, flags=re.S)
control=re.sub(r'    if \(actors\[i\]\) \{\n      actors\[i\]\.knockout.*?\n    \}',
    '    if (actors[i]) { actors[i].groundOffset=null; actors[i].groundInitialized=false; }',control,flags=re.S)
test=ROOT/'tests/test_boxing_combat_e2e.py'
source=test.read_text(encoding='utf-8')
source=source.replace("/ 'heavy_hands_gauntlet'", "/ 'performance_audit_20261003' / 'combat-control'")
source=source.replace("    page.goto(", "    page.route('**/static/boxing.js', lambda route: route.fulfill(body=control, content_type='text/javascript'))\n    page.goto(",1)
exec(compile(source,str(test),'exec'),{'__file__':str(test),'control':control,'__name__':'__main__'})

"""Optional modules. Each is switched on with `<name>: enabled: true` in profile.yaml.

A module is a plain Python file with:
    facts(ctx) -> dict        required; its result appears in facts.py's JSON under <name>
    save(ctx, result, hist)   optional; called by `facts.py --save` to record state

They run in REGISTRY order, and a later module can read an earlier one's
result from ctx["results"]. Trips runs first because it decides where you
are each day (ctx["where"]), which the others use. To add your own module:
write scripts/modules/<name>.py, add one line below, and describe in
config/brief_composition.md how the brief should use its facts.
"""

from modules import countdowns, jobs, trips, workout

REGISTRY = [
    ("trips", trips),
    ("countdowns", countdowns),
    ("workout", workout),
    ("jobs", jobs),
]

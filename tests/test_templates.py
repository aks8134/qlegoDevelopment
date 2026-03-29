from bundled_optimization_experiments import get_bundled_templates
import traceback

try:
    templates = get_bundled_templates("1q")
    print(f"Discovered {len(templates)} templates")
    for t in templates:
        print(f"Template Name: {t.name}")
except Exception as e:
    traceback.print_exc()


import json
from pathlib import Path

from aec_intelligence.dashboard import build_dashboard_data, render_dashboard_html, write_dashboard
from aec_intelligence.pipeline import DXFIngestionPipeline


FIXTURE = Path(__file__).parents[1] / "fixtures" / "simple_house.dxf"


def test_dashboard_is_source_backed_and_rebuildable(tmp_path: Path):
    DXFIngestionPipeline(tmp_path).ingest(FIXTURE, "P-DASH", "Dashboard fixture")
    data = build_dashboard_data(tmp_path)
    assert data["metrics"]["project_count"] == 1
    assert data["metrics"]["object_count"] == 7
    outputs = write_dashboard(tmp_path)
    assert outputs["html"].is_file()
    assert outputs["data"].is_file()
    assert "Dashboard fixture" in outputs["html"].read_text(encoding="utf-8")
    assert json.loads(outputs["data"].read_text(encoding="utf-8"))["status"] == "SUCCESS"


def test_dashboard_escapes_script_payload_and_untrusted_fields(tmp_path: Path):
    import re
    import shutil
    import subprocess

    import pytest

    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to execute the generated dashboard JavaScript")
    attack = '</script><img src=x onerror="throw 123">'
    data = {"projects": [{"project_id": attack, "name": attack, "status": attack,
                         "validation_status": attack, "artifact_count": attack, "object_count": attack,
                         "type_counts": {attack: 1}}],
            "metrics": {"project_count": attack, "artifact_count": attack, "object_count": attack,
                        "validated_project_count": attack, "average_classification_confidence": None},
            "generated_at": attack, "sources": [attack]}
    page = render_dashboard_html(data)
    assert page.count("</script>") == 1 and '<img src=x' not in page
    script = re.search(r"<script>(.*?)</script>", page, re.S).group(1)
    runner = tmp_path / "dashboard-test.js"
    runner.write_text('''const elements = Object.create(null);
global.document = {
  getElementById(id) { return elements[id] ||= {value:'all', appendChild(){}, addEventListener(){}}; },
  createElement() { return {}; }
};
''' + script + '''
for (const id of ['kpis', 'types', 'projects']) {
  if (elements[id].innerHTML.includes('<img') || elements[id].innerHTML.includes('</script>'))
    throw Error('unescaped data in ' + id);
  if (!elements[id].innerHTML.includes('&lt;')) throw Error('missing escaped data in ' + id);
}
''', encoding="utf-8")
    subprocess.run([node, str(runner)], check=True, capture_output=True, timeout=10)

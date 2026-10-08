from robodocs.config import PROJECT_ROOT, get_settings


def test_settings_load():
    s = get_settings()
    frameworks = {src.framework for src in s.collection.docs}
    assert {"ros2", "isaac_sim", "isaac_lab", "mujoco"} <= frameworks


def test_every_docs_source_has_versions():
    for src in get_settings().collection.docs:
        assert src.versions, f"{src.framework} has no versions configured"


def test_paths_resolve_inside_project():
    s = get_settings()
    assert s.abs_path(s.paths.raw_data).is_relative_to(PROJECT_ROOT)

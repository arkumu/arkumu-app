from pathlib import Path

import pytest

from arkumu.projects.services.domain_dataclass_generator import DomainDataclassGenerator


@pytest.fixture
def markdown_path(settings) -> Path:
    path = Path(settings.BASE_DIR) / "202509221749 arkumu model.md"
    if not path.exists():
        pytest.skip("Domain model markdown file missing")
    return path


def test_generated_module_contains_actor_class(markdown_path):
    generator = DomainDataclassGenerator()
    module_source = generator.build_module(markdown_path)

    assert "class Actor(ArkumuEntity):" in module_source
    assert "german_name: list[str]" in module_source


def test_generated_module_executes(markdown_path):
    generator = DomainDataclassGenerator()
    module_source = generator.build_module(markdown_path)

    namespace: dict[str, object] = {}
    exec(compile(module_source, "<generated>", "exec"), namespace)

    actor_cls = namespace.get("Actor")
    assert actor_cls is not None, "Actor class should be defined"
    instance = actor_cls()  # type: ignore[operator]
    assert isinstance(instance.identifiers, list)
    assert instance.german_name == []


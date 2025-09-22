from textwrap import dedent

from arkumu.projects.services.grails_domain_parser import (
    GrailsDataclassGenerator,
    GrailsDomainParser,
)


def sample_grails_domain() -> str:
    return dedent(
        """
        package de.unikoeln.digikunst

        class Projekt {
            String uuid
            Titel bevorzugterTitel
            Boolean restricted = false
            Date erstellungsDatumEinlieferer
            List<String> normdateiListe = []

            static hasMany = [
                ereignisse: Ereignis,
                schlagworte: Schlagwort
            ]

            static belongsTo = [Sammlung]
        }
        """
    )


def test_parser_extracts_fields_has_many_and_belongs_to():
    parser = GrailsDomainParser()
    domain = parser.parse_text(sample_grails_domain())

    assert domain.name == "Projekt"
    field_names = [field.name for field in domain.fields]
    assert "uuid" in field_names
    assert domain.has_many["ereignisse"] == "Ereignis"
    assert domain.belongs_to == ["Sammlung"]


def test_generator_produces_dataclass_structure():
    parser = GrailsDomainParser()
    domain = parser.parse_text(sample_grails_domain())
    generator = GrailsDataclassGenerator()
    module = generator.build_module([domain])

    assert "class Projekt:" in module
    assert "uuid: Optional[str] = None" in module
    assert "normdateiListe: list[str] = field(default_factory=list)" in module

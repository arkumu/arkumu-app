# Kreuz Configuration Reference

## What is this?

When we import data from institutions (KHM, FUK, HMT), relationships between entities are stored in **cross tables** (German: "Kreuztabellen"). For example, to know which actors participated in a film project, you need to look up a separate linking table.

**The problem:** To answer "Who worked on this project?", the system must:
1. Find the project
2. Look up the cross table
3. Find the actor references
4. Fetch the actor details

**The solution:** The derivation system creates **direct links** between entities, so the system can directly answer "Project X has Actor Y" without intermediate lookups.

### Before derivation
```
Project  ─┐
          ├── Cross Table ──┬── Actor
Event ────┘                 └── Role
```

### After derivation
```
Project ────── Actor (direct link created)
```

This makes queries faster and simplifies the data model for downstream consumers (OAI-PMH, catalog views, etc.).

---

## Technical Reference

This section documents `arkumu/metadata/derivations/kreuz_config.py`.

## Key Concepts

### Canonical Predicates

Each institution uses different names for the same concept (e.g., KHM calls it "Projekt_ID", FUK calls it "projekt"). Canonical predicates are **standardized identifiers** that unify these across all institutions:

| Constant | URI |
|----------|-----|
| `PROJECT` | `http://arkumu.org/data/properties/projekt` |
| `EVENT` | `http://arkumu.org/data/properties/ereignis` |
| `DIGITAL_OBJECT` | `http://arkumu.org/data/properties/digitales-objekt` |
| `INFORMATION_CARRIER` | `http://arkumu.org/data/properties/informationstraeger` |
| `KEYWORD` | `http://arkumu.org/data/properties/schlagwort` |
| `EQUIPMENT` | `http://arkumu.org/data/properties/equipment-software` |
| `ACTOR` | `http://arkumu.org/data/properties/akteurin` |
| `ACTOR_IN_EVENT` | `http://arkumu.org/data/properties/akteurin-im-ereignis` |
| `ROLE_IN_EVENT` | `http://arkumu.org/data/properties/rollen-der-akteurin-im-ereignis` |

### Derivation Patterns

A pattern defines **what direct links to create** when certain data exists. For example:
- "If a cross table has both PROJECT and ACTOR references, create a direct Project→Actor link"

Technically, a `DerivationPattern` contains:
- `required_properties`: which predicates must exist in the source data
- `recipes`: which new links to create

### Dataset Profiles

Each cross table is registered with its available predicates and applicable patterns. This tells the system:
- "This table contains PROJECT and ACTOR data"
- "Apply the project_actor pattern to create direct links"

## Available Patterns

All patterns that can create direct links:

| Pattern | Required Predicates | Direct Link Created |
|---------|----------|---------|
| `project_event` | PROJECT, EVENT | Project <-> Event (bidirectional) |
| `project_event_subject` | PROJECT | Project -> Event (dataset subject as event) |
| `event_digital_object` | EVENT, DIGITAL_OBJECT | Event -> Digital Object |
| `project_digital_object` | PROJECT, DIGITAL_OBJECT | Project -> Digital Object |
| `project_event_digital_bridge` | PROJECT, EVENT, DIGITAL_OBJECT | Project -> Digital Object (via junction) |
| `project_information_carrier` | PROJECT, INFORMATION_CARRIER | Project -> Information Carrier |
| `event_information_carrier` | EVENT, INFORMATION_CARRIER | Event -> Information Carrier |
| `project_keyword` | PROJECT, KEYWORD | Project -> Keyword |
| `project_equipment` | PROJECT, EQUIPMENT | Project -> Equipment |
| `event_equipment` | EVENT, EQUIPMENT | Event -> Equipment |
| `project_actor` | PROJECT, ACTOR | Project -> Actor (direct) |
| `event_actor` | EVENT, ACTOR_IN_EVENT | Event -> Actor (via role junction) |
| `project_event_actor_bridge` | PROJECT, EVENT, ACTOR_IN_EVENT | Project -> Actor (via event junction) |

## Organization Profiles

Which cross tables exist per institution and what patterns apply to them.

### KHM (Kunsthochschule für Medien Köln)

| Dataset | Predicates | Patterns |
|---------|------------|----------|
| `01_grundereignis` | PROJECT, EVENT, DIGITAL_OBJECT | project_event, project_event_subject, event_digital_object, project_event_digital_bridge, project_digital_object |
| `02_kreuz_projekte_personen` | PROJECT, EVENT, ACTOR_IN_EVENT, ROLE_IN_EVENT | event_actor, project_event_actor_bridge |
| `04_kreuz_betreuende_projekte` | PROJECT, EVENT, ACTOR_IN_EVENT | event_actor, project_event_actor_bridge |
| `07_kreuz_projekte_keywords` | PROJECT, KEYWORD | project_keyword |
| `09_kreuz_projekte_informationstraeger` | PROJECT, INFORMATION_CARRIER | project_information_carrier |
| `11_kreuz_digitaleobjekte_proj` | PROJECT, DIGITAL_OBJECT | project_digital_object |
| `16_kreuz_events_projekte` | PROJECT, EVENT | project_event |
| `18_kreuz_projekte_equipmentssoftware` | PROJECT, EQUIPMENT | project_equipment |

### FUK (Folkwang Universität der Künste)

| Dataset | Predicates | Patterns |
|---------|------------|----------|
| `projekt_ereignis` | PROJECT, EVENT | project_event |
| `ereignis_digitales_objekt` | EVENT, DIGITAL_OBJECT | event_digital_object, project_event_digital_bridge |
| `ereignis_informationstraeger` | EVENT, INFORMATION_CARRIER | event_information_carrier |
| `ereignis_equipment_software` | EVENT, EQUIPMENT | event_equipment |
| `projekt_schlagworte` | PROJECT, KEYWORD | project_keyword |
| `akteurin_ereignis_kreuztabelle` | EVENT, ACTOR_IN_EVENT, ROLE_IN_EVENT | event_actor, project_event_actor_bridge |

### HMT (Hochschule für Musik und Theater)

HMT currently shares FUK's configuration until a dedicated profile is created.

## Usage

After importing data and running `map_canonical_uris`, run the derivation command to create direct links:

```bash
# Run inside Docker container
docker compose -f docker-compose.local.yml run --rm django python manage.py derive_project_relationships --org khm
docker compose -f docker-compose.local.yml run --rm django python manage.py derive_project_relationships --org fuk
docker compose -f docker-compose.local.yml run --rm django python manage.py derive_project_relationships --org hmt
```

This should be run whenever:
- New data is imported
- Cross table mappings change
- New patterns are added

## Adding New Patterns

1. Define the pattern in `DERIVATION_PATTERNS`:

```python
"new_pattern": DerivationPattern(
    name="new_pattern",
    required_properties=(SOURCE_PREDICATE, TARGET_PREDICATE),
    recipes=(
        DerivedTripleRecipe(
            subject_property=SOURCE_PREDICATE,
            object_property=TARGET_PREDICATE,
            predicate_uri=DERIVED_PREDICATE,
            description="Source references Target",
        ),
    ),
),
```

2. Add the pattern to relevant dataset profiles in `KREUZ_DATASET_PROFILES`.

3. Re-run derivations for affected organizations.

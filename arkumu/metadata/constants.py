"""Shared metadata constants used across workspace views and services."""

ACTOR_EVENT_FIELD_NAME = "__join__AkteurIn_Ereignis_Kreuztabelle__AkteurIn"
ACTOR_EVENT_JOIN_DATASET = "AkteurIn_Ereignis_Kreuztabelle"
ACTOR_EVENT_ROLE_CONTEXT_COLUMN = "Rollen der AkteurIn im Ereignis"
ACTOR_EVENT_ROLE_DATASET = "Rolle"
ACTOR_EVENT_ROLE_SEARCH_PROPERTY = "Bezeichnung"
ACTOR_EVENT_ROLE_PROPERTY_URI = "http://arkumu.org/data/fuk/properties/rollen-der-akteurin-im-ereignis"

ACTOR_EVENT_FLAG_CONTEXT_SPECS = [
    {
        "column": "Ungesicherte Zuschreibung",
        "property_uri": "http://arkumu.org/data/fuk/properties/ungesicherte-zuschreibung",
        "widget": "select",
        "choices": [
            {"label": "Keine Angabe", "value": ""},
            {"label": "Ja", "value": "1"},
            {"label": "Nein", "value": "0"},
        ],
    },
    {
        "column": "besitzt Leistungsschutzrechte",
        "property_uri": "http://arkumu.org/data/fuk/properties/besitzt-leistungsschutzrechte",
        "widget": "select",
        "choices": [
            {"label": "Keine Angabe", "value": ""},
            {"label": "Ja", "value": "1"},
            {"label": "Nein", "value": "0"},
        ],
    },
    {
        "column": "ist UrheberIn",
        "property_uri": "http://arkumu.org/data/fuk/properties/ist-urheberin",
        "widget": "select",
        "choices": [
            {"label": "Keine Angabe", "value": ""},
            {"label": "Ja", "value": "1"},
            {"label": "Nein", "value": "0"},
        ],
    },
]

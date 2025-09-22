"""Auto-generated dataclasses from Arkumu domain model."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ArkumuEntity:
    uri: str | None = None
    identifiers: list[str] = field(default_factory=list)

@dataclass
class Actor(ArkumuEntity):
    """EN: An Actor is either a single living or dead real person, a group of such persons, or a legal body. Fictional Actors or role names, for example, should be recorded as a description or comment in an Event.
DE: Ein:e Akteur:in ist entweder eine einzelne lebende oder verstorbene reale Person, eine Gruppe solcher Personen oder eine Körperschaft. Fiktive Akteur:innen oder Rollennamen, zum Beispiel, sollten als Beschreibung oder Kommentar in einem Ereignis verzeichnet werden."""
    german_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german name', 'label_en': 'German Name', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-german-name', 'graph_id': 'arkumu:hasGermanName', 'property_slug': 'has-german-name', 'cardinality': 'repeatable' },
    )
    english_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english name', 'label_en': 'English Name', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-english-name', 'graph_id': 'arkumu:hasEnglishName', 'property_slug': 'has-english-name', 'cardinality': 'repeatable' },
    )
    alternative_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has alternative name', 'label_en': 'Alternative Name', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-alternative-name', 'graph_id': 'arkumu:hasAlternativeName', 'property_slug': 'has-alternative-name', 'cardinality': 'repeatable' },
    )
    non_public_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has non-public name', 'label_en': 'Non-public Name', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-non-public-name', 'graph_id': 'arkumu:hasNon-publicName', 'property_slug': 'has-non-public-name', 'cardinality': 'repeatable' },
    )
    preceding_title: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has preceding title', 'label_en': 'Preceding Title', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-preceding-title', 'graph_id': 'arkumu:hasPrecedingTitle', 'property_slug': 'has-preceding-title', 'cardinality': 'repeatable' },
    )
    trailing_title: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has trailing title', 'label_en': 'Trailing Title', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-trailing-title', 'graph_id': 'arkumu:hasTrailingTitle', 'property_slug': 'has-trailing-title', 'cardinality': 'repeatable' },
    )
    gender: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has gender', 'label_en': 'Gender', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-gender', 'graph_id': 'arkumu:hasGender', 'property_slug': 'has-gender', 'cardinality': 'repeatable', 'vocabulary': 'genders' },
    )
    date_of_birth: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has date of birth', 'label_en': 'Date of Birth', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-date-of-birth', 'graph_id': 'arkumu:hasDateOfBirth', 'property_slug': 'has-date-of-birth', 'cardinality': 'repeatable' },
    )
    date_of_death: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has date of death', 'label_en': 'Date of Death', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-date-of-death', 'graph_id': 'arkumu:hasDateOfDeath', 'property_slug': 'has-date-of-death', 'cardinality': 'repeatable' },
    )
    beginning_of_activity: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has beginning of activity', 'label_en': 'Beginning of Activity', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-beginning-of-activity', 'graph_id': 'arkumu:hasBeginningOfActivity', 'property_slug': 'has-beginning-of-activity', 'cardinality': 'repeatable' },
    )
    end_of_activity: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has end of activity', 'label_en': 'End of Activity', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-end-of-activity', 'graph_id': 'arkumu:hasEndOfActivity', 'property_slug': 'has-end-of-activity', 'cardinality': 'repeatable' },
    )
    place: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has place of birth', 'label_en': 'Place', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-place-of-birth', 'graph_id': 'arkumu:hasPlaceOfBirth', 'property_slug': 'has-place-of-birth', 'cardinality': 'repeatable' },
    )
    place_2: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has place of death', 'label_en': 'Place', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-place-of-death', 'graph_id': 'arkumu:hasPlaceOfDeath', 'property_slug': 'has-place-of-death', 'cardinality': 'repeatable' },
    )
    place_3: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has place of activity', 'label_en': 'Place', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-place-of-activity', 'graph_id': 'arkumu:hasPlaceOfActivity', 'property_slug': 'has-place-of-activity', 'cardinality': 'repeatable' },
    )
    place_4: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has place of foundation', 'label_en': 'Place', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-place-of-foundation', 'graph_id': 'arkumu:hasPlaceOfFoundation', 'property_slug': 'has-place-of-foundation', 'cardinality': 'repeatable' },
    )
    place_5: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has place of dissolution', 'label_en': 'Place', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-place-of-dissolution', 'graph_id': 'arkumu:hasPlaceOfDissolution', 'property_slug': 'has-place-of-dissolution', 'cardinality': 'repeatable' },
    )
    german_short_biography: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german short biography', 'label_en': 'German Short Biography', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-german-short-biography', 'graph_id': 'arkumu:hasGermanShortBiography', 'property_slug': 'has-german-short-biography', 'cardinality': 'repeatable' },
    )
    english_short_biography: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english short biography', 'label_en': 'English Short Biography', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-english-short-biography', 'graph_id': 'arkumu:hasEnglishShortBiography', 'property_slug': 'has-english-short-biography', 'cardinality': 'repeatable' },
    )
    german_commentary: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german commentary', 'label_en': 'German Commentary', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-german-commentary', 'graph_id': 'arkumu:hasGermanCommentary', 'property_slug': 'has-german-commentary', 'cardinality': 'repeatable' },
    )
    english_commentary: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english commentary', 'label_en': 'English Commentary', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-english-commentary', 'graph_id': 'arkumu:hasEnglishCommentary', 'property_slug': 'has-english-commentary', 'cardinality': 'repeatable' },
    )
    internal_commentary: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has internal commentary', 'label_en': 'Internal Commentary', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-internal-commentary', 'graph_id': 'arkumu:hasInternalCommentary', 'property_slug': 'has-internal-commentary', 'cardinality': 'repeatable' },
    )
    role: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has profession or activity', 'label_en': 'Role', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-profession-or-activity', 'graph_id': 'arkumu:hasProfessionOrActivity', 'property_slug': 'has-profession-or-activity', 'cardinality': 'repeatable' },
    )
    orcid: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has ORCID', 'label_en': 'ORCID', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-orcid', 'graph_id': 'arkumu:hasOrcid', 'property_slug': 'has-orcid', 'cardinality': 'repeatable' },
    )
    wikidata_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has Wikidata ID', 'label_en': 'Wikidata ID', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-wikidata-id', 'graph_id': 'arkumu:hasWikidataId', 'property_slug': 'has-wikidata-id', 'cardinality': 'repeatable' },
    )
    gnd_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has GND ID', 'label_en': 'GND ID', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-gnd-id', 'graph_id': 'arkumu:hasGndId', 'property_slug': 'has-gnd-id', 'cardinality': 'repeatable' },
    )
    viaf_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has VIAF ID', 'label_en': 'VIAF ID', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-viaf-id', 'graph_id': 'arkumu:hasViafId', 'property_slug': 'has-viaf-id', 'cardinality': 'repeatable' },
    )
    lccn_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has LCCN ID', 'label_en': 'LCCN ID', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-lccn-id', 'graph_id': 'arkumu:hasLccnId', 'property_slug': 'has-lccn-id', 'cardinality': 'repeatable' },
    )
    other_authority_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has other authority ID', 'label_en': 'Other Authority ID', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-other-authority-id', 'graph_id': 'arkumu:hasOtherAuthorityId', 'property_slug': 'has-other-authority-id', 'cardinality': 'repeatable' },
    )
    website: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has website', 'label_en': 'Website', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-website', 'graph_id': 'arkumu:hasWebsite', 'property_slug': 'has-website', 'cardinality': 'repeatable' },
    )
    contact_e_mail: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has contact e-mail', 'label_en': 'Contact (E-Mail)', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-contact-e-mail', 'graph_id': 'arkumu:hasContactE-mail', 'property_slug': 'has-contact-e-mail', 'cardinality': 'repeatable' },
    )
    contact_phone: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has contact phone number', 'label_en': 'Contact (Phone)', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-contact-phone-number', 'graph_id': 'arkumu:hasContactPhoneNumber', 'property_slug': 'has-contact-phone-number', 'cardinality': 'repeatable' },
    )
    contact_postal_address: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has contact postal address', 'label_en': 'Contact (Postal Address)', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-contact-postal-address', 'graph_id': 'arkumu:hasContactPostalAddress', 'property_slug': 'has-contact-postal-address', 'cardinality': 'repeatable' },
    )
    dataset_id_at_depositor: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has dataset ID at depositor', 'label_en': 'Dataset ID at Depositor', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-dataset-id-at-depositor', 'graph_id': 'arkumu:hasDatasetIdAtDepositor', 'property_slug': 'has-dataset-id-at-depositor', 'cardinality': 'repeatable' },
    )
    organisational_unit: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has depositor', 'label_en': 'Organisational Unit', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-depositor', 'graph_id': 'arkumu:hasDepositor', 'property_slug': 'has-depositor', 'cardinality': 'repeatable' },
    )
    dataset_creation_date_at_depositor: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has dataset creation date at depositor', 'label_en': 'Dataset Creation Date at Depositor', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-dataset-creation-date-at-depositor', 'graph_id': 'arkumu:hasDatasetCreationDateAtDepositor', 'property_slug': 'has-dataset-creation-date-at-depositor', 'cardinality': 'repeatable' },
    )
    dataset_last_modification_date_at_depositor: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has dataset last modification date at depositor', 'label_en': 'Dataset Last Modification Date at Depositor', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-dataset-last-modification-date-at-depositor', 'graph_id': 'arkumu:hasDatasetLastModificationDateAtDepositor', 'property_slug': 'has-dataset-last-modification-date-at-depositor', 'cardinality': 'repeatable' },
    )
    actor: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has related actor', 'label_en': 'Actor', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-related-actor', 'graph_id': 'arkumu:hasRelatedActor', 'property_slug': 'has-related-actor', 'cardinality': 'repeatable' },
    )

@dataclass
class AlternativeTitleSet(ArkumuEntity):
    """EN: Ein Set aus einem möglichen alternativen Titel und einem möglichen alternativen Untertitel.
DE: A set of a possible alternative title and a possible alternative subtitle."""
    alternative_title: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has alternative title', 'label_en': 'Alternative Title', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-alternative-title', 'graph_id': 'arkumu:hasAlternativeTitle', 'property_slug': 'has-alternative-title', 'cardinality': 'repeatable' },
    )
    alternative_subtitle: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has alternative subtitle', 'label_en': 'Alternative Subtitle', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-alternative-subtitle', 'graph_id': 'arkumu:hasAlternativeSubtitle', 'property_slug': 'has-alternative-subtitle', 'cardinality': 'repeatable' },
    )

@dataclass
class DepositingUniversity(ArkumuEntity):
    """EN: The university responsible for the data submitted.
DE: Die für die eingelieferten Daten verantwortliche Hochschule."""
    german_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german name', 'label_en': 'German Name', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-german-name', 'graph_id': 'arkumu:hasGermanName', 'property_slug': 'has-german-name', 'cardinality': 'repeatable' },
    )
    english_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english name', 'label_en': 'English Name', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-english-name', 'graph_id': 'arkumu:hasEnglishName', 'property_slug': 'has-english-name', 'cardinality': 'repeatable' },
    )
    wikidata_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has Wikidata ID', 'label_en': 'Wikidata ID', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-wikidata-id', 'graph_id': 'arkumu:hasWikidataId', 'property_slug': 'has-wikidata-id', 'cardinality': 'repeatable' },
    )
    gnd_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has GND ID', 'label_en': 'GND ID', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-gnd-id', 'graph_id': 'arkumu:hasGndId', 'property_slug': 'has-gnd-id', 'cardinality': 'repeatable' },
    )

@dataclass
class DigitalObject(ArkumuEntity):
    """EN: A Digital Object is a single file with its corresponding metadata set. Descriptive metadata is data entered by users, technical metadata is automatically read out by software.
DE: Ein Digitales Objekt ist eine einzelne Datei mit dazugehörigen Metadaten. Beschreibene Metadaten werden von Nutzer:innen eingegeben, technische Metadaten werden von Software automatisch ausgelesen."""
    file_path: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has file path', 'label_en': 'File Path', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-file-path', 'graph_id': 'arkumu:hasFilePath', 'property_slug': 'has-file-path', 'cardinality': 'repeatable' },
    )
    file_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has file name', 'label_en': 'File Name', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-file-name', 'graph_id': 'arkumu:hasFileName', 'property_slug': 'has-file-name', 'cardinality': 'repeatable' },
    )
    file_size: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has file size', 'label_en': 'File Size', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-file-size', 'graph_id': 'arkumu:hasFileSize', 'property_slug': 'has-file-size', 'cardinality': 'repeatable' },
    )
    mime_type: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has MIME type', 'label_en': 'MIME Type', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-mime-type', 'graph_id': 'arkumu:hasMimeType', 'property_slug': 'has-mime-type', 'cardinality': 'repeatable' },
    )
    media_type: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has media type', 'label_en': 'Media Type', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-media-type', 'graph_id': 'arkumu:hasMediaType', 'property_slug': 'has-media-type', 'cardinality': 'repeatable', 'vocabulary': 'media-types' },
    )
    genesis_type: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has genesis type', 'label_en': 'Genesis Type', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-genesis-type', 'graph_id': 'arkumu:hasGenesisType', 'property_slug': 'has-genesis-type', 'cardinality': 'repeatable', 'vocabulary': 'genesis-types' },
    )
    file_package: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'is file package', 'label_en': 'File Package', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#is-file-package', 'graph_id': 'arkumu:isFilePackage', 'property_slug': 'is-file-package', 'cardinality': 'repeatable' },
    )
    preservation_type: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has preservation type', 'label_en': 'Preservation Type', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-preservation-type', 'graph_id': 'arkumu:hasPreservationType', 'property_slug': 'has-preservation-type', 'cardinality': 'repeatable' },
    )
    derivate_copy_number: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has derivate copy number', 'label_en': 'Derivate Copy Number', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-derivate-copy-number', 'graph_id': 'arkumu:hasDerivateCopyNumber', 'property_slug': 'has-derivate-copy-number', 'cardinality': 'repeatable' },
    )
    digital_object_keyword: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has digital object keyword', 'label_en': 'Digital Object Keyword', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-digital-object-keyword', 'graph_id': 'arkumu:hasDigitalObjectKeyword', 'property_slug': 'has-digital-object-keyword', 'cardinality': 'repeatable' },
    )
    digital_object_license: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has digital object license', 'label_en': 'Digital Object License', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-digital-object-license', 'graph_id': 'arkumu:hasDigitalObjectLicense', 'property_slug': 'has-digital-object-license', 'cardinality': 'repeatable' },
    )
    german_content_description: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german content description', 'label_en': 'German Content Description', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-german-content-description', 'graph_id': 'arkumu:hasGermanContentDescription', 'property_slug': 'has-german-content-description', 'cardinality': 'repeatable' },
    )
    english_content_description: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english content description', 'label_en': 'English Content Description', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-english-content-description', 'graph_id': 'arkumu:hasEnglishContentDescription', 'property_slug': 'has-english-content-description', 'cardinality': 'repeatable' },
    )
    german_image_description: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german image description', 'label_en': 'German Image Description', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-german-image-description', 'graph_id': 'arkumu:hasGermanImageDescription', 'property_slug': 'has-german-image-description', 'cardinality': 'repeatable' },
    )
    english_image_description: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english image description', 'label_en': 'English Image Description', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-english-image-description', 'graph_id': 'arkumu:hasEnglishImageDescription', 'property_slug': 'has-english-image-description', 'cardinality': 'repeatable' },
    )
    german_commentary: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german commentary', 'label_en': 'German Commentary', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-german-commentary', 'graph_id': 'arkumu:hasGermanCommentary', 'property_slug': 'has-german-commentary', 'cardinality': 'repeatable' },
    )
    english_commentary: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english commentary', 'label_en': 'English Commentary', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-english-commentary', 'graph_id': 'arkumu:hasEnglishCommentary', 'property_slug': 'has-english-commentary', 'cardinality': 'repeatable' },
    )
    internal_commentary: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has internal commentary', 'label_en': 'Internal Commentary', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-internal-commentary', 'graph_id': 'arkumu:hasInternalCommentary', 'property_slug': 'has-internal-commentary', 'cardinality': 'repeatable' },
    )
    significant_properties_german: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has significant properties (german)', 'label_en': 'Significant Properties (German)', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-significant-properties-german', 'graph_id': 'arkumu:hasSignificantPropertiesGerman', 'property_slug': 'has-significant-properties-german', 'cardinality': 'repeatable' },
    )
    significant_properties_english: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has significant properties (english)', 'label_en': 'Significant Properties (English)', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-significant-properties-english', 'graph_id': 'arkumu:hasSignificantPropertiesEnglish', 'property_slug': 'has-significant-properties-english', 'cardinality': 'repeatable' },
    )
    system_requirements: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has system requirements', 'label_en': 'System Requirements', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-system-requirements', 'graph_id': 'arkumu:hasSystemRequirements', 'property_slug': 'has-system-requirements', 'cardinality': 'repeatable' },
    )
    checksum: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has checksum', 'label_en': 'Checksum', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-checksum', 'graph_id': 'arkumu:hasChecksum', 'property_slug': 'has-checksum', 'cardinality': 'repeatable' },
    )
    checksum_at_depositor: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has checksum at depositor', 'label_en': 'Checksum at Depositor', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-checksum-at-depositor', 'graph_id': 'arkumu:hasChecksumAtDepositor', 'property_slug': 'has-checksum-at-depositor', 'cardinality': 'repeatable' },
    )
    jhove_status: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has JHOVE status', 'label_en': 'JHOVE Status', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-jhove-status', 'graph_id': 'arkumu:hasJhoveStatus', 'property_slug': 'has-jhove-status', 'cardinality': 'repeatable' },
    )
    droid_puid: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has DROID puid', 'label_en': 'DROID PUID', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-droid-puid', 'graph_id': 'arkumu:hasDroidPuid', 'property_slug': 'has-droid-puid', 'cardinality': 'repeatable' },
    )
    jhove_metadata: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has JHOVE metadata', 'label_en': 'JHOVE Metadata', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-jhove-metadata', 'graph_id': 'arkumu:hasJhoveMetadata', 'property_slug': 'has-jhove-metadata', 'cardinality': 'repeatable' },
    )
    droid_metadata: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has DROID metadata', 'label_en': 'DROID Metadata', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-droid-metadata', 'graph_id': 'arkumu:hasDroidMetadata', 'property_slug': 'has-droid-metadata', 'cardinality': 'repeatable' },
    )
    exiftool_metadata: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has ExifTool metadata', 'label_en': 'ExifTool Metadata', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-exiftool-metadata', 'graph_id': 'arkumu:hasExiftoolMetadata', 'property_slug': 'has-exiftool-metadata', 'cardinality': 'repeatable' },
    )
    mediainfo_metadata: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has MediaInfo metadata', 'label_en': 'MediaInfo Metadata', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-mediainfo-metadata', 'graph_id': 'arkumu:hasMediainfoMetadata', 'property_slug': 'has-mediainfo-metadata', 'cardinality': 'repeatable' },
    )
    dataset_id_at_depositor: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has dataset ID at depositor', 'label_en': 'Dataset ID at Depositor', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-dataset-id-at-depositor', 'graph_id': 'arkumu:hasDatasetIdAtDepositor', 'property_slug': 'has-dataset-id-at-depositor', 'cardinality': 'repeatable' },
    )
    organisational_unit: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has depositor', 'label_en': 'Organisational Unit', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-depositor', 'graph_id': 'arkumu:hasDepositor', 'property_slug': 'has-depositor', 'cardinality': 'repeatable' },
    )
    dataset_creation_date_at_depositor: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has dataset creation date at depositor', 'label_en': 'Dataset Creation Date at Depositor', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-dataset-creation-date-at-depositor', 'graph_id': 'arkumu:hasDatasetCreationDateAtDepositor', 'property_slug': 'has-dataset-creation-date-at-depositor', 'cardinality': 'repeatable' },
    )
    dataset_last_modification_date_at_depositor: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has dataset last modification date at depositor', 'label_en': 'Dataset Last Modification Date at Depositor', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-dataset-last-modification-date-at-depositor', 'graph_id': 'arkumu:hasDatasetLastModificationDateAtDepositor', 'property_slug': 'has-dataset-last-modification-date-at-depositor', 'cardinality': 'repeatable' },
    )
    is_arkumu_preview: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has is arkumu preview', 'label_en': 'is arkumu Preview', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-is-arkumu-preview', 'graph_id': 'arkumu:hasIsArkumuPreview', 'property_slug': 'has-is-arkumu-preview', 'cardinality': 'repeatable' },
    )
    is_poster_image: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has is poster image', 'label_en': 'is Poster Image', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-is-poster-image', 'graph_id': 'arkumu:hasIsPosterImage', 'property_slug': 'has-is-poster-image', 'cardinality': 'repeatable' },
    )
    television_standard: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has television standard', 'label_en': 'Television Standard', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-television-standard', 'graph_id': 'arkumu:hasTelevisionStandard', 'property_slug': 'has-television-standard', 'cardinality': 'repeatable' },
    )
    frame_rate: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has frame rate', 'label_en': 'Frame Rate', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-frame-rate', 'graph_id': 'arkumu:hasFrameRate', 'property_slug': 'has-frame-rate', 'cardinality': 'repeatable' },
    )
    aspect_ratio: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has aspect ratio', 'label_en': 'Aspect Ratio', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-aspect-ratio', 'graph_id': 'arkumu:hasAspectRatio', 'property_slug': 'has-aspect-ratio', 'cardinality': 'repeatable' },
    )

@dataclass
class EquipmentAndSoftware(ArkumuEntity):
    """EN: Tools and Software that were used during an Event to achieve the result of an activity in question.
DE: Werkzeuge und Software, die während eines Ereignisses verwendet wurden, um das Ergebnis einer bestimmten Aktivität zu erreichen."""
    german_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german name', 'label_en': 'German Name', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-german-name', 'graph_id': 'arkumu:hasGermanName', 'property_slug': 'has-german-name', 'cardinality': 'repeatable' },
    )
    english_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english name', 'label_en': 'English Name', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-english-name', 'graph_id': 'arkumu:hasEnglishName', 'property_slug': 'has-english-name', 'cardinality': 'repeatable' },
    )
    producer: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has producer', 'label_en': 'Producer', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-producer', 'graph_id': 'arkumu:hasProducer', 'property_slug': 'has-producer', 'cardinality': 'repeatable' },
    )
    wikidata_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has Wikidata ID', 'label_en': 'Wikidata ID', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-wikidata-id', 'graph_id': 'arkumu:hasWikidataId', 'property_slug': 'has-wikidata-id', 'cardinality': 'repeatable' },
    )
    gnd_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has GND ID', 'label_en': 'GND ID', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-gnd-id', 'graph_id': 'arkumu:hasGndId', 'property_slug': 'has-gnd-id', 'cardinality': 'repeatable' },
    )
    german_description: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german description', 'label_en': 'German Description', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-german-description', 'graph_id': 'arkumu:hasGermanDescription', 'property_slug': 'has-german-description', 'cardinality': 'repeatable' },
    )
    english_description: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english description', 'label_en': 'English Description', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-english-description', 'graph_id': 'arkumu:hasEnglishDescription', 'property_slug': 'has-english-description', 'cardinality': 'repeatable' },
    )

@dataclass
class EquipmentType(ArkumuEntity):
    """EN: An Equipment Type categorises a piece of equipment or a piece of software using a controlled vocabulary.
DE: Eine Ereignisart kategorisiert eine Stück Equipment oder ein Stück Software mit Hilfe eines kontrollierten Vokabulars."""
    german_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german name', 'label_en': 'German Name', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-german-name', 'graph_id': 'arkumu:hasGermanName', 'property_slug': 'has-german-name', 'cardinality': 'repeatable' },
    )
    english_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english name', 'label_en': 'English Name', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-english-name', 'graph_id': 'arkumu:hasEnglishName', 'property_slug': 'has-english-name', 'cardinality': 'repeatable' },
    )
    wikidata_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has Wikidata ID', 'label_en': 'Wikidata ID', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-wikidata-id', 'graph_id': 'arkumu:hasWikidataId', 'property_slug': 'has-wikidata-id', 'cardinality': 'repeatable' },
    )
    gnd_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has GND ID', 'label_en': 'GND ID', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-gnd-id', 'graph_id': 'arkumu:hasGndId', 'property_slug': 'has-gnd-id', 'cardinality': 'repeatable' },
    )
    aat_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has AAT ID', 'label_en': 'AAT ID', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-aat-id', 'graph_id': 'arkumu:hasAatId', 'property_slug': 'has-aat-id', 'cardinality': 'repeatable' },
    )

@dataclass
class Event(ArkumuEntity):
    """EN: Events represent occurrences in the real world that have happened in connection with a Project and its Actors. Events have a temporal beginning and a temporal end and take place in real Places. Abstract places ('on the internet') or fictional places ('Duckburg') need to be recorded as comments. Events are performed or executed by various actors, which can lead to legal ownership. Events manifest themselves or are documented in Digital Objects (files and their metadata).
DE: Ereignisse bilden Geschehnisse in der realen Welt ab, die im Zusammenhang mit einem Projekt und dessen Akteur:innen passiert sind. Ereignisse haben einen zeitlichen Beginn und ein zeitliches Ende und finden an realen Orten statt. Abstrakte Orte ("im Internet") oder fiktive Orte ("Entenhausen") sind als Kommentar zu verzeichnen. Ereignisse werden von verschiedenen Akteur:innen durch- oder aufgeführt, wodurch sich rechtliche Ansprüche ableiten können. Ereignisse manifestieren sich oder werden dokumentiert in Digitalen Objekten (Dateien und ihren Metadaten)."""
    german_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german name', 'label_en': 'German Name', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-german-name', 'graph_id': 'arkumu:hasGermanName', 'property_slug': 'has-german-name', 'cardinality': 'repeatable' },
    )
    english_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english name', 'label_en': 'English Name', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-english-name', 'graph_id': 'arkumu:hasEnglishName', 'property_slug': 'has-english-name', 'cardinality': 'repeatable' },
    )
    event_type: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has event type', 'label_en': 'Event Type', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-event-type', 'graph_id': 'arkumu:hasEventType', 'property_slug': 'has-event-type', 'cardinality': 'repeatable', 'vocabulary': 'event-types' },
    )
    event_beginning: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has event beginning', 'label_en': 'Event Beginning', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-event-beginning', 'graph_id': 'arkumu:hasEventBeginning', 'property_slug': 'has-event-beginning', 'cardinality': 'repeatable' },
    )
    event_end: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has event end', 'label_en': 'Event End', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-event-end', 'graph_id': 'arkumu:hasEventEnd', 'property_slug': 'has-event-end', 'cardinality': 'repeatable' },
    )
    place: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has event place', 'label_en': 'Place', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-event-place', 'graph_id': 'arkumu:hasEventPlace', 'property_slug': 'has-event-place', 'cardinality': 'repeatable' },
    )
    event_description: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has event description', 'label_en': 'Event Description', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-event-description', 'graph_id': 'arkumu:hasEventDescription', 'property_slug': 'has-event-description', 'cardinality': 'repeatable' },
    )
    german_commentary: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german commentary', 'label_en': 'German Commentary', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-german-commentary', 'graph_id': 'arkumu:hasGermanCommentary', 'property_slug': 'has-german-commentary', 'cardinality': 'repeatable' },
    )
    english_commentary: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english commentary', 'label_en': 'English Commentary', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-english-commentary', 'graph_id': 'arkumu:hasEnglishCommentary', 'property_slug': 'has-english-commentary', 'cardinality': 'repeatable' },
    )
    internal_commentary: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has internal commentary', 'label_en': 'Internal Commentary', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-internal-commentary', 'graph_id': 'arkumu:hasInternalCommentary', 'property_slug': 'has-internal-commentary', 'cardinality': 'repeatable' },
    )
    event_property: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has event property', 'label_en': 'Event Property', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-event-property', 'graph_id': 'arkumu:hasEventProperty', 'property_slug': 'has-event-property', 'cardinality': 'repeatable' },
    )
    event: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has related event', 'label_en': 'Event', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-related-event', 'graph_id': 'arkumu:hasRelatedEvent', 'property_slug': 'has-related-event', 'cardinality': 'repeatable' },
    )
    actor: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has actor', 'label_en': 'Actor', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-actor', 'graph_id': 'arkumu:hasActor', 'property_slug': 'has-actor', 'cardinality': 'repeatable' },
    )
    equipment_and_software: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has equipment and software', 'label_en': 'Equipment and Software', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-equipment-and-software', 'graph_id': 'arkumu:hasEquipmentAndSoftware', 'property_slug': 'has-equipment-and-software', 'cardinality': 'repeatable' },
    )
    physical_object: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has physical object', 'label_en': 'Physical Object', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-physical-object', 'graph_id': 'arkumu:hasPhysicalObject', 'property_slug': 'has-physical-object', 'cardinality': 'repeatable' },
    )
    information_storage_medium: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has information storage medium', 'label_en': 'Information Storage Medium', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-information-storage-medium', 'graph_id': 'arkumu:hasInformationStorageMedium', 'property_slug': 'has-information-storage-medium', 'cardinality': 'repeatable' },
    )
    digital_object: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has digital object', 'label_en': 'Digital Object', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-digital-object', 'graph_id': 'arkumu:hasDigitalObject', 'property_slug': 'has-digital-object', 'cardinality': 'repeatable' },
    )
    wikidata_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has Wikidata ID', 'label_en': 'Wikidata ID', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-wikidata-id', 'graph_id': 'arkumu:hasWikidataId', 'property_slug': 'has-wikidata-id', 'cardinality': 'repeatable' },
    )
    gnd_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has GND ID', 'label_en': 'GND ID', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-gnd-id', 'graph_id': 'arkumu:hasGndId', 'property_slug': 'has-gnd-id', 'cardinality': 'repeatable' },
    )
    viaf_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has VIAF ID', 'label_en': 'VIAF ID', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-viaf-id', 'graph_id': 'arkumu:hasViafId', 'property_slug': 'has-viaf-id', 'cardinality': 'repeatable' },
    )
    dataset_id_at_depositor: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has dataset ID at depositor', 'label_en': 'Dataset ID at Depositor', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-dataset-id-at-depositor', 'graph_id': 'arkumu:hasDatasetIdAtDepositor', 'property_slug': 'has-dataset-id-at-depositor', 'cardinality': 'repeatable' },
    )
    organisational_unit: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has depositor', 'label_en': 'Organisational Unit', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-depositor', 'graph_id': 'arkumu:hasDepositor', 'property_slug': 'has-depositor', 'cardinality': 'repeatable' },
    )
    dataset_creation_date_at_depositor: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has dataset creation date at depositor', 'label_en': 'Dataset Creation Date at Depositor', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-dataset-creation-date-at-depositor', 'graph_id': 'arkumu:hasDatasetCreationDateAtDepositor', 'property_slug': 'has-dataset-creation-date-at-depositor', 'cardinality': 'repeatable' },
    )
    dataset_last_modification_date_at_depositor: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has dataset last modification date at depositor', 'label_en': 'Dataset Last Modification Date at Depositor', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-dataset-last-modification-date-at-depositor', 'graph_id': 'arkumu:hasDatasetLastModificationDateAtDepositor', 'property_slug': 'has-dataset-last-modification-date-at-depositor', 'cardinality': 'repeatable' },
    )

@dataclass
class EventDescription(ArkumuEntity):
    """EN: A text describing what happened during an Event, or contains additional information to the Event in question. These can be texts written by the artists themselves or by a third person.
DE: Ein Text, der beschreibt, was während eines Ereignisses passiert ist oder der zusätzliche Informationen zu dem betreffenden Ereignis enthält. Dabei kann es sich um Texte handeln, die von den Künstlern selbst oder von einer dritten Person verfasst wurden."""
    description_text: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has description text', 'label_en': 'Description Text', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-description-text', 'graph_id': 'arkumu:hasDescriptionText', 'property_slug': 'has-description-text', 'cardinality': 'repeatable' },
    )
    sorting_number: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has sorting number', 'label_en': 'Sorting Number', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-sorting-number', 'graph_id': 'arkumu:hasSortingNumber', 'property_slug': 'has-sorting-number', 'cardinality': 'repeatable' },
    )

@dataclass
class EventType(ArkumuEntity):
    """EN: An Event Type categorises an Event with a controlled vocabulary.
DE: Ein Ereignistyp kategorisiert ein Ereignis mit Hilfe eines kontrollierten Vokabulars."""
    german_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german name', 'label_en': 'German Name', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-german-name', 'graph_id': 'arkumu:hasGermanName', 'property_slug': 'has-german-name', 'cardinality': 'repeatable' },
    )
    english_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english name', 'label_en': 'English Name', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-english-name', 'graph_id': 'arkumu:hasEnglishName', 'property_slug': 'has-english-name', 'cardinality': 'repeatable' },
    )
    german_synonyms: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german synonyms', 'label_en': 'German Synonyms', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-german-synonyms', 'graph_id': 'arkumu:hasGermanSynonyms', 'property_slug': 'has-german-synonyms', 'cardinality': 'repeatable' },
    )
    english_synonyms: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english synonyms', 'label_en': 'English Synonyms', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-english-synonyms', 'graph_id': 'arkumu:hasEnglishSynonyms', 'property_slug': 'has-english-synonyms', 'cardinality': 'repeatable' },
    )
    wikidata_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has Wikidata ID', 'label_en': 'Wikidata ID', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-wikidata-id', 'graph_id': 'arkumu:hasWikidataId', 'property_slug': 'has-wikidata-id', 'cardinality': 'repeatable' },
    )
    gnd_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has GND ID', 'label_en': 'GND ID', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-gnd-id', 'graph_id': 'arkumu:hasGndId', 'property_slug': 'has-gnd-id', 'cardinality': 'repeatable' },
    )
    aat_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has AAT ID', 'label_en': 'AAT ID', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-aat-id', 'graph_id': 'arkumu:hasAatId', 'property_slug': 'has-aat-id', 'cardinality': 'repeatable' },
    )
    lido_terminology_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has LIDO Terminology ID', 'label_en': 'LIDO Terminology ID', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-lido-terminology-id', 'graph_id': 'arkumu:hasLidoTerminologyId', 'property_slug': 'has-lido-terminology-id', 'cardinality': 'repeatable' },
    )

@dataclass
class ExistingLicenseAgreement(ArkumuEntity):
    """EN: An already existing standard license form for a project in use at one of the depositing universities.
DE: Ein bereits bestehender, standardisierter Lizenzvertrag für ein Projekt, der an einer der einreichenden Universitäten verwendet wird."""
    german_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german name', 'label_en': 'German Name', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-german-name', 'graph_id': 'arkumu:hasGermanName', 'property_slug': 'has-german-name', 'cardinality': 'repeatable' },
    )
    english_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english name', 'label_en': 'English Name', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-english-name', 'graph_id': 'arkumu:hasEnglishName', 'property_slug': 'has-english-name', 'cardinality': 'repeatable' },
    )
    depositing_university: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has accountable university', 'label_en': 'Depositing University', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-accountable-university', 'graph_id': 'arkumu:hasAccountableUniversity', 'property_slug': 'has-accountable-university', 'cardinality': 'repeatable' },
    )
    german_wording: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german wording', 'label_en': 'German Wording', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-german-wording', 'graph_id': 'arkumu:hasGermanWording', 'property_slug': 'has-german-wording', 'cardinality': 'repeatable' },
    )
    english_wording: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english wording', 'label_en': 'English Wording', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-english-wording', 'graph_id': 'arkumu:hasEnglishWording', 'property_slug': 'has-english-wording', 'cardinality': 'repeatable' },
    )
    pdf: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has pdf', 'label_en': 'PDF', 'source_de_name': 'has pdf', 'label_de': 'PDF', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-pdf', 'graph_id': 'arkumu:hasPdf', 'property_slug': 'has-pdf', 'cardinality': 'repeatable' },
    )
    uri: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has uri', 'label_en': 'URI', 'source_de_name': 'has uri', 'label_de': 'URI', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-uri', 'graph_id': 'arkumu:hasUri', 'property_slug': 'has-uri', 'cardinality': 'repeatable' },
    )

@dataclass
class InformationStorageMedium(ArkumuEntity):
    """EN: Special type of Physical Object on which data can be saved or extracted from. Synonyms: Storage Medium, Recording Medium, Data Carrier.
DE: Besondere Art eines Physischen Objekts, auf dem Daten gespeichert können. Synonyme: Speichermedium, Aufzeichnungsmedium, Datenträger, Trägermedium."""
    german_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german name', 'label_en': 'German Name', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-german-name', 'graph_id': 'arkumu:hasGermanName', 'property_slug': 'has-german-name', 'cardinality': 'repeatable' },
    )
    english_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english name', 'label_en': 'English Name', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-english-name', 'graph_id': 'arkumu:hasEnglishName', 'property_slug': 'has-english-name', 'cardinality': 'repeatable' },
    )
    label: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has label', 'label_en': 'Label', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-label', 'graph_id': 'arkumu:hasLabel', 'property_slug': 'has-label', 'cardinality': 'repeatable' },
    )
    information_storage_medium_type: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has information storage medium type', 'label_en': 'Information Storage Medium Type', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-information-storage-medium-type', 'graph_id': 'arkumu:hasInformationStorageMediumType', 'property_slug': 'has-information-storage-medium-type', 'cardinality': 'repeatable' },
    )
    product_id_value: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has product ID', 'label_en': 'Product ID Value', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-product-id', 'graph_id': 'arkumu:hasProductId', 'property_slug': 'has-product-id', 'cardinality': 'repeatable' },
    )
    external_inventory_number: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has external inventory number', 'label_en': 'External Inventory Number', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-external-inventory-number', 'graph_id': 'arkumu:hasExternalInventoryNumber', 'property_slug': 'has-external-inventory-number', 'cardinality': 'repeatable' },
    )
    wikidata_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has Wikidata ID', 'label_en': 'Wikidata ID', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-wikidata-id', 'graph_id': 'arkumu:hasWikidataId', 'property_slug': 'has-wikidata-id', 'cardinality': 'repeatable' },
    )
    gnd_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has GND ID', 'label_en': 'GND ID', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-gnd-id', 'graph_id': 'arkumu:hasGndId', 'property_slug': 'has-gnd-id', 'cardinality': 'repeatable' },
    )
    place: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has depository', 'label_en': 'Place', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-depository', 'graph_id': 'arkumu:hasDepository', 'property_slug': 'has-depository', 'cardinality': 'repeatable' },
    )
    actor: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has owner', 'label_en': 'Actor', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-owner', 'graph_id': 'arkumu:hasOwner', 'property_slug': 'has-owner', 'cardinality': 'repeatable' },
    )
    actor_2: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has legal rights holder', 'label_en': 'Actor', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-legal-rights-holder', 'graph_id': 'arkumu:hasLegalRightsHolder', 'property_slug': 'has-legal-rights-holder', 'cardinality': 'repeatable' },
    )
    provenance: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has provenance', 'label_en': 'Provenance', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-provenance', 'graph_id': 'arkumu:hasProvenance', 'property_slug': 'has-provenance', 'cardinality': 'repeatable' },
    )
    german_description: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german description', 'label_en': 'German Description', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-german-description', 'graph_id': 'arkumu:hasGermanDescription', 'property_slug': 'has-german-description', 'cardinality': 'repeatable' },
    )
    english_description: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english description', 'label_en': 'English Description', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-english-description', 'graph_id': 'arkumu:hasEnglishDescription', 'property_slug': 'has-english-description', 'cardinality': 'repeatable' },
    )
    german_commentary: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german commentary', 'label_en': 'German Commentary', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-german-commentary', 'graph_id': 'arkumu:hasGermanCommentary', 'property_slug': 'has-german-commentary', 'cardinality': 'repeatable' },
    )
    english_commentary: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english commentary', 'label_en': 'English Commentary', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-english-commentary', 'graph_id': 'arkumu:hasEnglishCommentary', 'property_slug': 'has-english-commentary', 'cardinality': 'repeatable' },
    )
    internal_commentary: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has internal commentary', 'label_en': 'Internal Commentary', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-internal-commentary', 'graph_id': 'arkumu:hasInternalCommentary', 'property_slug': 'has-internal-commentary', 'cardinality': 'repeatable' },
    )
    material_keyword: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has material keyword', 'label_en': 'Material Keyword', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-material-keyword', 'graph_id': 'arkumu:hasMaterialKeyword', 'property_slug': 'has-material-keyword', 'cardinality': 'repeatable' },
    )
    dimensions: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has dimensions', 'label_en': 'Dimensions', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-dimensions', 'graph_id': 'arkumu:hasDimensions', 'property_slug': 'has-dimensions', 'cardinality': 'repeatable' },
    )
    condition_state_german: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has condition state (german)', 'label_en': 'Condition State (German)', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-condition-state-german', 'graph_id': 'arkumu:hasConditionStateGerman', 'property_slug': 'has-condition-state-german', 'cardinality': 'repeatable' },
    )
    condition_state_english: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has condition state (english)', 'label_en': 'Condition State (English)', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-condition-state-english', 'graph_id': 'arkumu:hasConditionStateEnglish', 'property_slug': 'has-condition-state-english', 'cardinality': 'repeatable' },
    )
    compilation: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'is compilation', 'label_en': 'Compilation', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#is-compilation', 'graph_id': 'arkumu:isCompilation', 'property_slug': 'is-compilation', 'cardinality': 'repeatable' },
    )
    compilation_title: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has compilation title', 'label_en': 'Compilation Title', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-compilation-title', 'graph_id': 'arkumu:hasCompilationTitle', 'property_slug': 'has-compilation-title', 'cardinality': 'repeatable' },
    )
    compilation_series_number: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has compilation series number', 'label_en': 'Compilation Series Number', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-compilation-series-number', 'graph_id': 'arkumu:hasCompilationSeriesNumber', 'property_slug': 'has-compilation-series-number', 'cardinality': 'repeatable' },
    )
    original_language: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has original language', 'label_en': 'Original Language', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-original-language', 'graph_id': 'arkumu:hasOriginalLanguage', 'property_slug': 'has-original-language', 'cardinality': 'repeatable' },
    )
    subtitle_language: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has subtitle language', 'label_en': 'Subtitle Language', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-subtitle-language', 'graph_id': 'arkumu:hasSubtitleLanguage', 'property_slug': 'has-subtitle-language', 'cardinality': 'repeatable' },
    )
    language_version: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has language version', 'label_en': 'Language Version', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-language-version', 'graph_id': 'arkumu:hasLanguageVersion', 'property_slug': 'has-language-version', 'cardinality': 'repeatable' },
    )

@dataclass
class InformationStorageMediumType(ArkumuEntity):
    """EN: An Information Storage Medium Type categorises an Information Storage medium with a controlled vocabulary.
DE: Ein Informationsträgertyp kategorisiert einen Informationsträger mit Hilfe eines kontrollierten Vokabulars."""
    german_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german name', 'label_en': 'German Name', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-german-name', 'graph_id': 'arkumu:hasGermanName', 'property_slug': 'has-german-name', 'cardinality': 'repeatable' },
    )
    english_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english name', 'label_en': 'English Name', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-english-name', 'graph_id': 'arkumu:hasEnglishName', 'property_slug': 'has-english-name', 'cardinality': 'repeatable' },
    )
    german_synonyms: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german synonyms', 'label_en': 'German Synonyms', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-german-synonyms', 'graph_id': 'arkumu:hasGermanSynonyms', 'property_slug': 'has-german-synonyms', 'cardinality': 'repeatable' },
    )
    english_synonyms: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english synonyms', 'label_en': 'English Synonyms', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-english-synonyms', 'graph_id': 'arkumu:hasEnglishSynonyms', 'property_slug': 'has-english-synonyms', 'cardinality': 'repeatable' },
    )
    wikidata_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has Wikidata ID', 'label_en': 'Wikidata ID', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-wikidata-id', 'graph_id': 'arkumu:hasWikidataId', 'property_slug': 'has-wikidata-id', 'cardinality': 'repeatable' },
    )
    gnd_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has GND ID', 'label_en': 'GND ID', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-gnd-id', 'graph_id': 'arkumu:hasGndId', 'property_slug': 'has-gnd-id', 'cardinality': 'repeatable' },
    )
    aat_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has AAT ID', 'label_en': 'AAT ID', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-aat-id', 'graph_id': 'arkumu:hasAatId', 'property_slug': 'has-aat-id', 'cardinality': 'repeatable' },
    )
    pbcore_link: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has PBCore link', 'label_en': 'PBCore Link', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-pbcore-link', 'graph_id': 'arkumu:hasPbcoreLink', 'property_slug': 'has-pbcore-link', 'cardinality': 'repeatable' },
    )
    information_storage_medium_type: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has broader information storage medium type', 'label_en': 'Information Storage Medium Type', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-broader-information-storage-medium-type', 'graph_id': 'arkumu:hasBroaderInformationStorageMediumType', 'property_slug': 'has-broader-information-storage-medium-type', 'cardinality': 'repeatable' },
    )

@dataclass
class Keyword(ArkumuEntity):
    """EN: A metadata entry from the controlled vocabulary of Wikidata.
DE: Ein Metadaten-Eintrag aus dem kontrollierten Vokabular von Wikidata."""
    german_wikidata_label: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german wikidata label', 'label_en': 'German Wikidata Label', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-german-wikidata-label', 'graph_id': 'arkumu:hasGermanWikidataLabel', 'property_slug': 'has-german-wikidata-label', 'cardinality': 'repeatable' },
    )
    english_wikidata_label: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english wikidata label', 'label_en': 'English Wikidata Label', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-english-wikidata-label', 'graph_id': 'arkumu:hasEnglishWikidataLabel', 'property_slug': 'has-english-wikidata-label', 'cardinality': 'repeatable' },
    )
    german_wikidata_synonym: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german wikidata synonym', 'label_en': 'German Wikidata Synonym', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-german-wikidata-synonym', 'graph_id': 'arkumu:hasGermanWikidataSynonym', 'property_slug': 'has-german-wikidata-synonym', 'cardinality': 'repeatable' },
    )
    english_wikidata_synonym: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english wikidata synonym', 'label_en': 'English Wikidata Synonym', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-english-wikidata-synonym', 'graph_id': 'arkumu:hasEnglishWikidataSynonym', 'property_slug': 'has-english-wikidata-synonym', 'cardinality': 'repeatable' },
    )
    german_wikidata_description: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german wikidata description', 'label_en': 'German Wikidata Description', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-german-wikidata-description', 'graph_id': 'arkumu:hasGermanWikidataDescription', 'property_slug': 'has-german-wikidata-description', 'cardinality': 'repeatable' },
    )
    german_wikidata_description_2: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german wikidata description', 'label_en': 'German Wikidata Description', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-german-wikidata-description', 'graph_id': 'arkumu:hasGermanWikidataDescription', 'property_slug': 'has-german-wikidata-description', 'cardinality': 'repeatable' },
    )
    wikidata_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has Wikidata ID', 'label_en': 'Wikidata ID', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-wikidata-id', 'graph_id': 'arkumu:hasWikidataId', 'property_slug': 'has-wikidata-id', 'cardinality': 'repeatable' },
    )
    gnd_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has GND ID', 'label_en': 'GND ID', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-gnd-id', 'graph_id': 'arkumu:hasGndId', 'property_slug': 'has-gnd-id', 'cardinality': 'repeatable' },
    )

@dataclass
class Language(ArkumuEntity):
    """EN: A language defined by the ISO 639-2 standard. This standard was chosen to be compatible with all libraries.
DE: Eine Sprache, die durch die Norm ISO 639-2 definiert ist. Dieser Standard wurde gewählt, um mit allen Bibliotheken kompatibel zu sein."""
    german_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german name', 'label_en': 'German Name', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-german-name', 'graph_id': 'arkumu:hasGermanName', 'property_slug': 'has-german-name', 'cardinality': 'repeatable' },
    )
    english_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english name', 'label_en': 'English Name', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-english-name', 'graph_id': 'arkumu:hasEnglishName', 'property_slug': 'has-english-name', 'cardinality': 'repeatable' },
    )
    iso_639_2_b_code: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has ISO 639-2(B) code', 'label_en': 'ISO 639-2(B) Code', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-iso-639-2b-code', 'graph_id': 'arkumu:hasIso639-2-B-Code', 'property_slug': 'has-iso-639-2b-code', 'cardinality': 'repeatable' },
    )
    iso_639_2_t_code: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has ISO 639-2(T) code', 'label_en': 'ISO 639-2(T) Code', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-iso-639-2t-code', 'graph_id': 'hasIso639-2-T-Code', 'property_slug': 'has-iso-639-2t-code', 'cardinality': 'repeatable' },
    )
    iso_639_1_code: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has ISO 639-1 code', 'label_en': 'ISO 639-1 Code', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-iso-639-1-code', 'graph_id': 'arkumu:hasIso639-1-Code', 'property_slug': 'has-iso-639-1-code', 'cardinality': 'repeatable' },
    )

@dataclass
class OrganisationalUnit(ArkumuEntity):
    """EN: A department, an institute, a study programme, or an artistic/scientific facility.
DE: Ein Fachbereich, Institut, ein Studiengang oder eine künstlerisch/wissenschaftliche Einrichtung."""
    german_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german name', 'label_en': 'German Name', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-german-name', 'graph_id': 'arkumu:hasGermanName', 'property_slug': 'has-german-name', 'cardinality': 'repeatable' },
    )
    english_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english name', 'label_en': 'English Name', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-english-name', 'graph_id': 'arkumu:hasEnglishName', 'property_slug': 'has-english-name', 'cardinality': 'repeatable' },
    )
    german_description: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german description', 'label_en': 'German Description', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-german-description', 'graph_id': 'arkumu:hasGermanDescription', 'property_slug': 'has-german-description', 'cardinality': 'repeatable' },
    )
    english_description: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english description', 'label_en': 'English Description', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-english-description', 'graph_id': 'arkumu:hasEnglishDescription', 'property_slug': 'has-english-description', 'cardinality': 'repeatable' },
    )

@dataclass
class Place(ArkumuEntity):
    """EN: A place metadata entry from the controlled vocabulary of Wikidata. Only "real" places are acceptable, i.e. they must be identifiable with geolocation coordinates.
DE: Ein Ort-Metadaten-Eintrag aus dem kontrollierten Vokabular von Wikidata. Nur "reale" Orte sind erlaubt, d.h. sie müssen mit Geokoordinaten identifierbar sein."""
    german_wikidata_label: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german wikidata label', 'label_en': 'German Wikidata Label', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-german-wikidata-label', 'graph_id': 'arkumu:hasGermanWikidataLabel', 'property_slug': 'has-german-wikidata-label', 'cardinality': 'repeatable' },
    )
    english_wikidata_label: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english wikidata label', 'label_en': 'English Wikidata Label', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-english-wikidata-label', 'graph_id': 'arkumu:hasEnglishWikidataLabel', 'property_slug': 'has-english-wikidata-label', 'cardinality': 'repeatable' },
    )
    place_type: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has place type', 'label_en': 'Place Type', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-place-type', 'graph_id': 'arkumu:hasPlaceType', 'property_slug': 'has-place-type', 'cardinality': 'repeatable' },
    )
    wikidata_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has Wikidata ID', 'label_en': 'Wikidata ID', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-wikidata-id', 'graph_id': 'arkumu:hasWikidataId', 'property_slug': 'has-wikidata-id', 'cardinality': 'repeatable' },
    )
    gnd_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has GND ID', 'label_en': 'GND ID', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-gnd-id', 'graph_id': 'arkumu:hasGndId', 'property_slug': 'has-gnd-id', 'cardinality': 'repeatable' },
    )
    viaf_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has VIAF ID', 'label_en': 'VIAF ID', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-viaf-id', 'graph_id': 'arkumu:hasViafId', 'property_slug': 'has-viaf-id', 'cardinality': 'repeatable' },
    )
    longitude: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has longitude', 'label_en': 'Longitude', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-longitude', 'graph_id': 'arkumu:hasLongitude', 'property_slug': 'has-longitude', 'cardinality': 'repeatable' },
    )
    latitude: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has latitude', 'label_en': 'Latitude', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-latitude', 'graph_id': 'arkumu:hasLatitude', 'property_slug': 'has-latitude', 'cardinality': 'repeatable' },
    )
    place: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has broader place', 'label_en': 'Place', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-broader-place', 'graph_id': 'arkumu:hasBroaderPlace', 'property_slug': 'has-broader-place', 'cardinality': 'repeatable' },
    )

@dataclass
class PhyiscalObject(ArkumuEntity):
    """EN: Ein physisch abgrenzbares Objekt, ein Teil eines solchen oder ein Material, das in einem Ereignis entstanden oder verwendet wurde.
DE: A physically delineated object, a part of such, or a material that was created or used in an Event."""
    german_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german name', 'label_en': 'German Name', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-german-name', 'graph_id': 'arkumu:hasGermanName', 'property_slug': 'has-german-name', 'cardinality': 'repeatable' },
    )
    english_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english name', 'label_en': 'English Name', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-english-name', 'graph_id': 'arkumu:hasEnglishName', 'property_slug': 'has-english-name', 'cardinality': 'repeatable' },
    )
    external_inventory_number: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has external inventory number', 'label_en': 'External Inventory Number', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-external-inventory-number', 'graph_id': 'arkumu:hasExternalInventoryNumber', 'property_slug': 'has-external-inventory-number', 'cardinality': 'repeatable' },
    )
    place: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has depository', 'label_en': 'Place', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-depository', 'graph_id': 'arkumu:hasDepository', 'property_slug': 'has-depository', 'cardinality': 'repeatable' },
    )
    actor: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has owner', 'label_en': 'Actor', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-owner', 'graph_id': 'arkumu:hasOwner', 'property_slug': 'has-owner', 'cardinality': 'repeatable' },
    )
    actor_2: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has legal rights holder', 'label_en': 'Actor', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-legal-rights-holder', 'graph_id': 'arkumu:hasLegalRightsHolder', 'property_slug': 'has-legal-rights-holder', 'cardinality': 'repeatable' },
    )
    provenance: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has provenance', 'label_en': 'Provenance', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-provenance', 'graph_id': 'arkumu:hasProvenance', 'property_slug': 'has-provenance', 'cardinality': 'repeatable' },
    )
    german_description: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german description', 'label_en': 'German Description', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-german-description', 'graph_id': 'arkumu:hasGermanDescription', 'property_slug': 'has-german-description', 'cardinality': 'repeatable' },
    )
    english_description: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english description', 'label_en': 'English Description', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-english-description', 'graph_id': 'arkumu:hasEnglishDescription', 'property_slug': 'has-english-description', 'cardinality': 'repeatable' },
    )
    german_commentary: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german commentary', 'label_en': 'German Commentary', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-german-commentary', 'graph_id': 'arkumu:hasGermanCommentary', 'property_slug': 'has-german-commentary', 'cardinality': 'repeatable' },
    )
    english_commentary: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english commentary', 'label_en': 'English Commentary', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-english-commentary', 'graph_id': 'arkumu:hasEnglishCommentary', 'property_slug': 'has-english-commentary', 'cardinality': 'repeatable' },
    )
    internal_commentary: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has internal commentary', 'label_en': 'Internal Commentary', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-internal-commentary', 'graph_id': 'arkumu:hasInternalCommentary', 'property_slug': 'has-internal-commentary', 'cardinality': 'repeatable' },
    )
    classifying_keyword: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has classifying keyword', 'label_en': 'Classifying Keyword', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-classifying-keyword', 'graph_id': 'arkumu:hasClassifyingKeyword', 'property_slug': 'has-classifying-keyword', 'cardinality': 'repeatable' },
    )
    material_keyword: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has material keyword', 'label_en': 'Material Keyword', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-material-keyword', 'graph_id': 'arkumu:hasMaterialKeyword', 'property_slug': 'has-material-keyword', 'cardinality': 'repeatable' },
    )
    technique_keyword: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has technique keyword', 'label_en': 'Technique Keyword', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-technique-keyword', 'graph_id': 'arkumu:hasTechniqueKeyword', 'property_slug': 'has-technique-keyword', 'cardinality': 'repeatable' },
    )
    german_technique_commentary: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german technique commentary', 'label_en': 'German Technique Commentary', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-german-technique-commentary', 'graph_id': 'arkumu:hasGermanTechniqueCommentary', 'property_slug': 'has-german-technique-commentary', 'cardinality': 'repeatable' },
    )
    english_technique_commentary: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english technique commentary', 'label_en': 'English Technique Commentary', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-english-technique-commentary', 'graph_id': 'arkumu:hasEnglishTechniqueCommentary', 'property_slug': 'has-english-technique-commentary', 'cardinality': 'repeatable' },
    )
    dimensions: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has dimensions', 'label_en': 'Dimensions', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-dimensions', 'graph_id': 'arkumu:hasDimensions', 'property_slug': 'has-dimensions', 'cardinality': 'repeatable' },
    )
    condition_state_german: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has condition state (german)', 'label_en': 'Condition State (German)', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-condition-state-german', 'graph_id': 'arkumu:hasConditionStateGerman', 'property_slug': 'has-condition-state-german', 'cardinality': 'repeatable' },
    )
    condition_state_english: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has condition state (english)', 'label_en': 'Condition State (English)', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-condition-state-english', 'graph_id': 'arkumu:hasConditionStateEnglish', 'property_slug': 'has-condition-state-english', 'cardinality': 'repeatable' },
    )

@dataclass
class Project(ArkumuEntity):
    """EN: A Project is dataset record that is describing art and things related to art, as well as holding its current legal and usage rights status of the intellectual property. A Project is the central cataloguing unit of arkumu.nrw.
DE: Ein Projekt ist ein Datensatz, der Kunst und kunstbezogene Dinge beschreibt sowie den aktuellen Rechts- und Nutzungsrechtsstatus dieses geistigen Eigentums enthält. Ein Projekt ist die zentrale Verzeichnungseinheit von arkumu.nrw."""
    preferred_title: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has preferred title', 'label_en': 'Preferred Title', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-preferred-title', 'graph_id': 'arkumu:hasPreferredTitle', 'property_slug': 'has-preferred-title', 'cardinality': 'repeatable' },
    )
    preferred_subtitle: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has preferred subtitle', 'label_en': 'Preferred Subtitle', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-preferred-subtitle', 'graph_id': 'arkumu:hasPreferredSubtitle', 'property_slug': 'has-preferred-subtitle', 'cardinality': 'repeatable' },
    )
    alternative_title_set: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has alternative title set', 'label_en': 'Alternative Title Set', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-alternative-title-set', 'graph_id': 'arkumu:hasAlternativeTitleSet', 'property_slug': 'has-alternative-title-set', 'cardinality': 'repeatable' },
    )
    depositing_university: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has depositing university', 'label_en': 'Depositing University', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-depositing-university', 'graph_id': 'arkumu:hasDepositingUniversity', 'property_slug': 'has-depositing-university', 'cardinality': 'repeatable' },
    )
    organisational_unit: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has organisational unit', 'label_en': 'Organisational Unit', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-organisational-unit', 'graph_id': 'arkumu:hasOrganisationalUnit', 'property_slug': 'has-organisational-unit', 'cardinality': 'repeatable' },
    )
    project_type: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has project type', 'label_en': 'Project Type', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-project-type', 'graph_id': 'arkumu:hasProjectType', 'property_slug': 'has-project-type', 'cardinality': 'repeatable', 'vocabulary': 'project-types' },
    )
    project_category: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has project category', 'label_en': 'Project Category', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-project-category', 'graph_id': 'arkumu:hasProjectCategory', 'property_slug': 'has-project-category', 'cardinality': 'repeatable' },
    )
    keyword: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has keyword', 'label_en': 'Keyword', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-keyword', 'graph_id': 'arkumu:hasKeyword', 'property_slug': 'has-keyword', 'cardinality': 'repeatable' },
    )
    project_description: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has project description', 'label_en': 'Project Description', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-project-description', 'graph_id': 'arkumu:hasProjectDescription', 'property_slug': 'has-project-description', 'cardinality': 'repeatable' },
    )
    german_commentary: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german commentary', 'label_en': 'German Commentary', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-german-commentary', 'graph_id': 'arkumu:hasGermanCommentary', 'property_slug': 'has-german-commentary', 'cardinality': 'repeatable' },
    )
    english_commentary: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english commentary', 'label_en': 'English Commentary', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-english-commentary', 'graph_id': 'arkumu:hasEnglishCommentary', 'property_slug': 'has-english-commentary', 'cardinality': 'repeatable' },
    )
    internal_commentary: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has internal commentary', 'label_en': 'Internal Commentary', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-internal-commentary', 'graph_id': 'arkumu:hasInternalCommentary', 'property_slug': 'has-internal-commentary', 'cardinality': 'repeatable' },
    )
    event: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has event', 'label_en': 'Event', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-event', 'graph_id': 'arkumu:hasEvent', 'property_slug': 'has-event', 'cardinality': 'repeatable' },
    )
    project_property: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has project property', 'label_en': 'Project Property', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-project-property', 'graph_id': 'arkumu:hasProjectProperty', 'property_slug': 'has-project-property', 'cardinality': 'repeatable' },
    )
    project: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has related project', 'label_en': 'Project', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-related-project', 'graph_id': 'arkumu:hasRelatedProject', 'property_slug': 'has-related-project', 'cardinality': 'repeatable' },
    )
    arkumu_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has arkumu ID', 'label_en': 'arkumu ID', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-arkumu-id', 'graph_id': 'arkumu:hasArkumuId', 'property_slug': 'has-arkumu-id', 'cardinality': 'repeatable' },
    )
    ark_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has ARK ID', 'label_en': 'ARK ID', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-ark-id', 'graph_id': 'arkumu:hasArkId', 'property_slug': 'has-ark-id', 'cardinality': 'repeatable' },
    )
    id_at_depositor: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has ID at depositor', 'label_en': 'ID at Depositor', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-id-at-depositor', 'graph_id': 'arkumu:hasIdAtDepositor', 'property_slug': 'has-id-at-depositor', 'cardinality': 'repeatable' },
    )
    catalogue_raisonn_reference_number: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has catalogue raisonné reference number', 'label_en': 'Catalogue Raisonné Reference Number', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-catalogue-raisonne-reference-number', 'graph_id': 'arkumu:hasCatalogueRaisonneReferenceNumber', 'property_slug': 'has-catalogue-raisonn-reference-number', 'cardinality': 'repeatable' },
    )
    wikidata_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has Wikidata ID', 'label_en': 'Wikidata ID', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-wikidata-id', 'graph_id': 'arkumu:hasWikidataId', 'property_slug': 'has-wikidata-id', 'cardinality': 'repeatable' },
    )
    gnd_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has GND ID', 'label_en': 'GND ID', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-gnd-id', 'graph_id': 'arkumu:hasGndId', 'property_slug': 'has-gnd-id', 'cardinality': 'repeatable' },
    )
    website: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has website', 'label_en': 'Website', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-website', 'graph_id': 'arkumu:hasWebsite', 'property_slug': 'has-website', 'cardinality': 'repeatable' },
    )
    dataset_id_at_depositor: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has dataset ID at depositor', 'label_en': 'Dataset ID at Depositor', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-dataset-id-at-depositor', 'graph_id': 'arkumu:hasDatasetIdAtDepositor', 'property_slug': 'has-dataset-id-at-depositor', 'cardinality': 'repeatable' },
    )
    organisational_unit_2: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has depositor', 'label_en': 'Organisational Unit', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-depositor', 'graph_id': 'arkumu:hasDepositor', 'property_slug': 'has-depositor', 'cardinality': 'repeatable' },
    )
    dataset_creation_date_at_depositor: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has dataset creation date at depositor', 'label_en': 'Dataset Creation Date at Depositor', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-dataset-creation-date-at-depositor', 'graph_id': 'arkumu:hasDatasetCreationDateAtDepositor', 'property_slug': 'has-dataset-creation-date-at-depositor', 'cardinality': 'repeatable' },
    )
    dataset_last_modification_date_at_depositor: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has dataset last modification date at depositor', 'label_en': 'Dataset Last Modification Date at Depositor', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-dataset-last-modification-date-at-depositor', 'graph_id': 'arkumu:hasDatasetLastModificationDateAtDepositor', 'property_slug': 'has-dataset-last-modification-date-at-depositor', 'cardinality': 'repeatable' },
    )
    rights_status: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has rights status', 'label_en': 'Rights Status', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-rights-status', 'graph_id': 'arkumu:hasRightsStatus', 'property_slug': 'has-rights-status', 'cardinality': 'repeatable' },
    )
    existing_license_agreement: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has existing license agreement', 'label_en': 'Existing License Agreement', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-existing-license-agreement', 'graph_id': 'arkumu:hasExistingLicenseAgreement', 'property_slug': 'has-existing-license-agreement', 'cardinality': 'repeatable' },
    )
    new_arkumu_license_agreement: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has new arkumu license agreement', 'label_en': 'New arkumu License Agreement', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-new-arkumu-license-agreement', 'graph_id': 'arkumu:hasNewArkumuLicenseAgreement', 'property_slug': 'has-new-arkumu-license-agreement', 'cardinality': 'repeatable' },
    )
    additional_rights_document: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has additional rights document', 'label_en': 'Additional Rights Document', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-additional-rights-document', 'graph_id': 'arkumu:hasAdditionalRightsDocument', 'property_slug': 'has-additional-rights-document', 'cardinality': 'repeatable' },
    )
    file_license_document: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has file license document', 'label_en': 'File License Document', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-file-license-document', 'graph_id': 'arkumu:hasFileLicenseDocument', 'property_slug': 'has-file-license-document', 'cardinality': 'repeatable' },
    )

@dataclass
class ProjectCategory(ArkumuEntity):
    """EN: A Project Category typifies a Project, in an artistic sense, with the help of a controlled vocabulary.
DE: Eine Projektkategorie typisiert ein Projekt, in einem künstlerischen Sinne, mit Hilfe eines kontrollierten Vokabulars."""
    german_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german name', 'label_en': 'German Name', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-german-name', 'graph_id': 'arkumu:hasGermanName', 'property_slug': 'has-german-name', 'cardinality': 'repeatable' },
    )
    english_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english name', 'label_en': 'English Name', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-english-name', 'graph_id': 'arkumu:hasEnglishName', 'property_slug': 'has-english-name', 'cardinality': 'repeatable' },
    )
    german_synonyms: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german synonyms', 'label_en': 'German Synonyms', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-german-synonyms', 'graph_id': 'arkumu:hasGermanSynonyms', 'property_slug': 'has-german-synonyms', 'cardinality': 'repeatable' },
    )
    english_synonyms: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english synonyms', 'label_en': 'English Synonyms', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-english-synonyms', 'graph_id': 'arkumu:hasEnglishSynonyms', 'property_slug': 'has-english-synonyms', 'cardinality': 'repeatable' },
    )
    wikidata_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has Wikidata ID', 'label_en': 'Wikidata ID', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-wikidata-id', 'graph_id': 'arkumu:hasWikidataId', 'property_slug': 'has-wikidata-id', 'cardinality': 'repeatable' },
    )
    gnd_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has GND ID', 'label_en': 'GND ID', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-gnd-id', 'graph_id': 'arkumu:hasGndId', 'property_slug': 'has-gnd-id', 'cardinality': 'repeatable' },
    )
    aat_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has AAT ID', 'label_en': 'AAT ID', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-aat-id', 'graph_id': 'arkumu:hasAatId', 'property_slug': 'has-aat-id', 'cardinality': 'repeatable' },
    )
    filmportal_de_category_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has filmportal.de category ID', 'label_en': 'filmportal.de Category ID', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-filmportalde-category-id', 'graph_id': 'arkumu:hasFilmportalDeCategoryId', 'property_slug': 'has-filmportal-de-category-id', 'cardinality': 'repeatable' },
    )
    project_category: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has broader project category', 'label_en': 'Project Category', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-broader-project-category', 'graph_id': 'arkumu:hasBroaderProjectCategory', 'property_slug': 'has-broader-project-category', 'cardinality': 'repeatable' },
    )

@dataclass
class ProjectDescription(ArkumuEntity):
    """EN: A text describing the content of the Project, or what the Project in question is. These can be texts written by the artists themselves or written by a third person.
DE: Ein Text, der den Inhalt des Projekts beschreibt oder was das Projekt ist. Dabei kann es sich um Texte handeln, die von den Künstler:innen selbst oder von einer dritten Person verfasst wurden."""
    description_text: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has description text', 'label_en': 'Description Text', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-description-text', 'graph_id': 'arkumu:hasDescriptionText', 'property_slug': 'has-description-text', 'cardinality': 'repeatable' },
    )
    sorting_number: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has sorting number', 'label_en': 'Sorting Number', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-sorting-number', 'graph_id': 'arkumu:hasSortingNumber', 'property_slug': 'has-sorting-number', 'cardinality': 'repeatable' },
    )

@dataclass
class ProjectType(ArkumuEntity):
    """EN: A Project Type categorises a the academic context of a Project with the help of a controlled vocabulary.
DE: Eine Projektart kategorisiert den akademischen Kontext eines Projekts mit Hilfe eines kontrollierten Vokabulars."""
    german_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german name', 'label_en': 'German Name', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-german-name', 'graph_id': 'arkumu:hasGermanName', 'property_slug': 'has-german-name', 'cardinality': 'repeatable' },
    )
    english_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english name', 'label_en': 'English Name', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-english-name', 'graph_id': 'arkumu:hasEnglishName', 'property_slug': 'has-english-name', 'cardinality': 'repeatable' },
    )
    wikidata_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has Wikidata ID', 'label_en': 'Wikidata ID', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-wikidata-id', 'graph_id': 'arkumu:hasWikidataId', 'property_slug': 'has-wikidata-id', 'cardinality': 'repeatable' },
    )

@dataclass
class Role(ArkumuEntity):
    """EN: An artistic or non-artistic role of a person, a group, or legal entity, either as a global role as profession or activity directly bound to the actor, or situational executed in an Event.
DE: Eine künstlerische oder nicht-künstlerische Rolle einer Person, einer Gruppe oder einer Körperschaft, entweder als globale Rolle, als Beruf oder Tätigkeit, direkt an eine:n Akteur:in gebunden oder situativ ausgeführt in einem Event."""
    german_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german name', 'label_en': 'German Name', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-german-name', 'graph_id': 'arkumu:hasGermanName', 'property_slug': 'has-german-name', 'cardinality': 'repeatable' },
    )
    english_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english name', 'label_en': 'English Name', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-english-name', 'graph_id': 'arkumu:hasEnglishName', 'property_slug': 'has-english-name', 'cardinality': 'repeatable' },
    )
    wikidata_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has Wikidata ID', 'label_en': 'Wikidata ID', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-wikidata-id', 'graph_id': 'arkumu:hasWikidataId', 'property_slug': 'has-wikidata-id', 'cardinality': 'repeatable' },
    )
    gnd_id_male: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has GND ID (male)', 'label_en': 'GND ID (male)', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-gnd-id-male', 'graph_id': 'arkumu:hasGndIdMale', 'property_slug': 'has-gnd-id-male', 'cardinality': 'repeatable' },
    )
    gnd_id_female: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has GND ID (female)', 'label_en': 'GND ID (female)', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-gnd-id-female', 'graph_id': 'arkumu:hasGndIdFemale', 'property_slug': 'has-gnd-id-female', 'cardinality': 'repeatable' },
    )
    gnd_id_group: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has GND ID (group)', 'label_en': 'GND ID (group)', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-gnd-id-group', 'graph_id': 'arkumu:hasGndIdGroup', 'property_slug': 'has-gnd-id-group', 'cardinality': 'repeatable' },
    )
    aat_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has AAT ID', 'label_en': 'AAT ID', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-aat-id', 'graph_id': 'arkumu:hasAatId', 'property_slug': 'has-aat-id', 'cardinality': 'repeatable' },
    )
    role: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has broader role', 'label_en': 'Role', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-broader-role', 'graph_id': 'arkumu:hasBroaderRole', 'property_slug': 'has-broader-role', 'cardinality': 'repeatable' },
    )

@dataclass
class AatId(ArkumuEntity):
    """EN: An identification number for an entry in the "Art & Architecture Thesaurus" of the Getty research Institute; e.g. 300054138.
DE: Eine Identifikatsnummer eines Eintrags im „Art & Architecture Thesaurus“ des Getty Reasearch Institute; z.B. 300054138."""
    pass

@dataclass
class AdditionalRightsDocument(ArkumuEntity):
    """EN: Links to additionally uploaded documents that are relevant to German *Urheberrecht* or German *Leistungsschutzrecht* issues relating to a Project or Events associated with the Project.
DE: Links zu weiteren hochgeladenen Dokumenten, die für urheberrechtliche oder leistungsschutzrechtliche Fragen bezüglich eines Projekts oder den damit, über das Projekt verbundenen, Ereignissen relevant ist."""
    pass

@dataclass
class AlternativeName(ArkumuEntity):
    """EN: An alternative appellation for an Actor.
DE: Eine alternative Bezeichnung für einen/eine Akteur:in."""
    pass

@dataclass
class AlternativeSubtitle(ArkumuEntity):
    """EN: An alternative short, supplementary line of text for a Project, which is linked to it via an Alternative Title Set.
DE: Ein alternative kurze, ergänzende Textzeile für eine Projekt, die über ein Alternatives Titel-Set verbunden wird."""
    language: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has language', 'label_en': 'Language', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-language', 'graph_id': 'arkumu:hasLanguage', 'property_slug': 'has-language', 'cardinality': 'repeatable' },
    )

@dataclass
class AlternativeTitle(ArkumuEntity):
    """EN: An alternative appellation for a Project, which is linked to it via an Alternative Title Set.
DE: Ein alternative Benennung für ein Projekt, die über ein Alternatives Titel-Set verbunden wird."""
    language: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has language', 'label_en': 'Language', 'predicate_uri': 'https://gitlab.git.nrw/arkumu/arkumu-exchange-portal/-/wikis/data-model/classes-and-properties#has-language', 'graph_id': 'arkumu:hasLanguage', 'property_slug': 'has-language', 'cardinality': 'repeatable' },
    )

@dataclass
class Ark(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class ArkumuId(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class AspectRatio(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class BeginningOfActivity(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class CatalogueRaisonnReferenceNumber(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class Checksum(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class ChecksumAtDepositor(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class ClassifyingKeyword(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class Compilation(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class CompilationSeriesNumber(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class CompilationTitle(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class ConditionStateEnglish(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class ConditionStateGerman(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class ContactEMail(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class ContactPhone(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class ContactPostalAddress(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class DatasetCreationDateAtDepositor(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class DatasetIdAtDepositor(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class DatasetLastModificationDateAtDepositor(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class DateOfBirth(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class DateOfDeath(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class DerivateCopyNumber(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class DescriptionText(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class DigitalObjectKeyword(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class Dimensions(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class DroidMetadata(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class DroidPuid(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class EndOfActivity(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class EnglishCommentary(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class EnglishContentDescription(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class EnglishDescription(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class EnglishImageDescription(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class EnglishName(ArkumuEntity):
    """EN: An English appellation of an Event, Actor, or further entity.
DE: Eine englische Benennung eines Ereignis, einer Akteur:in oder eine anderen Entität."""
    pass

@dataclass
class EnglishShortBiography(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class EnglishSynonyms(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class EnglishTechniqueCommentary(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class EnglishWikidataLabel(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class EnglishWikidataSynonym(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class EnglishWording(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class EventBeginning(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class EventEnd(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class EventProperty(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class ExiftoolMetadata(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class ExternalInventoryNumber(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class FileLicenseDocument(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class FileName(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class FilePackage(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class FilePath(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class FileSize(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class FilmportalDeCategoryId(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class FrameRate(ArkumuEntity):
    """EN: Anzahl der Bilder, die pro Sekunde gerendert werden, z. B. 25 fps.
DE: Number of frames rendered per second, e.g. 25 fps."""
    pass

@dataclass
class Gender(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class GenesisType(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class GermanCommentary(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class GermanContentDescription(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class GermanDescription(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class GermanImageDescription(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class GermanName(ArkumuEntity):
    """EN: An German appellation of an Event, Actor, or further entity.
DE: Eine deutsche Benennung eines Ereignis, einer Akteur:in oder eine anderen Entität."""
    pass

@dataclass
class GermanShortBiography(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class GermanSynonyms(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class GermanTechniqueCommentary(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class GermanWikidataDescription(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class GermanWikidataLabel(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class GermanWikidataSynonym(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class GermanWording(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class GndId(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class GndIdFemale(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class GndIdGroup(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class GndIdMale(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class IdAtDepositor(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class InternalCommentary(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class IsArkumuPreview(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class IsPosterImage(ArkumuEntity):
    """EN: 
DE: Eine Bilddatei, die repräsentativ für das ganze Projekt auf der Suchergebnisseite angezeigt wird. Wenn mehrere digitale Objekte eines Projekts Bilder sind, wird eines zum Vorschaubild deklariert."""
    pass

@dataclass
class Iso6391Code(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class Iso6392BCode(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class Iso6392TCode(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class JhoveMetadata(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class JhoveStatus(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class Label(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class LanguageVersion(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class Latitude(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class LccnId(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class LidoTerminologyId(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class Longitude(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class MaterialKeyword(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class MediaType(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class MediainfoMetadata(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class MimeType(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class NewArkumuLicenseAgreement(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class NonPublicName(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class Orcid(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class OriginalLanguage(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class OtherAuthorityId(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class PbcoreLink(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class Pdf(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class PlaceType(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class PrecedingTitle(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class PreferredSubtitle(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class PreferredTitle(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class PreservationType(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class Producer(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class ProductIdValue(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class ProjectProperty(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class Provenance(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class RightsStatus(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class SignificantPropertiesEnglish(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class SignificantPropertiesGerman(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class SortingNumber(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class SubtitleLanguage(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class SystemRequirements(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class TechniqueKeyword(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class TelevisionStandard(ArkumuEntity):
    """EN: Standard for terrestrial television signals, e.g. PAL or NTSC.
DE: Der Standard, nach dem Informationen beim Fernsehen vom Sender zum Empfänger übertragen werden, z. B. PAL oder NTSC."""
    pass

@dataclass
class TrailingTitle(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class Uri(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class ViafId(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class Website(ArkumuEntity):
    """EN: 
DE:"""
    pass

@dataclass
class WikidataId(ArkumuEntity):
    """EN: 
DE:"""
    pass

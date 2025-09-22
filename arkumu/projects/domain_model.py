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
        metadata={ 'source_en_name': 'has german name', 'label_en': 'German Name' },
    )
    english_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english name', 'label_en': 'English Name' },
    )
    alternative_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has alternative name', 'label_en': 'Alternative Name' },
    )
    non_public_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has non-public name', 'label_en': 'Non-public Name' },
    )
    preceding_title: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has preceding title', 'label_en': 'Preceding Title' },
    )
    trailing_title: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has trailing title', 'label_en': 'Trailing Title' },
    )
    gender: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has gender', 'label_en': 'Gender' },
    )
    date_of_birth: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has date of birth', 'label_en': 'Date of Birth' },
    )
    date_of_death: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has date of death', 'label_en': 'Date of Death' },
    )
    beginning_of_activity: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has beginning of activity', 'label_en': 'Beginning of Activity' },
    )
    end_of_activity: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has end of activity', 'label_en': 'End of Activity' },
    )
    place: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has place of birth', 'label_en': 'Place' },
    )
    place_2: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has place of death', 'label_en': 'Place' },
    )
    place_3: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has place of activity', 'label_en': 'Place' },
    )
    place_4: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has place of foundation', 'label_en': 'Place' },
    )
    place_5: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has place of dissolution', 'label_en': 'Place' },
    )
    german_short_biography: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german short biography', 'label_en': 'German Short Biography' },
    )
    english_short_biography: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english short biography', 'label_en': 'English Short Biography' },
    )
    german_commentary: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german commentary', 'label_en': 'German Commentary' },
    )
    english_commentary: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english commentary', 'label_en': 'English Commentary' },
    )
    internal_commentary: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has internal commentary', 'label_en': 'Internal Commentary' },
    )
    role: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has profession or activity', 'label_en': 'Role' },
    )
    orcid: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has ORCID', 'label_en': 'ORCID' },
    )
    wikidata_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has Wikidata ID', 'label_en': 'Wikidata ID' },
    )
    gnd_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has GND ID', 'label_en': 'GND ID' },
    )
    viaf_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has VIAF ID', 'label_en': 'VIAF ID' },
    )
    lccn_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has LCCN ID', 'label_en': 'LCCN ID' },
    )
    other_authority_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has other authority ID', 'label_en': 'Other Authority ID' },
    )
    website: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has website', 'label_en': 'Website' },
    )
    contact_e_mail: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has contact e-mail', 'label_en': 'Contact (E-Mail)' },
    )
    contact_phone: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has contact phone number', 'label_en': 'Contact (Phone)' },
    )
    contact_postal_address: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has contact postal address', 'label_en': 'Contact (Postal Address)' },
    )
    dataset_id_at_depositor: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has dataset ID at depositor', 'label_en': 'Dataset ID at Depositor' },
    )
    organisational_unit: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has depositor', 'label_en': 'Organisational Unit' },
    )
    dataset_creation_date_at_depositor: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has dataset creation date at depositor', 'label_en': 'Dataset Creation Date at Depositor' },
    )
    dataset_last_modification_date_at_depositor: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has dataset last modification date at depositor', 'label_en': 'Dataset Last Modification Date at Depositor' },
    )
    actor: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has related actor', 'label_en': 'Actor' },
    )

@dataclass
class AlternativeTitleSet(ArkumuEntity):
    """EN: Ein Set aus einem möglichen alternativen Titel und einem möglichen alternativen Untertitel.
DE: A set of a possible alternative title and a possible alternative subtitle."""
    alternative_title: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has alternative title', 'label_en': 'Alternative Title' },
    )
    alternative_subtitle: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has alternative subtitle', 'label_en': 'Alternative Subtitle' },
    )

@dataclass
class DepositingUniversity(ArkumuEntity):
    """EN: The university responsible for the data submitted.
DE: Die für die eingelieferten Daten verantwortliche Hochschule."""
    german_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german name', 'label_en': 'German Name' },
    )
    english_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english name', 'label_en': 'English Name' },
    )
    wikidata_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has Wikidata ID', 'label_en': 'Wikidata ID' },
    )
    gnd_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has GND ID', 'label_en': 'GND ID' },
    )

@dataclass
class DigitalObject(ArkumuEntity):
    """EN: A Digital Object is a single file with its corresponding metadata set. Descriptive metadata is data entered by users, technical metadata is automatically read out by software.
DE: Ein Digitales Objekt ist eine einzelne Datei mit dazugehörigen Metadaten. Beschreibene Metadaten werden von Nutzer:innen eingegeben, technische Metadaten werden von Software automatisch ausgelesen."""
    file_path: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has file path', 'label_en': 'File Path' },
    )
    file_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has file name', 'label_en': 'File Name' },
    )
    file_size: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has file size', 'label_en': 'File Size' },
    )
    mime_type: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has MIME type', 'label_en': 'MIME Type' },
    )
    media_type: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has media type', 'label_en': 'Media Type' },
    )
    genesis_type: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has genesis type', 'label_en': 'Genesis Type' },
    )
    file_package: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'is file package', 'label_en': 'File Package' },
    )
    preservation_type: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has preservation type', 'label_en': 'Preservation Type' },
    )
    derivate_copy_number: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has derivate copy number', 'label_en': 'Derivate Copy Number' },
    )
    digital_object_keyword: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has digital object keyword', 'label_en': 'Digital Object Keyword' },
    )
    digital_object_license: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has digital object license', 'label_en': 'Digital Object License' },
    )
    german_content_description: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german content description', 'label_en': 'German Content Description' },
    )
    english_content_description: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english content description', 'label_en': 'English Content Description' },
    )
    german_image_description: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german image description', 'label_en': 'German Image Description' },
    )
    english_image_description: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english image description', 'label_en': 'English Image Description' },
    )
    german_commentary: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german commentary', 'label_en': 'German Commentary' },
    )
    english_commentary: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english commentary', 'label_en': 'English Commentary' },
    )
    internal_commentary: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has internal commentary', 'label_en': 'Internal Commentary' },
    )
    significant_properties_german: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has significant properties (german)', 'label_en': 'Significant Properties (German)' },
    )
    significant_properties_english: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has significant properties (english)', 'label_en': 'Significant Properties (English)' },
    )
    system_requirements: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has system requirements', 'label_en': 'System Requirements' },
    )
    checksum: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has checksum', 'label_en': 'Checksum' },
    )
    checksum_at_depositor: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has checksum at depositor', 'label_en': 'Checksum at Depositor' },
    )
    jhove_status: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has JHOVE status', 'label_en': 'JHOVE Status' },
    )
    droid_puid: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has DROID puid', 'label_en': 'DROID PUID' },
    )
    jhove_metadata: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has JHOVE metadata', 'label_en': 'JHOVE Metadata' },
    )
    droid_metadata: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has DROID metadata', 'label_en': 'DROID Metadata' },
    )
    exiftool_metadata: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has ExifTool metadata', 'label_en': 'ExifTool Metadata' },
    )
    mediainfo_metadata: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has MediaInfo metadata', 'label_en': 'MediaInfo Metadata' },
    )
    dataset_id_at_depositor: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has dataset ID at depositor', 'label_en': 'Dataset ID at Depositor' },
    )
    organisational_unit: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has depositor', 'label_en': 'Organisational Unit' },
    )
    dataset_creation_date_at_depositor: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has dataset creation date at depositor', 'label_en': 'Dataset Creation Date at Depositor' },
    )
    dataset_last_modification_date_at_depositor: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has dataset last modification date at depositor', 'label_en': 'Dataset Last Modification Date at Depositor' },
    )
    is_arkumu_preview: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has is arkumu preview', 'label_en': 'is arkumu Preview' },
    )
    is_poster_image: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has is poster image', 'label_en': 'is Poster Image' },
    )
    television_standard: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has television standard', 'label_en': 'Television Standard' },
    )
    frame_rate: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has frame rate', 'label_en': 'Frame Rate' },
    )
    aspect_ratio: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has aspect ratio', 'label_en': 'Aspect Ratio' },
    )

@dataclass
class EquipmentAndSoftware(ArkumuEntity):
    """EN: Tools and Software that were used during an Event to achieve the result of an activity in question.
DE: Werkzeuge und Software, die während eines Ereignisses verwendet wurden, um das Ergebnis einer bestimmten Aktivität zu erreichen."""
    german_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german name', 'label_en': 'German Name' },
    )
    english_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english name', 'label_en': 'English Name' },
    )
    producer: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has producer', 'label_en': 'Producer' },
    )
    wikidata_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has Wikidata ID', 'label_en': 'Wikidata ID' },
    )
    gnd_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has GND ID', 'label_en': 'GND ID' },
    )
    german_description: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german description', 'label_en': 'German Description' },
    )
    english_description: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english description', 'label_en': 'English Description' },
    )

@dataclass
class EquipmentType(ArkumuEntity):
    """EN: An Equipment Type categorises a piece of equipment or a piece of software using a controlled vocabulary.
DE: Eine Ereignisart kategorisiert eine Stück Equipment oder ein Stück Software mit Hilfe eines kontrollierten Vokabulars."""
    german_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german name', 'label_en': 'German Name' },
    )
    english_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english name', 'label_en': 'English Name' },
    )
    wikidata_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has Wikidata ID', 'label_en': 'Wikidata ID' },
    )
    gnd_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has GND ID', 'label_en': 'GND ID' },
    )
    aat_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has AAT ID', 'label_en': 'AAT ID' },
    )

@dataclass
class Event(ArkumuEntity):
    """EN: Events represent occurrences in the real world that have happened in connection with a Project and its Actors. Events have a temporal beginning and a temporal end and take place in real Places. Abstract places ('on the internet') or fictional places ('Duckburg') need to be recorded as comments. Events are performed or executed by various actors, which can lead to legal ownership. Events manifest themselves or are documented in Digital Objects (files and their metadata).
DE: Ereignisse bilden Geschehnisse in der realen Welt ab, die im Zusammenhang mit einem Projekt und dessen Akteur:innen passiert sind. Ereignisse haben einen zeitlichen Beginn und ein zeitliches Ende und finden an realen Orten statt. Abstrakte Orte ("im Internet") oder fiktive Orte ("Entenhausen") sind als Kommentar zu verzeichnen. Ereignisse werden von verschiedenen Akteur:innen durch- oder aufgeführt, wodurch sich rechtliche Ansprüche ableiten können. Ereignisse manifestieren sich oder werden dokumentiert in Digitalen Objekten (Dateien und ihren Metadaten)."""
    german_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german name', 'label_en': 'German Name' },
    )
    english_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english name', 'label_en': 'English Name' },
    )
    event_type: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has event type', 'label_en': 'Event Type' },
    )
    event_beginning: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has event beginning', 'label_en': 'Event Beginning' },
    )
    event_end: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has event end', 'label_en': 'Event End' },
    )
    place: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has event place', 'label_en': 'Place' },
    )
    event_description: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has event description', 'label_en': 'Event Description' },
    )
    german_commentary: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german commentary', 'label_en': 'German Commentary' },
    )
    english_commentary: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english commentary', 'label_en': 'English Commentary' },
    )
    internal_commentary: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has internal commentary', 'label_en': 'Internal Commentary' },
    )
    event_property: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has event property', 'label_en': 'Event Property' },
    )
    event: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has related event', 'label_en': 'Event' },
    )
    actor: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has actor', 'label_en': 'Actor' },
    )
    equipment_and_software: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has equipment and software', 'label_en': 'Equipment and Software' },
    )
    physical_object: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has physical object', 'label_en': 'Physical Object' },
    )
    information_storage_medium: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has information storage medium', 'label_en': 'Information Storage Medium' },
    )
    digital_object: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has digital object', 'label_en': 'Digital Object' },
    )
    wikidata_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has Wikidata ID', 'label_en': 'Wikidata ID' },
    )
    gnd_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has GND ID', 'label_en': 'GND ID' },
    )
    viaf_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has VIAF ID', 'label_en': 'VIAF ID' },
    )
    dataset_id_at_depositor: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has dataset ID at depositor', 'label_en': 'Dataset ID at Depositor' },
    )
    organisational_unit: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has depositor', 'label_en': 'Organisational Unit' },
    )
    dataset_creation_date_at_depositor: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has dataset creation date at depositor', 'label_en': 'Dataset Creation Date at Depositor' },
    )
    dataset_last_modification_date_at_depositor: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has dataset last modification date at depositor', 'label_en': 'Dataset Last Modification Date at Depositor' },
    )

@dataclass
class EventDescription(ArkumuEntity):
    """EN: A text describing what happened during an Event, or contains additional information to the Event in question. These can be texts written by the artists themselves or by a third person.
DE: Ein Text, der beschreibt, was während eines Ereignisses passiert ist oder der zusätzliche Informationen zu dem betreffenden Ereignis enthält. Dabei kann es sich um Texte handeln, die von den Künstlern selbst oder von einer dritten Person verfasst wurden."""
    description_text: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has description text', 'label_en': 'Description Text' },
    )
    sorting_number: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has sorting number', 'label_en': 'Sorting Number' },
    )

@dataclass
class EventType(ArkumuEntity):
    """EN: An Event Type categorises an Event with a controlled vocabulary.
DE: Ein Ereignistyp kategorisiert ein Ereignis mit Hilfe eines kontrollierten Vokabulars."""
    german_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german name', 'label_en': 'German Name' },
    )
    english_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english name', 'label_en': 'English Name' },
    )
    german_synonyms: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german synonyms', 'label_en': 'German Synonyms' },
    )
    english_synonyms: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english synonyms', 'label_en': 'English Synonyms' },
    )
    wikidata_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has Wikidata ID', 'label_en': 'Wikidata ID' },
    )
    gnd_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has GND ID', 'label_en': 'GND ID' },
    )
    aat_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has AAT ID', 'label_en': 'AAT ID' },
    )
    lido_terminology_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has LIDO Terminology ID', 'label_en': 'LIDO Terminology ID' },
    )

@dataclass
class ExistingLicenseAgreement(ArkumuEntity):
    """EN: An already existing standard license form for a project in use at one of the depositing universities.
DE: Ein bereits bestehender, standardisierter Lizenzvertrag für ein Projekt, der an einer der einreichenden Universitäten verwendet wird."""
    german_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german name', 'label_en': 'German Name' },
    )
    english_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english name', 'label_en': 'English Name' },
    )
    depositing_university: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has accountable university', 'label_en': 'Depositing University' },
    )
    german_wording: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german wording', 'label_en': 'German Wording' },
    )
    english_wording: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english wording', 'label_en': 'English Wording' },
    )
    pdf: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has pdf', 'label_en': 'PDF', 'source_de_name': 'has pdf', 'label_de': 'PDF' },
    )
    uri: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has uri', 'label_en': 'URI', 'source_de_name': 'has uri', 'label_de': 'URI' },
    )

@dataclass
class InformationStorageMedium(ArkumuEntity):
    """EN: Special type of Physical Object on which data can be saved or extracted from. Synonyms: Storage Medium, Recording Medium, Data Carrier.
DE: Besondere Art eines Physischen Objekts, auf dem Daten gespeichert können. Synonyme: Speichermedium, Aufzeichnungsmedium, Datenträger, Trägermedium."""
    german_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german name', 'label_en': 'German Name' },
    )
    english_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english name', 'label_en': 'English Name' },
    )
    label: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has label', 'label_en': 'Label' },
    )
    information_storage_medium_type: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has information storage medium type', 'label_en': 'Information Storage Medium Type' },
    )
    product_id_value: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has product ID', 'label_en': 'Product ID Value' },
    )
    external_inventory_number: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has external inventory number', 'label_en': 'External Inventory Number' },
    )
    wikidata_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has Wikidata ID', 'label_en': 'Wikidata ID' },
    )
    gnd_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has GND ID', 'label_en': 'GND ID' },
    )
    place: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has depository', 'label_en': 'Place' },
    )
    actor: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has owner', 'label_en': 'Actor' },
    )
    actor_2: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has legal rights holder', 'label_en': 'Actor' },
    )
    provenance: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has provenance', 'label_en': 'Provenance' },
    )
    german_description: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german description', 'label_en': 'German Description' },
    )
    english_description: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english description', 'label_en': 'English Description' },
    )
    german_commentary: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german commentary', 'label_en': 'German Commentary' },
    )
    english_commentary: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english commentary', 'label_en': 'English Commentary' },
    )
    internal_commentary: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has internal commentary', 'label_en': 'Internal Commentary' },
    )
    material_keyword: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has material keyword', 'label_en': 'Material Keyword' },
    )
    dimensions: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has dimensions', 'label_en': 'Dimensions' },
    )
    condition_state_german: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has condition state (german)', 'label_en': 'Condition State (German)' },
    )
    condition_state_english: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has condition state (english)', 'label_en': 'Condition State (English)' },
    )
    compilation: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'is compilation', 'label_en': 'Compilation' },
    )
    compilation_title: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has compilation title', 'label_en': 'Compilation Title' },
    )
    compilation_series_number: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has compilation series number', 'label_en': 'Compilation Series Number' },
    )
    original_language: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has original language', 'label_en': 'Original Language' },
    )
    subtitle_language: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has subtitle language', 'label_en': 'Subtitle Language' },
    )
    language_version: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has language version', 'label_en': 'Language Version' },
    )

@dataclass
class InformationStorageMediumType(ArkumuEntity):
    """EN: An Information Storage Medium Type categorises an Information Storage medium with a controlled vocabulary.
DE: Ein Informationsträgertyp kategorisiert einen Informationsträger mit Hilfe eines kontrollierten Vokabulars."""
    german_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german name', 'label_en': 'German Name' },
    )
    english_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english name', 'label_en': 'English Name' },
    )
    german_synonyms: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german synonyms', 'label_en': 'German Synonyms' },
    )
    english_synonyms: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english synonyms', 'label_en': 'English Synonyms' },
    )
    wikidata_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has Wikidata ID', 'label_en': 'Wikidata ID' },
    )
    gnd_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has GND ID', 'label_en': 'GND ID' },
    )
    aat_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has AAT ID', 'label_en': 'AAT ID' },
    )
    pbcore_link: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has PBCore link', 'label_en': 'PBCore Link' },
    )
    information_storage_medium_type: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has broader information storage medium type', 'label_en': 'Information Storage Medium Type' },
    )

@dataclass
class Keyword(ArkumuEntity):
    """EN: A metadata entry from the controlled vocabulary of Wikidata.
DE: Ein Metadaten-Eintrag aus dem kontrollierten Vokabular von Wikidata."""
    german_wikidata_label: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german wikidata label', 'label_en': 'German Wikidata Label' },
    )
    english_wikidata_label: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english wikidata label', 'label_en': 'English Wikidata Label' },
    )
    german_wikidata_synonym: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german wikidata synonym', 'label_en': 'German Wikidata Synonym' },
    )
    english_wikidata_synonym: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english wikidata synonym', 'label_en': 'English Wikidata Synonym' },
    )
    german_wikidata_description: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german wikidata description', 'label_en': 'German Wikidata Description' },
    )
    german_wikidata_description_2: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german wikidata description', 'label_en': 'German Wikidata Description' },
    )
    wikidata_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has Wikidata ID', 'label_en': 'Wikidata ID' },
    )
    gnd_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has GND ID', 'label_en': 'GND ID' },
    )

@dataclass
class Language(ArkumuEntity):
    """EN: A language defined by the ISO 639-2 standard. This standard was chosen to be compatible with all libraries.
DE: Eine Sprache, die durch die Norm ISO 639-2 definiert ist. Dieser Standard wurde gewählt, um mit allen Bibliotheken kompatibel zu sein."""
    german_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german name', 'label_en': 'German Name' },
    )
    english_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english name', 'label_en': 'English Name' },
    )
    iso_639_2_b_code: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has ISO 639-2(B) code', 'label_en': 'ISO 639-2(B) Code' },
    )
    iso_639_2_t_code: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has ISO 639-2(T) code', 'label_en': 'ISO 639-2(T) Code' },
    )
    iso_639_1_code: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has ISO 639-1 code', 'label_en': 'ISO 639-1 Code' },
    )

@dataclass
class OrganisationalUnit(ArkumuEntity):
    """EN: A department, an institute, a study programme, or an artistic/scientific facility.
DE: Ein Fachbereich, Institut, ein Studiengang oder eine künstlerisch/wissenschaftliche Einrichtung."""
    german_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german name', 'label_en': 'German Name' },
    )
    english_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english name', 'label_en': 'English Name' },
    )
    german_description: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german description', 'label_en': 'German Description' },
    )
    english_description: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english description', 'label_en': 'English Description' },
    )

@dataclass
class Place(ArkumuEntity):
    """EN: A place metadata entry from the controlled vocabulary of Wikidata. Only "real" places are acceptable, i.e. they must be identifiable with geolocation coordinates.
DE: Ein Ort-Metadaten-Eintrag aus dem kontrollierten Vokabular von Wikidata. Nur "reale" Orte sind erlaubt, d.h. sie müssen mit Geokoordinaten identifierbar sein."""
    german_wikidata_label: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german wikidata label', 'label_en': 'German Wikidata Label' },
    )
    english_wikidata_label: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english wikidata label', 'label_en': 'English Wikidata Label' },
    )
    place_type: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has place type', 'label_en': 'Place Type' },
    )
    wikidata_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has Wikidata ID', 'label_en': 'Wikidata ID' },
    )
    gnd_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has GND ID', 'label_en': 'GND ID' },
    )
    viaf_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has VIAF ID', 'label_en': 'VIAF ID' },
    )
    longitude: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has longitude', 'label_en': 'Longitude' },
    )
    latitude: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has latitude', 'label_en': 'Latitude' },
    )
    place: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has broader place', 'label_en': 'Place' },
    )

@dataclass
class PhyiscalObject(ArkumuEntity):
    """EN: Ein physisch abgrenzbares Objekt, ein Teil eines solchen oder ein Material, das in einem Ereignis entstanden oder verwendet wurde.
DE: A physically delineated object, a part of such, or a material that was created or used in an Event."""
    german_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german name', 'label_en': 'German Name' },
    )
    english_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english name', 'label_en': 'English Name' },
    )
    external_inventory_number: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has external inventory number', 'label_en': 'External Inventory Number' },
    )
    place: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has depository', 'label_en': 'Place' },
    )
    actor: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has owner', 'label_en': 'Actor' },
    )
    actor_2: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has legal rights holder', 'label_en': 'Actor' },
    )
    provenance: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has provenance', 'label_en': 'Provenance' },
    )
    german_description: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german description', 'label_en': 'German Description' },
    )
    english_description: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english description', 'label_en': 'English Description' },
    )
    german_commentary: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german commentary', 'label_en': 'German Commentary' },
    )
    english_commentary: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english commentary', 'label_en': 'English Commentary' },
    )
    internal_commentary: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has internal commentary', 'label_en': 'Internal Commentary' },
    )
    classifying_keyword: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has classifying keyword', 'label_en': 'Classifying Keyword' },
    )
    material_keyword: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has material keyword', 'label_en': 'Material Keyword' },
    )
    technique_keyword: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has technique keyword', 'label_en': 'Technique Keyword' },
    )
    german_technique_commentary: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german technique commentary', 'label_en': 'German Technique Commentary' },
    )
    english_technique_commentary: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english technique commentary', 'label_en': 'English Technique Commentary' },
    )
    dimensions: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has dimensions', 'label_en': 'Dimensions' },
    )
    condition_state_german: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has condition state (german)', 'label_en': 'Condition State (German)' },
    )
    condition_state_english: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has condition state (english)', 'label_en': 'Condition State (English)' },
    )

@dataclass
class Project(ArkumuEntity):
    """EN: A Project is dataset record that is describing art and things related to art, as well as holding its current legal and usage rights status of the intellectual property. A Project is the central cataloguing unit of arkumu.nrw.
DE: Ein Projekt ist ein Datensatz, der Kunst und kunstbezogene Dinge beschreibt sowie den aktuellen Rechts- und Nutzungsrechtsstatus dieses geistigen Eigentums enthält. Ein Projekt ist die zentrale Verzeichnungseinheit von arkumu.nrw."""
    preferred_title: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has preferred title', 'label_en': 'Preferred Title' },
    )
    preferred_subtitle: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has preferred subtitle', 'label_en': 'Preferred Subtitle' },
    )
    alternative_title_set: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has alternative title set', 'label_en': 'Alternative Title Set' },
    )
    depositing_university: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has depositing university', 'label_en': 'Depositing University' },
    )
    organisational_unit: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has organisational unit', 'label_en': 'Organisational Unit' },
    )
    project_type: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has project type', 'label_en': 'Project Type' },
    )
    project_category: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has project category', 'label_en': 'Project Category' },
    )
    keyword: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has keyword', 'label_en': 'Keyword' },
    )
    project_description: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has project description', 'label_en': 'Project Description' },
    )
    german_commentary: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german commentary', 'label_en': 'German Commentary' },
    )
    english_commentary: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english commentary', 'label_en': 'English Commentary' },
    )
    internal_commentary: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has internal commentary', 'label_en': 'Internal Commentary' },
    )
    event: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has event', 'label_en': 'Event' },
    )
    project_property: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has project property', 'label_en': 'Project Property' },
    )
    project: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has related project', 'label_en': 'Project' },
    )
    arkumu_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has arkumu ID', 'label_en': 'arkumu ID' },
    )
    ark_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has ARK ID', 'label_en': 'ARK ID' },
    )
    id_at_depositor: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has ID at depositor', 'label_en': 'ID at Depositor' },
    )
    catalogue_raisonn_reference_number: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has catalogue raisonné reference number', 'label_en': 'Catalogue Raisonné Reference Number' },
    )
    wikidata_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has Wikidata ID', 'label_en': 'Wikidata ID' },
    )
    gnd_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has GND ID', 'label_en': 'GND ID' },
    )
    website: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has website', 'label_en': 'Website' },
    )
    dataset_id_at_depositor: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has dataset ID at depositor', 'label_en': 'Dataset ID at Depositor' },
    )
    organisational_unit_2: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has depositor', 'label_en': 'Organisational Unit' },
    )
    dataset_creation_date_at_depositor: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has dataset creation date at depositor', 'label_en': 'Dataset Creation Date at Depositor' },
    )
    dataset_last_modification_date_at_depositor: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has dataset last modification date at depositor', 'label_en': 'Dataset Last Modification Date at Depositor' },
    )
    rights_status: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has rights status', 'label_en': 'Rights Status' },
    )
    existing_license_agreement: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has existing license agreement', 'label_en': 'Existing License Agreement' },
    )
    new_arkumu_license_agreement: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has new arkumu license agreement', 'label_en': 'New arkumu License Agreement' },
    )
    additional_rights_document: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has additional rights document', 'label_en': 'Additional Rights Document' },
    )
    file_license_document: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has file license document', 'label_en': 'File License Document' },
    )

@dataclass
class ProjectCategory(ArkumuEntity):
    """EN: A Project Category typifies a Project, in an artistic sense, with the help of a controlled vocabulary.
DE: Eine Projektkategorie typisiert ein Projekt, in einem künstlerischen Sinne, mit Hilfe eines kontrollierten Vokabulars."""
    german_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german name', 'label_en': 'German Name' },
    )
    english_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english name', 'label_en': 'English Name' },
    )
    german_synonyms: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german synonyms', 'label_en': 'German Synonyms' },
    )
    english_synonyms: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english synonyms', 'label_en': 'English Synonyms' },
    )
    wikidata_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has Wikidata ID', 'label_en': 'Wikidata ID' },
    )
    gnd_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has GND ID', 'label_en': 'GND ID' },
    )
    aat_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has AAT ID', 'label_en': 'AAT ID' },
    )
    filmportal_de_category_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has filmportal.de category ID', 'label_en': 'filmportal.de Category ID' },
    )
    project_category: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has broader project category', 'label_en': 'Project Category' },
    )

@dataclass
class ProjectDescription(ArkumuEntity):
    """EN: A text describing the content of the Project, or what the Project in question is. These can be texts written by the artists themselves or written by a third person.
DE: Ein Text, der den Inhalt des Projekts beschreibt oder was das Projekt ist. Dabei kann es sich um Texte handeln, die von den Künstler:innen selbst oder von einer dritten Person verfasst wurden."""
    description_text: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has description text', 'label_en': 'Description Text' },
    )
    sorting_number: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has sorting number', 'label_en': 'Sorting Number' },
    )

@dataclass
class ProjectType(ArkumuEntity):
    """EN: A Project Type categorises a the academic context of a Project with the help of a controlled vocabulary.
DE: Eine Projektart kategorisiert den akademischen Kontext eines Projekts mit Hilfe eines kontrollierten Vokabulars."""
    german_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german name', 'label_en': 'German Name' },
    )
    english_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english name', 'label_en': 'English Name' },
    )
    wikidata_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has Wikidata ID', 'label_en': 'Wikidata ID' },
    )

@dataclass
class Role(ArkumuEntity):
    """EN: An artistic or non-artistic role of a person, a group, or legal entity, either as a global role as profession or activity directly bound to the actor, or situational executed in an Event.
DE: Eine künstlerische oder nicht-künstlerische Rolle einer Person, einer Gruppe oder einer Körperschaft, entweder als globale Rolle, als Beruf oder Tätigkeit, direkt an eine:n Akteur:in gebunden oder situativ ausgeführt in einem Event."""
    german_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has german name', 'label_en': 'German Name' },
    )
    english_name: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has english name', 'label_en': 'English Name' },
    )
    wikidata_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has Wikidata ID', 'label_en': 'Wikidata ID' },
    )
    gnd_id_male: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has GND ID (male)', 'label_en': 'GND ID (male)' },
    )
    gnd_id_female: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has GND ID (female)', 'label_en': 'GND ID (female)' },
    )
    gnd_id_group: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has GND ID (group)', 'label_en': 'GND ID (group)' },
    )
    aat_id: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has AAT ID', 'label_en': 'AAT ID' },
    )
    role: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has broader role', 'label_en': 'Role' },
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
        metadata={ 'source_en_name': 'has language', 'label_en': 'Language' },
    )

@dataclass
class AlternativeTitle(ArkumuEntity):
    """EN: An alternative appellation for a Project, which is linked to it via an Alternative Title Set.
DE: Ein alternative Benennung für ein Projekt, die über ein Alternatives Titel-Set verbunden wird."""
    language: list[str] = field(
        default_factory=list,
        metadata={ 'source_en_name': 'has language', 'label_en': 'Language' },
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

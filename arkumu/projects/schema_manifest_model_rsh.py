"""Auto-generated from schema manifest."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Ort:
    """Dataset Ort (canonical http://arkumu.org/data/types/ort)"""
    ort_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Ort-ID', 'canonical_uri': 'http://arkumu.org/data/properties/ort-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/ort-id' })
    wikidata_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Wikidata-ID', 'canonical_uri': 'http://arkumu.org/data/properties/wikidata-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/wikidata-id' })
    deutscher_name_des_ortes: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Deutscher Name des Ortes', 'canonical_uri': 'http://arkumu.org/data/properties/deutscher-name-des-ortes', 'local_uri': 'http://arkumu.org/data/rsh/properties/deutscher-name-des-ortes' })

@dataclass
class Rolle:
    """Dataset Rolle (canonical http://arkumu.org/data/types/rolle)"""
    aat_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'AAT-ID', 'canonical_uri': 'http://arkumu.org/data/properties/aat-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/aat-id' })
    rolle_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Rolle-ID', 'canonical_uri': 'http://arkumu.org/data/properties/rolle-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/rolle-id' })
    synonyme: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Synonyme', 'canonical_uri': 'http://arkumu.org/data/properties/synonyme', 'local_uri': 'http://arkumu.org/data/rsh/properties/synonyme' })
    wikidata_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Wikidata-ID', 'canonical_uri': 'http://arkumu.org/data/properties/wikidata-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/wikidata-id' })
    gnd_nummer_gruppe: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'GND-Nummer (Gruppe)', 'canonical_uri': 'http://arkumu.org/data/properties/gnd-nummer-gruppe', 'local_uri': 'http://arkumu.org/data/rsh/properties/gnd-nummer-gruppe' })
    gnd_nummer_weiblich: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'GND-Nummer (weiblich)', 'canonical_uri': 'http://arkumu.org/data/properties/gnd-nummer-weiblich', 'local_uri': 'http://arkumu.org/data/rsh/properties/gnd-nummer-weiblich' })
    gnd_nummer_m_nnlich: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'GND-Nummer (männlich)', 'canonical_uri': 'http://arkumu.org/data/properties/gnd-nummer-maennlich', 'local_uri': 'http://arkumu.org/data/rsh/properties/gnd-nummer-maennlich' })
    deutscher_name_der_rolle_breadcrumb: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Deutscher Name der Rolle (Breadcrumb)', 'canonical_uri': 'http://arkumu.org/data/properties/deutscher-name-der-rolle-breadcrumb', 'local_uri': 'http://arkumu.org/data/rsh/properties/deutscher-name-der-rolle-breadcrumb' })
    englischer_name_der_rolle_breadcrumb: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Englischer Name der Rolle (Breadcrumb)', 'canonical_uri': 'http://arkumu.org/data/properties/englischer-name-der-rolle-breadcrumb', 'local_uri': 'http://arkumu.org/data/rsh/properties/englischer-name-der-rolle-breadcrumb' })
    w_hlt_ist_urheber_in_automatisch_aus: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'wählt ""ist Urheber:in"" automatisch aus', 'canonical_uri': 'http://arkumu.org/data/properties/waehlt-ist-urheber-in-automatisch-aus', 'local_uri': 'http://arkumu.org/data/rsh/properties/waehlt-ist-urheber-in-automatisch-aus' })
    w_hlt_besitzt_leistungsschutzrechte_automatisch_aus: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'wählt ""besitzt Leistungsschutzrechte"" automatisch aus', 'canonical_uri': 'http://arkumu.org/data/properties/waehlt-besitzt-leistungsschutzrechte-automatisch-aus', 'local_uri': 'http://arkumu.org/data/rsh/properties/waehlt-besitzt-leistungsschutzrechte-automatisch-aus' })

@dataclass
class Projekt:
    """Dataset Projekt (canonical http://arkumu.org/data/types/projekt)"""
    viaf_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'VIAF-ID', 'canonical_uri': 'http://arkumu.org/data/properties/viaf-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/viaf-id' })
    ereignis: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Ereignis', 'canonical_uri': 'http://arkumu.org/data/properties/ereignis', 'local_uri': 'http://arkumu.org/data/rsh/properties/ereignis' })
    gnd_nummer: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'GND-Nummer', 'canonical_uri': 'http://arkumu.org/data/properties/gnd-nummer', 'local_uri': 'http://arkumu.org/data/rsh/properties/gnd-nummer' })
    projekt_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Projekt-ID', 'canonical_uri': 'http://arkumu.org/data/properties/projekt-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/projekt-id' })
    projektart: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Projektart', 'canonical_uri': 'http://arkumu.org/data/properties/projektart', 'local_uri': 'http://arkumu.org/data/rsh/properties/projektart' })
    schlagwort: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Schlagwort', 'canonical_uri': 'http://arkumu.org/data/properties/schlagwort', 'local_uri': 'http://arkumu.org/data/rsh/properties/schlagwort' })
    wikidata_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Wikidata-ID', 'canonical_uri': 'http://arkumu.org/data/properties/wikidata-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/wikidata-id' })
    beschreibung: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Beschreibung', 'canonical_uri': 'http://arkumu.org/data/properties/beschreibung', 'local_uri': 'http://arkumu.org/data/rsh/properties/beschreibung' })
    rechtsstatus: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Rechtsstatus', 'canonical_uri': 'http://arkumu.org/data/properties/rechtsstatus', 'local_uri': 'http://arkumu.org/data/rsh/properties/rechtsstatus' })
    vorschaubild: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Vorschaubild', 'canonical_uri': 'http://arkumu.org/data/properties/vorschaubild', 'local_uri': 'http://arkumu.org/data/rsh/properties/vorschaubild' })
    inhaltswarnung: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Inhaltswarnung', 'canonical_uri': 'http://arkumu.org/data/properties/inhaltswarnung', 'local_uri': 'http://arkumu.org/data/rsh/properties/inhaltswarnung' })
    sonderregelung: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Sonderregelung', 'canonical_uri': 'http://arkumu.org/data/properties/sonderregelung', 'local_uri': 'http://arkumu.org/data/rsh/properties/sonderregelung' })
    andere_normdaten: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Andere Normdaten', 'canonical_uri': 'http://arkumu.org/data/properties/andere-normdaten', 'local_uri': 'http://arkumu.org/data/rsh/properties/andere-normdaten' })
    projektkategorie: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Projektkategorie', 'canonical_uri': 'http://arkumu.org/data/properties/projektkategorie', 'local_uri': 'http://arkumu.org/data/rsh/properties/projektkategorie' })
    bevorzugter_titel: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Bevorzugter Titel', 'canonical_uri': 'http://arkumu.org/data/properties/bevorzugter-titel', 'local_uri': 'http://arkumu.org/data/rsh/properties/bevorzugter-titel' })
    interner_kommentar: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Interner Kommentar', 'canonical_uri': 'http://arkumu.org/data/properties/interner-kommentar', 'local_uri': 'http://arkumu.org/data/rsh/properties/interner-kommentar' })
    deutscher_kommentar: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Deutscher Kommentar', 'canonical_uri': 'http://arkumu.org/data/properties/deutscher-kommentar', 'local_uri': 'http://arkumu.org/data/rsh/properties/deutscher-kommentar' })
    dateiabfragedokument: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Dateiabfragedokument', 'canonical_uri': 'http://arkumu.org/data/properties/dateiabfragedokument', 'local_uri': 'http://arkumu.org/data/rsh/properties/dateiabfragedokument' })
    englischer_kommentar: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Englischer Kommentar', 'canonical_uri': 'http://arkumu.org/data/properties/englischer-kommentar', 'local_uri': 'http://arkumu.org/data/rsh/properties/englischer-kommentar' })
    organisationseinheit: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Organisationseinheit', 'canonical_uri': 'http://arkumu.org/data/properties/organisationseinheit', 'local_uri': 'http://arkumu.org/data/rsh/properties/organisationseinheit' })
    alternativer_titel_set: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Alternativer Titel-Set', 'canonical_uri': 'http://arkumu.org/data/properties/alternativer-titel-set', 'local_uri': 'http://arkumu.org/data/rsh/properties/alternativer-titel-set' })
    bevorzugter_untertitel: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Bevorzugter Untertitel', 'canonical_uri': 'http://arkumu.org/data/properties/bevorzugter-untertitel', 'local_uri': 'http://arkumu.org/data/rsh/properties/bevorzugter-untertitel' })
    werkverzeichnis_nummer: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Werkverzeichnis-Nummer', 'canonical_uri': 'http://arkumu.org/data/properties/werkverzeichnis-nummer', 'local_uri': 'http://arkumu.org/data/rsh/properties/werkverzeichnis-nummer' })
    art_des_lizenzvertrages: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Art des Lizenzvertrages', 'canonical_uri': 'http://arkumu.org/data/properties/art-des-lizenzvertrages', 'local_uri': 'http://arkumu.org/data/rsh/properties/art-des-lizenzvertrages' })
    einliefernde_hochschule: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Einliefernde Hochschule', 'canonical_uri': 'http://arkumu.org/data/properties/einliefernde-hochschule', 'local_uri': 'http://arkumu.org/data/rsh/properties/einliefernde-hochschule' })
    externe_projektwebseite: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Externe Projektwebseite', 'canonical_uri': 'http://arkumu.org/data/properties/externe-projektwebseite', 'local_uri': 'http://arkumu.org/data/rsh/properties/externe-projektwebseite' })
    weiteres_rechtsdokument: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Weiteres Rechtsdokument', 'canonical_uri': 'http://arkumu.org/data/properties/weiteres-rechtsdokument', 'local_uri': 'http://arkumu.org/data/rsh/properties/weiteres-rechtsdokument' })
    angegebene_nutzungsrechte: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Angegebene Nutzungsrechte', 'canonical_uri': 'http://arkumu.org/data/properties/angegebene-nutzungsrechte', 'local_uri': 'http://arkumu.org/data/rsh/properties/angegebene-nutzungsrechte' })
    bestehender_lizenzvertrag: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Bestehender Lizenzvertrag', 'canonical_uri': 'http://arkumu.org/data/properties/bestehender-lizenzvertrag', 'local_uri': 'http://arkumu.org/data/rsh/properties/bestehender-lizenzvertrag' })
    signatur_beim_einlieferer: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Signatur beim Einlieferer', 'canonical_uri': 'http://arkumu.org/data/properties/signatur-beim-einlieferer', 'local_uri': 'http://arkumu.org/data/rsh/properties/signatur-beim-einlieferer' })
    sprache_des_bevorzugten_titels: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Sprache des bevorzugten Titels', 'canonical_uri': 'http://arkumu.org/data/properties/sprache-des-bevorzugten-titels', 'local_uri': 'http://arkumu.org/data/rsh/properties/sprache-des-bevorzugten-titels' })
    projekterstellung_beim_einlieferer: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Projekterstellung beim Einlieferer', 'canonical_uri': 'http://arkumu.org/data/properties/projekterstellung-beim-einlieferer', 'local_uri': 'http://arkumu.org/data/rsh/properties/projekterstellung-beim-einlieferer' })
    sprache_des_bevorzugten_untertitels: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Sprache des bevorzugten Untertitels', 'canonical_uri': 'http://arkumu.org/data/properties/sprache-des-bevorzugten-untertitels', 'local_uri': 'http://arkumu.org/data/rsh/properties/sprache-des-bevorzugten-untertitels' })
    neuer_lizenzvertrag_digi_kunst_formular: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Neuer Lizenzvertrag (Digi-Kunst-Formular)', 'canonical_uri': 'http://arkumu.org/data/properties/neuer-lizenzvertrag-digi-kunst-formular', 'local_uri': 'http://arkumu.org/data/rsh/properties/neuer-lizenzvertrag-digi-kunst-formular' })
    letzte_projektmodifikation_beim_einlieferer: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Letzte Projektmodifikation beim Einlieferer', 'canonical_uri': 'http://arkumu.org/data/properties/letzte-projektmodifikation-beim-einlieferer', 'local_uri': 'http://arkumu.org/data/rsh/properties/letzte-projektmodifikation-beim-einlieferer' })

@dataclass
class Sprache:
    """Dataset Sprache (canonical http://arkumu.org/data/types/sprache)"""
    sprache_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Sprache-ID', 'canonical_uri': 'http://arkumu.org/data/properties/sprache-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/sprache-id' })
    iso_639_1_code: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'ISO-639-1-Code', 'canonical_uri': 'http://arkumu.org/data/properties/iso-639-1-code', 'local_uri': 'http://arkumu.org/data/rsh/properties/iso-639-1-code' })
    iso_639_2_b_code: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'ISO-639-2(B)-Code', 'canonical_uri': 'http://arkumu.org/data/properties/iso-639-2b-code', 'local_uri': 'http://arkumu.org/data/rsh/properties/iso-639-2b-code' })
    iso_639_2_t_code: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'ISO-639-2(T)-Code', 'canonical_uri': 'http://arkumu.org/data/properties/iso-639-2t-code', 'local_uri': 'http://arkumu.org/data/rsh/properties/iso-639-2t-code' })
    deutscher_name_der_sprache: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Deutscher Name der Sprache', 'canonical_uri': 'http://arkumu.org/data/properties/deutscher-name-der-sprache', 'local_uri': 'http://arkumu.org/data/rsh/properties/deutscher-name-der-sprache' })
    englischer_name_der_sprache: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Englischer Name der Sprache', 'canonical_uri': 'http://arkumu.org/data/properties/englischer-name-der-sprache', 'local_uri': 'http://arkumu.org/data/rsh/properties/englischer-name-der-sprache' })

@dataclass
class Akteurin:
    """Dataset AkteurIn (canonical http://arkumu.org/data/types/akteurin)"""
    orcid: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'OrcID', 'canonical_uri': 'http://arkumu.org/data/properties/orcid', 'local_uri': 'http://arkumu.org/data/rsh/properties/orcid' })
    lccn_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'LCCN-ID', 'canonical_uri': 'http://arkumu.org/data/properties/lccn-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/lccn-id' })
    viaf_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'VIAF-ID', 'canonical_uri': 'http://arkumu.org/data/properties/viaf-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/viaf-id' })
    sterbeort: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Sterbeort', 'canonical_uri': 'http://arkumu.org/data/properties/sterbeort', 'local_uri': 'http://arkumu.org/data/rsh/properties/sterbeort' })
    gnd_nummer: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'GND-Nummer', 'canonical_uri': 'http://arkumu.org/data/properties/gnd-nummer', 'local_uri': 'http://arkumu.org/data/rsh/properties/gnd-nummer' })
    geburtsort: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Geburtsort', 'canonical_uri': 'http://arkumu.org/data/properties/geburtsort', 'local_uri': 'http://arkumu.org/data/rsh/properties/geburtsort' })
    geschlecht: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Geschlecht', 'canonical_uri': 'http://arkumu.org/data/properties/geschlecht', 'local_uri': 'http://arkumu.org/data/rsh/properties/geschlecht' })
    akteurin_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'AkteurIn-ID', 'canonical_uri': 'http://arkumu.org/data/properties/akteurin-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/akteurin-id' })
    wikidata_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Wikidata-ID', 'canonical_uri': 'http://arkumu.org/data/properties/wikidata-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/wikidata-id' })
    wirkungsort: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Wirkungsort', 'canonical_uri': 'http://arkumu.org/data/properties/wirkungsort', 'local_uri': 'http://arkumu.org/data/rsh/properties/wirkungsort' })
    wirkungsende: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Wirkungsende', 'canonical_uri': 'http://arkumu.org/data/properties/wirkungsende', 'local_uri': 'http://arkumu.org/data/rsh/properties/wirkungsende' })
    gr_ndungsort: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Gründungsort', 'canonical_uri': 'http://arkumu.org/data/properties/gruendungsort', 'local_uri': 'http://arkumu.org/data/rsh/properties/gruendungsort' })
    aufl_sungsort: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Auflösungsort', 'canonical_uri': 'http://arkumu.org/data/properties/aufloesungsort', 'local_uri': 'http://arkumu.org/data/rsh/properties/aufloesungsort' })
    deutscher_name: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Deutscher Name', 'canonical_uri': 'http://arkumu.org/data/properties/deutscher-name', 'local_uri': 'http://arkumu.org/data/rsh/properties/deutscher-name' })
    wirkungsbeginn: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Wirkungsbeginn', 'canonical_uri': 'http://arkumu.org/data/properties/wirkungsbeginn', 'local_uri': 'http://arkumu.org/data/rsh/properties/wirkungsbeginn' })
    englischer_name: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Englischer Name', 'canonical_uri': 'http://arkumu.org/data/properties/englischer-name', 'local_uri': 'http://arkumu.org/data/rsh/properties/englischer-name' })
    andere_normdaten: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Andere Normdaten', 'canonical_uri': 'http://arkumu.org/data/properties/andere-normdaten', 'local_uri': 'http://arkumu.org/data/rsh/properties/andere-normdaten' })
    alternativer_name: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Alternativer Name', 'canonical_uri': 'http://arkumu.org/data/properties/alternativer-name', 'local_uri': 'http://arkumu.org/data/rsh/properties/alternativer-name' })
    interner_kommentar: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Interner Kommentar', 'canonical_uri': 'http://arkumu.org/data/properties/interner-kommentar', 'local_uri': 'http://arkumu.org/data/rsh/properties/interner-kommentar' })
    deutscher_kommentar: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Deutscher Kommentar', 'canonical_uri': 'http://arkumu.org/data/properties/deutscher-kommentar', 'local_uri': 'http://arkumu.org/data/rsh/properties/deutscher-kommentar' })
    beruf_und_t_tigkeit: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Beruf und Tätigkeit', 'canonical_uri': 'http://arkumu.org/data/properties/beruf-und-taetigkeit', 'local_uri': 'http://arkumu.org/data/rsh/properties/beruf-und-taetigkeit' })
    englischer_kommentar: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Englischer Kommentar', 'canonical_uri': 'http://arkumu.org/data/properties/englischer-kommentar', 'local_uri': 'http://arkumu.org/data/rsh/properties/englischer-kommentar' })
    nachgestellter_titel: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Nachgestellter Titel', 'canonical_uri': 'http://arkumu.org/data/properties/nachgestellter-titel', 'local_uri': 'http://arkumu.org/data/rsh/properties/nachgestellter-titel' })
    vorangestellter_titel: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Vorangestellter Titel', 'canonical_uri': 'http://arkumu.org/data/properties/vorangestellter-titel', 'local_uri': 'http://arkumu.org/data/rsh/properties/vorangestellter-titel' })
    webseite_der_akteurin: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Webseite der AkteurIn', 'canonical_uri': 'http://arkumu.org/data/properties/webseite-der-akteurin', 'local_uri': 'http://arkumu.org/data/rsh/properties/webseite-der-akteurin' })
    deutsche_kurzbiografie: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Deutsche Kurzbiografie', 'canonical_uri': 'http://arkumu.org/data/properties/deutsche-kurzbiografie', 'local_uri': 'http://arkumu.org/data/rsh/properties/deutsche-kurzbiografie' })
    fr_hestes_sterbedatum: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Frühestes Sterbedatum', 'canonical_uri': 'http://arkumu.org/data/properties/fruehestes-sterbedatum', 'local_uri': 'http://arkumu.org/data/rsh/properties/fruehestes-sterbedatum' })
    sp_testes_sterbedatum: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Spätestes Sterbedatum', 'canonical_uri': 'http://arkumu.org/data/properties/spaetestes-sterbedatum', 'local_uri': 'http://arkumu.org/data/rsh/properties/spaetestes-sterbedatum' })
    englische_kurzbiografie: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Englische Kurzbiografie', 'canonical_uri': 'http://arkumu.org/data/properties/englische-kurzbiografie', 'local_uri': 'http://arkumu.org/data/rsh/properties/englische-kurzbiografie' })
    fr_hestes_geburtsdatum: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Frühestes Geburtsdatum', 'canonical_uri': 'http://arkumu.org/data/properties/fruehestes-geburtsdatum', 'local_uri': 'http://arkumu.org/data/rsh/properties/fruehestes-geburtsdatum' })
    sp_testes_geburtsdatum: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Spätestes Geburtsdatum', 'canonical_uri': 'http://arkumu.org/data/properties/spaetestes-geburtsdatum', 'local_uri': 'http://arkumu.org/data/rsh/properties/spaetestes-geburtsdatum' })
    nicht_ffentlicher_name: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Nicht-öffentlicher Name', 'canonical_uri': 'http://arkumu.org/data/properties/nicht-oeffentlicher-name', 'local_uri': 'http://arkumu.org/data/rsh/properties/nicht-oeffentlicher-name' })
    nicht_ffentlicher_name_begr_ndung: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Nicht-öffentlicher Name (Begründung)', 'canonical_uri': 'http://arkumu.org/data/properties/nicht-oeffentlicher-name-begruendung', 'local_uri': 'http://arkumu.org/data/rsh/properties/nicht-oeffentlicher-name-begruendung' })

@dataclass
class Ereignis:
    """Dataset Ereignis (canonical http://arkumu.org/data/types/ereignis)"""
    viaf_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'VIAF-ID', 'canonical_uri': 'http://arkumu.org/data/properties/viaf-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/viaf-id' })
    gnd_nummer: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'GND-Nummer', 'canonical_uri': 'http://arkumu.org/data/properties/gnd-nummer', 'local_uri': 'http://arkumu.org/data/rsh/properties/gnd-nummer' })
    einlieferer: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Einlieferer', 'canonical_uri': 'http://arkumu.org/data/properties/einlieferer', 'local_uri': 'http://arkumu.org/data/rsh/properties/einlieferer' })
    ereignis_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Ereignis-ID', 'canonical_uri': 'http://arkumu.org/data/properties/ereignis-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/ereignis-id' })
    ereignisort: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Ereignisort', 'canonical_uri': 'http://arkumu.org/data/properties/ereignisort', 'local_uri': 'http://arkumu.org/data/rsh/properties/ereignisort' })
    ereignistyp: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Ereignistyp', 'canonical_uri': 'http://arkumu.org/data/properties/ereignistyp', 'local_uri': 'http://arkumu.org/data/rsh/properties/ereignistyp' })
    wikidata_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Wikidata-ID', 'canonical_uri': 'http://arkumu.org/data/properties/wikidata-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/wikidata-id' })
    ereignisende: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Ereignisende', 'canonical_uri': 'http://arkumu.org/data/properties/ereignisende', 'local_uri': 'http://arkumu.org/data/rsh/properties/ereignisende' })
    ereignisname: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Ereignisname', 'canonical_uri': 'http://arkumu.org/data/properties/ereignisname', 'local_uri': 'http://arkumu.org/data/rsh/properties/ereignisname' })
    ereignisbeginn: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Ereignisbeginn', 'canonical_uri': 'http://arkumu.org/data/properties/ereignisbeginn', 'local_uri': 'http://arkumu.org/data/rsh/properties/ereignisbeginn' })
    andere_normdaten: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Andere Normdaten', 'canonical_uri': 'http://arkumu.org/data/properties/andere-normdaten', 'local_uri': 'http://arkumu.org/data/rsh/properties/andere-normdaten' })
    digitales_objekt: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Digitales Objekt', 'canonical_uri': 'http://arkumu.org/data/properties/digitales-objekt', 'local_uri': 'http://arkumu.org/data/rsh/properties/digitales-objekt' })
    physisches_objekt: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Physisches Objekt', 'canonical_uri': 'http://arkumu.org/data/properties/physisches-objekt', 'local_uri': 'http://arkumu.org/data/rsh/properties/physisches-objekt' })
    interner_kommentar: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Interner Kommentar', 'canonical_uri': 'http://arkumu.org/data/properties/interner-kommentar', 'local_uri': 'http://arkumu.org/data/rsh/properties/interner-kommentar' })
    deutscher_kommentar: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Deutscher Kommentar', 'canonical_uri': 'http://arkumu.org/data/properties/deutscher-kommentar', 'local_uri': 'http://arkumu.org/data/rsh/properties/deutscher-kommentar' })
    informationstr_ger: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Informationsträger', 'canonical_uri': 'http://arkumu.org/data/properties/informationstraeger', 'local_uri': 'http://arkumu.org/data/rsh/properties/informationstraeger' })
    englischer_kommentar: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Englischer Kommentar', 'canonical_uri': 'http://arkumu.org/data/properties/englischer-kommentar', 'local_uri': 'http://arkumu.org/data/rsh/properties/englischer-kommentar' })
    ereignisbeschreibung: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Ereignisbeschreibung', 'canonical_uri': 'http://arkumu.org/data/properties/ereignisbeschreibung', 'local_uri': 'http://arkumu.org/data/rsh/properties/ereignisbeschreibung' })
    equipment_und_software: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Equipment und Software', 'canonical_uri': 'http://arkumu.org/data/properties/equipment-und-software', 'local_uri': 'http://arkumu.org/data/rsh/properties/equipment-und-software' })
    ereignisende_gesch_tzt: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Ereignisende geschätzt', 'canonical_uri': 'http://arkumu.org/data/properties/ereignisende-geschaetzt', 'local_uri': 'http://arkumu.org/data/rsh/properties/ereignisende-geschaetzt' })
    ereignisbeginn_gesch_tzt: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Ereignisbeginn geschätzt', 'canonical_uri': 'http://arkumu.org/data/properties/ereignisbeginn-geschaetzt', 'local_uri': 'http://arkumu.org/data/rsh/properties/ereignisbeginn-geschaetzt' })
    datensatz_id_beim_einlieferer: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Datensatz-ID beim Einlieferer', 'canonical_uri': 'http://arkumu.org/data/properties/datensatz-id-beim-einlieferer', 'local_uri': 'http://arkumu.org/data/rsh/properties/datensatz-id-beim-einlieferer' })
    datensatzerstellung_beim_einlieferer: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Datensatzerstellung beim Einlieferer', 'canonical_uri': 'http://arkumu.org/data/properties/datensatzerstellung-beim-einlieferer', 'local_uri': 'http://arkumu.org/data/rsh/properties/datensatzerstellung-beim-einlieferer' })
    letzte_datensatzmodifikation_beim_einlieferer: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Letzte Datensatzmodifikation beim Einlieferer', 'canonical_uri': 'http://arkumu.org/data/properties/letzte-datensatzmodifikation-beim-einlieferer', 'local_uri': 'http://arkumu.org/data/rsh/properties/letzte-datensatzmodifikation-beim-einlieferer' })

@dataclass
class Sammlung:
    """Dataset Sammlung (canonical http://arkumu.org/data/types/sammlung)"""
    sammlung_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Sammlung-ID', 'canonical_uri': 'http://arkumu.org/data/properties/sammlung-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/sammlung-id' })
    sammlungsart: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Sammlungsart', 'canonical_uri': 'http://arkumu.org/data/properties/sammlungsart', 'local_uri': 'http://arkumu.org/data/rsh/properties/sammlungsart' })
    verkn_pftes_projekt: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Verknüpftes Projekt', 'canonical_uri': 'http://arkumu.org/data/properties/verknuepftes-projekt', 'local_uri': 'http://arkumu.org/data/rsh/properties/verknuepftes-projekt' })
    deutsche_beschreibung: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Deutsche Beschreibung', 'canonical_uri': 'http://arkumu.org/data/properties/deutsche-beschreibung', 'local_uri': 'http://arkumu.org/data/rsh/properties/deutsche-beschreibung' })
    verkn_pftes_ereignis: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Verknüpftes Ereignis', 'canonical_uri': 'http://arkumu.org/data/properties/verknuepftes-ereignis', 'local_uri': 'http://arkumu.org/data/rsh/properties/verknuepftes-ereignis' })
    englische_beschreibung: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Englische Beschreibung', 'canonical_uri': 'http://arkumu.org/data/properties/englische-beschreibung', 'local_uri': 'http://arkumu.org/data/rsh/properties/englische-beschreibung' })
    deutscher_name_der_sammlung: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Deutscher Name der Sammlung', 'canonical_uri': 'http://arkumu.org/data/properties/deutscher-name-der-sammlung', 'local_uri': 'http://arkumu.org/data/rsh/properties/deutscher-name-der-sammlung' })
    englischer_name_der_sammlung: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Englischer Name der Sammlung', 'canonical_uri': 'http://arkumu.org/data/properties/englischer-name-der-sammlung', 'local_uri': 'http://arkumu.org/data/rsh/properties/englischer-name-der-sammlung' })
    verkn_pftes_digitales_objekt: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Verknüpftes Digitales Objekt', 'canonical_uri': 'http://arkumu.org/data/properties/verknuepftes-digitales-objekt', 'local_uri': 'http://arkumu.org/data/rsh/properties/verknuepftes-digitales-objekt' })
    verkn_pftes_physisches_objekt: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Verknüpftes Physisches Objekt', 'canonical_uri': 'http://arkumu.org/data/properties/verknuepftes-physisches-objekt', 'local_uri': 'http://arkumu.org/data/rsh/properties/verknuepftes-physisches-objekt' })
    verkn_pfter_informationstr_ger: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Verknüpfter Informationsträger', 'canonical_uri': 'http://arkumu.org/data/properties/verknuepfter-informationstraeger', 'local_uri': 'http://arkumu.org/data/rsh/properties/verknuepfter-informationstraeger' })
    verkn_pftes_equipment_und_software: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Verknüpftes Equipment und Software', 'canonical_uri': 'http://arkumu.org/data/properties/verknuepftes-equipment-und-software', 'local_uri': 'http://arkumu.org/data/rsh/properties/verknuepftes-equipment-und-software' })

@dataclass
class Nummernart:
    """Dataset Nummernart (canonical http://arkumu.org/data/types/nummernart)"""
    gnd_nummer: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'GND-Nummer', 'canonical_uri': 'http://arkumu.org/data/properties/gnd-nummer', 'local_uri': 'http://arkumu.org/data/rsh/properties/gnd-nummer' })
    wikidata_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Wikidata-ID', 'canonical_uri': 'http://arkumu.org/data/properties/wikidata-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/wikidata-id' })
    nummernart_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Nummernart-ID', 'canonical_uri': 'http://arkumu.org/data/properties/nummernart-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/nummernart-id' })
    deutscher_name_der_nummernart: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Deutscher Name der Nummernart', 'canonical_uri': 'http://arkumu.org/data/properties/deutscher-name-der-nummernart', 'local_uri': 'http://arkumu.org/data/rsh/properties/deutscher-name-der-nummernart' })
    englischer_name_der_nummernart: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Englischer Name der Nummernart', 'canonical_uri': 'http://arkumu.org/data/properties/englischer-name-der-nummernart', 'local_uri': 'http://arkumu.org/data/rsh/properties/englischer-name-der-nummernart' })

@dataclass
class Projektart:
    """Dataset Projektart (canonical http://arkumu.org/data/types/projektart)"""
    wikidata_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Wikidata-ID', 'canonical_uri': 'http://arkumu.org/data/properties/wikidata-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/wikidata-id' })
    projektart_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Projektart-ID', 'canonical_uri': 'http://arkumu.org/data/properties/projektart-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/projektart-id' })
    deutscher_name_der_projektart: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Deutscher Name der Projektart', 'canonical_uri': 'http://arkumu.org/data/properties/deutscher-name-der-projektart', 'local_uri': 'http://arkumu.org/data/rsh/properties/deutscher-name-der-projektart' })
    englischer_name_der_projektart: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Englischer Name der Projektart', 'canonical_uri': 'http://arkumu.org/data/properties/englischer-name-der-projektart', 'local_uri': 'http://arkumu.org/data/rsh/properties/englischer-name-der-projektart' })

@dataclass
class Schlagwort:
    """Dataset Schlagwort (canonical http://arkumu.org/data/types/schlagwort)"""
    wikidata_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Wikidata-ID', 'canonical_uri': 'http://arkumu.org/data/properties/wikidata-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/wikidata-id' })
    schlagwort_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Schlagwort-ID', 'canonical_uri': 'http://arkumu.org/data/properties/schlagwort-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/schlagwort-id' })
    deutsches_wikidata_label: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Deutsches Wikidata-Label', 'canonical_uri': 'http://arkumu.org/data/properties/deutsches-wikidata-label', 'local_uri': 'http://arkumu.org/data/rsh/properties/deutsches-wikidata-label' })

@dataclass
class Ereignistyp:
    """Dataset Ereignistyp (canonical http://arkumu.org/data/types/ereignistyp)"""
    aat_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'AAT-ID', 'canonical_uri': 'http://arkumu.org/data/properties/aat-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/aat-id' })
    synonyme: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Synonyme', 'canonical_uri': 'http://arkumu.org/data/properties/synonyme', 'local_uri': 'http://arkumu.org/data/rsh/properties/synonyme' })
    gnd_nummer: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'GND-Nummer', 'canonical_uri': 'http://arkumu.org/data/properties/gnd-nummer', 'local_uri': 'http://arkumu.org/data/rsh/properties/gnd-nummer' })
    wikidata_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Wikidata-ID', 'canonical_uri': 'http://arkumu.org/data/properties/wikidata-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/wikidata-id' })
    ereignistyp_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Ereignistyp-ID', 'canonical_uri': 'http://arkumu.org/data/properties/ereignistyp-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/ereignistyp-id' })
    lido_terminologie_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'LIDO-Terminologie-ID', 'canonical_uri': 'http://arkumu.org/data/properties/lido-terminologie-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/lido-terminologie-id' })
    deutscher_name_des_ereignistyps: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Deutscher Name des Ereignistyps', 'canonical_uri': 'http://arkumu.org/data/properties/deutscher-name-des-ereignistyps', 'local_uri': 'http://arkumu.org/data/rsh/properties/deutscher-name-des-ereignistyps' })
    englischer_name_des_ereignistyps: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Englischer Name des Ereignistyps', 'canonical_uri': 'http://arkumu.org/data/properties/englischer-name-des-ereignistyps', 'local_uri': 'http://arkumu.org/data/rsh/properties/englischer-name-des-ereignistyps' })

@dataclass
class Beschreibung:
    """Dataset Beschreibung (canonical http://arkumu.org/data/types/beschreibung)"""
    sortierung: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Sortierung', 'canonical_uri': 'http://arkumu.org/data/properties/sortierung', 'local_uri': 'http://arkumu.org/data/rsh/properties/sortierung' })
    beschreibung: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Beschreibung', 'canonical_uri': 'http://arkumu.org/data/properties/beschreibung', 'local_uri': 'http://arkumu.org/data/rsh/properties/beschreibung' })
    beschreibung_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Beschreibung-ID', 'canonical_uri': 'http://arkumu.org/data/properties/beschreibung-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/beschreibung-id' })
    sprache_der_beschreibung: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Sprache der Beschreibung', 'canonical_uri': 'http://arkumu.org/data/properties/sprache-der-beschreibung', 'local_uri': 'http://arkumu.org/data/rsh/properties/sprache-der-beschreibung' })

@dataclass
class Equipmentart:
    """Dataset Equipmentart (canonical http://arkumu.org/data/types/equipmentart)"""
    aat_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'AAT-ID', 'canonical_uri': 'http://arkumu.org/data/properties/aat-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/aat-id' })
    gnd_nummer: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'GND-Nummer', 'canonical_uri': 'http://arkumu.org/data/properties/gnd-nummer', 'local_uri': 'http://arkumu.org/data/rsh/properties/gnd-nummer' })
    wikidata_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Wikidata-ID', 'canonical_uri': 'http://arkumu.org/data/properties/wikidata-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/wikidata-id' })
    equipmentart_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Equipmentart-ID', 'canonical_uri': 'http://arkumu.org/data/properties/equipmentart-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/equipmentart-id' })
    deutscher_name_der_equipmentart: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Deutscher Name der Equipmentart', 'canonical_uri': 'http://arkumu.org/data/properties/deutscher-name-der-equipmentart', 'local_uri': 'http://arkumu.org/data/rsh/properties/deutscher-name-der-equipmentart' })
    englischer_name_der_equipmentart: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Englischer Name der Equipmentart', 'canonical_uri': 'http://arkumu.org/data/properties/englischer-name-der-equipmentart', 'local_uri': 'http://arkumu.org/data/rsh/properties/englischer-name-der-equipmentart' })

@dataclass
class DigitalesObjekt:
    """Dataset Digitales_Objekt (canonical http://arkumu.org/data/types/digitales-objekt)"""
    eq: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'EQ', 'canonical_uri': 'http://arkumu.org/data/properties/eq', 'local_uri': 'http://arkumu.org/data/rsh/properties/eq' })
    dcp_art: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'DCP-Art', 'canonical_uri': 'http://arkumu.org/data/properties/dcp-art', 'local_uri': 'http://arkumu.org/data/rsh/properties/dcp-art' })
    dateiname: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Dateiname', 'canonical_uri': 'http://arkumu.org/data/properties/dateiname', 'local_uri': 'http://arkumu.org/data/rsh/properties/dateiname' })
    dateipfad: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Dateipfad', 'canonical_uri': 'http://arkumu.org/data/properties/dateipfad', 'local_uri': 'http://arkumu.org/data/rsh/properties/dateipfad' })
    medientyp: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Medientyp', 'canonical_uri': 'http://arkumu.org/data/properties/medientyp', 'local_uri': 'http://arkumu.org/data/rsh/properties/medientyp' })
    objekttyp: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Objekttyp', 'canonical_uri': 'http://arkumu.org/data/properties/objekttyp', 'local_uri': 'http://arkumu.org/data/rsh/properties/objekttyp' })
    tonformat: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Tonformat', 'canonical_uri': 'http://arkumu.org/data/properties/tonformat', 'local_uri': 'http://arkumu.org/data/rsh/properties/tonformat' })
    dateipaket: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Dateipaket', 'canonical_uri': 'http://arkumu.org/data/properties/dateipaket', 'local_uri': 'http://arkumu.org/data/rsh/properties/dateipaket' })
    entstehung: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Entstehung', 'canonical_uri': 'http://arkumu.org/data/properties/entstehung', 'local_uri': 'http://arkumu.org/data/rsh/properties/entstehung' })
    einlieferer: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Einlieferer', 'canonical_uri': 'http://arkumu.org/data/properties/einlieferer', 'local_uri': 'http://arkumu.org/data/rsh/properties/einlieferer' })
    lizenzstatus: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Lizenzstatus', 'canonical_uri': 'http://arkumu.org/data/properties/lizenzstatus', 'local_uri': 'http://arkumu.org/data/rsh/properties/lizenzstatus' })
    anzeigestatus: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Anzeigestatus', 'canonical_uri': 'http://arkumu.org/data/properties/anzeigestatus', 'local_uri': 'http://arkumu.org/data/rsh/properties/anzeigestatus' })
    erhaltungstyp: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Erhaltungstyp', 'canonical_uri': 'http://arkumu.org/data/properties/erhaltungstyp', 'local_uri': 'http://arkumu.org/data/rsh/properties/erhaltungstyp' })
    sprachfassung: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Sprachfassung', 'canonical_uri': 'http://arkumu.org/data/properties/sprachfassung', 'local_uri': 'http://arkumu.org/data/rsh/properties/sprachfassung' })
    originalsprache: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Originalsprache', 'canonical_uri': 'http://arkumu.org/data/properties/originalsprache', 'local_uri': 'http://arkumu.org/data/rsh/properties/originalsprache' })
    tonmischfassung: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Tonmischfassung', 'canonical_uri': 'http://arkumu.org/data/properties/tonmischfassung', 'local_uri': 'http://arkumu.org/data/rsh/properties/tonmischfassung' })
    teil_einer_serie: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Teil einer Serie', 'canonical_uri': 'http://arkumu.org/data/properties/teil-einer-serie', 'local_uri': 'http://arkumu.org/data/rsh/properties/teil-einer-serie' })
    untertitelsprache: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Untertitelsprache', 'canonical_uri': 'http://arkumu.org/data/properties/untertitelsprache', 'local_uri': 'http://arkumu.org/data/rsh/properties/untertitelsprache' })
    interner_kommentar: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Interner Kommentar', 'canonical_uri': 'http://arkumu.org/data/properties/interner-kommentar', 'local_uri': 'http://arkumu.org/data/rsh/properties/interner-kommentar' })
    projektkompilation: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Projektkompilation', 'canonical_uri': 'http://arkumu.org/data/properties/projektkompilation', 'local_uri': 'http://arkumu.org/data/rsh/properties/projektkompilation' })
    derivatkopie_nummer: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Derivatkopie-Nummer', 'canonical_uri': 'http://arkumu.org/data/properties/derivatkopie-nummer', 'local_uri': 'http://arkumu.org/data/rsh/properties/derivatkopie-nummer' })
    deutscher_kommentar: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Deutscher Kommentar', 'canonical_uri': 'http://arkumu.org/data/properties/deutscher-kommentar', 'local_uri': 'http://arkumu.org/data/rsh/properties/deutscher-kommentar' })
    digitales_objekt_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Digitales Objekt-ID', 'canonical_uri': 'http://arkumu.org/data/properties/digitales-objekt-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/digitales-objekt-id' })
    englischer_kommentar: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Englischer Kommentar', 'canonical_uri': 'http://arkumu.org/data/properties/englischer-kommentar', 'local_uri': 'http://arkumu.org/data/rsh/properties/englischer-kommentar' })
    systemvoraussetzungen: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Systemvoraussetzungen', 'canonical_uri': 'http://arkumu.org/data/properties/systemvoraussetzungen', 'local_uri': 'http://arkumu.org/data/rsh/properties/systemvoraussetzungen' })
    wird_im_loop_abgespielt: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Wird im Loop abgespielt', 'canonical_uri': 'http://arkumu.org/data/properties/wird-im-loop-abgespielt', 'local_uri': 'http://arkumu.org/data/rsh/properties/wird-im-loop-abgespielt' })
    khm_internetfreigabestufe: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'KHM-Internetfreigabestufe', 'canonical_uri': 'http://arkumu.org/data/properties/khm-internetfreigabestufe', 'local_uri': 'http://arkumu.org/data/rsh/properties/khm-internetfreigabestufe' })
    bildbeschreibung_deutsch: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Bildbeschreibung (deutsch)', 'canonical_uri': 'http://arkumu.org/data/properties/bildbeschreibung-deutsch', 'local_uri': 'http://arkumu.org/data/rsh/properties/bildbeschreibung-deutsch' })
    bildbeschreibung_englisch: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Bildbeschreibung (englisch)', 'canonical_uri': 'http://arkumu.org/data/properties/bildbeschreibung-englisch', 'local_uri': 'http://arkumu.org/data/rsh/properties/bildbeschreibung-englisch' })
    datensatz_id_beim_einlieferer: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Datensatz-ID beim Einlieferer', 'canonical_uri': 'http://arkumu.org/data/properties/datensatz-id-beim-einlieferer', 'local_uri': 'http://arkumu.org/data/rsh/properties/datensatz-id-beim-einlieferer' })
    deutsche_inhaltliche_beschreibung: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Deutsche inhaltliche Beschreibung', 'canonical_uri': 'http://arkumu.org/data/properties/deutsche-inhaltliche-beschreibung', 'local_uri': 'http://arkumu.org/data/rsh/properties/deutsche-inhaltliche-beschreibung' })
    englische_inhaltliche_beschreibung: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Englische inhaltliche Beschreibung', 'canonical_uri': 'http://arkumu.org/data/properties/englische-inhaltliche-beschreibung', 'local_uri': 'http://arkumu.org/data/rsh/properties/englische-inhaltliche-beschreibung' })
    wesentliche_eigenschaften_deutsch: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Wesentliche Eigenschaften (deutsch)', 'canonical_uri': 'http://arkumu.org/data/properties/wesentliche-eigenschaften-deutsch', 'local_uri': 'http://arkumu.org/data/rsh/properties/wesentliche-eigenschaften-deutsch' })
    datensatzerstellung_beim_einlieferer: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Datensatzerstellung beim Einlieferer', 'canonical_uri': 'http://arkumu.org/data/properties/datensatzerstellung-beim-einlieferer', 'local_uri': 'http://arkumu.org/data/rsh/properties/datensatzerstellung-beim-einlieferer' })
    wesentliche_eigenschaften_englisch: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Wesentliche Eigenschaften (englisch)', 'canonical_uri': 'http://arkumu.org/data/properties/wesentliche-eigenschaften-englisch', 'local_uri': 'http://arkumu.org/data/rsh/properties/wesentliche-eigenschaften-englisch' })
    letzte_datensatzmodifikation_beim_einlieferer: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Letzte Datensatzmodifikation beim Einlieferer', 'canonical_uri': 'http://arkumu.org/data/properties/letzte-datensatzmodifikation-beim-einlieferer', 'local_uri': 'http://arkumu.org/data/rsh/properties/letzte-datensatzmodifikation-beim-einlieferer' })

@dataclass
class Projektkategorie:
    """Dataset Projektkategorie (canonical http://arkumu.org/data/types/projektkategorie)"""
    aat_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'AAT-ID', 'canonical_uri': 'http://arkumu.org/data/properties/aat-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/aat-id' })
    synonyme: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Synonyme', 'canonical_uri': 'http://arkumu.org/data/properties/synonyme', 'local_uri': 'http://arkumu.org/data/rsh/properties/synonyme' })
    gnd_nummer: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'GND-Nummer', 'canonical_uri': 'http://arkumu.org/data/properties/gnd-nummer', 'local_uri': 'http://arkumu.org/data/rsh/properties/gnd-nummer' })
    wikidata_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Wikidata-ID', 'canonical_uri': 'http://arkumu.org/data/properties/wikidata-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/wikidata-id' })
    projektkategorie_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Projektkategorie-ID', 'canonical_uri': 'http://arkumu.org/data/properties/projektkategorie-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/projektkategorie-id' })
    filmportal_kategorie_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Filmportal-Kategorie-ID', 'canonical_uri': 'http://arkumu.org/data/properties/filmportal-kategorie-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/filmportal-kategorie-id' })
    deutscher_name_der_projektkategorie_breadcrumb: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Deutscher Name der Projektkategorie (Breadcrumb)', 'canonical_uri': 'http://arkumu.org/data/properties/deutscher-name-der-projektkategorie-breadcrumb', 'local_uri': 'http://arkumu.org/data/rsh/properties/deutscher-name-der-projektkategorie-breadcrumb' })
    englischer_name_der_projektkategorie_breadcrumb: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Englischer Name der Projektkategorie (Breadcrumb)', 'canonical_uri': 'http://arkumu.org/data/properties/englischer-name-der-projektkategorie-breadcrumb', 'local_uri': 'http://arkumu.org/data/rsh/properties/englischer-name-der-projektkategorie-breadcrumb' })

@dataclass
class PhysischesObjekt:
    """Dataset Physisches_Objekt (canonical http://arkumu.org/data/types/physisches-objekt)"""
    ma_e: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Maße', 'canonical_uri': 'http://arkumu.org/data/properties/masse', 'local_uri': 'http://arkumu.org/data/rsh/properties/masse' })
    besitzerin: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'BesitzerIn', 'canonical_uri': 'http://arkumu.org/data/properties/besitzerin', 'local_uri': 'http://arkumu.org/data/rsh/properties/besitzerin' })
    provinienz: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Provinienz', 'canonical_uri': 'http://arkumu.org/data/properties/provinienz', 'local_uri': 'http://arkumu.org/data/rsh/properties/provinienz' })
    eigent_merin: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'EigentümerIn', 'canonical_uri': 'http://arkumu.org/data/properties/eigentuemerin', 'local_uri': 'http://arkumu.org/data/rsh/properties/eigentuemerin' })
    aufbewahrungsort: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Aufbewahrungsort', 'canonical_uri': 'http://arkumu.org/data/properties/aufbewahrungsort', 'local_uri': 'http://arkumu.org/data/rsh/properties/aufbewahrungsort' })
    technikschlagwort: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Technikschlagwort', 'canonical_uri': 'http://arkumu.org/data/properties/technikschlagwort', 'local_uri': 'http://arkumu.org/data/rsh/properties/technikschlagwort' })
    materialschlagwort: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Materialschlagwort', 'canonical_uri': 'http://arkumu.org/data/properties/materialschlagwort', 'local_uri': 'http://arkumu.org/data/rsh/properties/materialschlagwort' })
    deutscher_kommentar: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Deutscher Kommentar', 'canonical_uri': 'http://arkumu.org/data/properties/deutscher-kommentar', 'local_uri': 'http://arkumu.org/data/rsh/properties/deutscher-kommentar' })
    deutsche_bezeichnung: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Deutsche Bezeichnung', 'canonical_uri': 'http://arkumu.org/data/properties/deutsche-bezeichnung', 'local_uri': 'http://arkumu.org/data/rsh/properties/deutsche-bezeichnung' })
    englischer_kommentar: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Englischer Kommentar', 'canonical_uri': 'http://arkumu.org/data/properties/englischer-kommentar', 'local_uri': 'http://arkumu.org/data/rsh/properties/englischer-kommentar' })
    physisches_objekt_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Physisches Objekt-ID', 'canonical_uri': 'http://arkumu.org/data/properties/physisches-objekt-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/physisches-objekt-id' })
    deutsche_beschreibung: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Deutsche Beschreibung', 'canonical_uri': 'http://arkumu.org/data/properties/deutsche-beschreibung', 'local_uri': 'http://arkumu.org/data/rsh/properties/deutsche-beschreibung' })
    englische_bezeichnung: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Englische Bezeichnung', 'canonical_uri': 'http://arkumu.org/data/properties/englische-bezeichnung', 'local_uri': 'http://arkumu.org/data/rsh/properties/englische-bezeichnung' })
    englische_beschreibung: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Englische Beschreibung', 'canonical_uri': 'http://arkumu.org/data/properties/englische-beschreibung', 'local_uri': 'http://arkumu.org/data/rsh/properties/englische-beschreibung' })
    erhaltungszustand_deutsch: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Erhaltungszustand (deutsch)', 'canonical_uri': 'http://arkumu.org/data/properties/erhaltungszustand-deutsch', 'local_uri': 'http://arkumu.org/data/rsh/properties/erhaltungszustand-deutsch' })
    erhaltungszustand_englisch: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Erhaltungszustand (englisch)', 'canonical_uri': 'http://arkumu.org/data/properties/erhaltungszustand-englisch', 'local_uri': 'http://arkumu.org/data/rsh/properties/erhaltungszustand-englisch' })
    klassifizierendes_schlagwort: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Klassifizierendes Schlagwort', 'canonical_uri': 'http://arkumu.org/data/properties/klassifizierendes-schlagwort', 'local_uri': 'http://arkumu.org/data/rsh/properties/klassifizierendes-schlagwort' })
    externe_inventar_signaturnummer: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Externe Inventar-Signaturnummer', 'canonical_uri': 'http://arkumu.org/data/properties/externe-inventar-signaturnummer', 'local_uri': 'http://arkumu.org/data/rsh/properties/externe-inventar-signaturnummer' })
    technischer_kommentar_deutsch: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Technischer Kommentar (deutsch)', 'canonical_uri': 'http://arkumu.org/data/properties/technischer-kommentar-deutsch', 'local_uri': 'http://arkumu.org/data/rsh/properties/technischer-kommentar-deutsch' })
    technischer_kommentar_englisch: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Technischer Kommentar (englisch)', 'canonical_uri': 'http://arkumu.org/data/properties/technischer-kommentar-englisch', 'local_uri': 'http://arkumu.org/data/rsh/properties/technischer-kommentar-englisch' })

@dataclass
class Technikschlagwort:
    """Dataset Technikschlagwort (canonical http://arkumu.org/data/types/technikschlagwort)"""
    wikidata_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Wikidata-ID', 'canonical_uri': 'http://arkumu.org/data/properties/wikidata-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/wikidata-id' })
    technikschlagwort_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Technikschlagwort-ID', 'canonical_uri': 'http://arkumu.org/data/properties/technikschlagwort-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/technikschlagwort-id' })
    deutsches_wikidata_label: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Deutsches Wikidata-Label', 'canonical_uri': 'http://arkumu.org/data/properties/deutsches-wikidata-label', 'local_uri': 'http://arkumu.org/data/rsh/properties/deutsches-wikidata-label' })

@dataclass
class AlternativerTitel:
    """Dataset Alternativer_Titel (canonical http://arkumu.org/data/types/alternativer-titel)"""
    alternativer_titel: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Alternativer Titel', 'canonical_uri': 'http://arkumu.org/data/properties/alternativer-titel', 'local_uri': 'http://arkumu.org/data/rsh/properties/alternativer-titel' })
    alternativer_untertitel: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Alternativer Untertitel', 'canonical_uri': 'http://arkumu.org/data/properties/alternativer-untertitel', 'local_uri': 'http://arkumu.org/data/rsh/properties/alternativer-untertitel' })
    alternativer_titel_set_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Alternativer Titel-Set-ID', 'canonical_uri': 'http://arkumu.org/data/properties/alternativer-titel-set-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/alternativer-titel-set-id' })
    sprache_des_alternativen_titels: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Sprache des Alternativen Titels', 'canonical_uri': 'http://arkumu.org/data/properties/sprache-des-alternativen-titels', 'local_uri': 'http://arkumu.org/data/rsh/properties/sprache-des-alternativen-titels' })
    sprache_des_alternativen_untertitels: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Sprache des Alternativen Untertitels', 'canonical_uri': 'http://arkumu.org/data/properties/sprache-des-alternativen-untertitels', 'local_uri': 'http://arkumu.org/data/rsh/properties/sprache-des-alternativen-untertitels' })

@dataclass
class Materialschlagwort:
    """Dataset Materialschlagwort (canonical http://arkumu.org/data/types/materialschlagwort)"""
    wikidata_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Wikidata-ID', 'canonical_uri': 'http://arkumu.org/data/properties/wikidata-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/wikidata-id' })
    materialschlagwort_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Materialschlagwort-ID', 'canonical_uri': 'http://arkumu.org/data/properties/materialschlagwort-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/materialschlagwort-id' })
    deutsches_wikidata_label: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Deutsches Wikidata-Label', 'canonical_uri': 'http://arkumu.org/data/properties/deutsches-wikidata-label', 'local_uri': 'http://arkumu.org/data/rsh/properties/deutsches-wikidata-label' })

@dataclass
class Projekteigenschaft:
    """Dataset Projekteigenschaft (canonical http://arkumu.org/data/types/projekteigenschaft)"""
    einheit: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Einheit', 'canonical_uri': 'http://arkumu.org/data/properties/einheit', 'local_uri': 'http://arkumu.org/data/rsh/properties/einheit' })
    gnd_nummer: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'GND-Nummer', 'canonical_uri': 'http://arkumu.org/data/properties/gnd-nummer', 'local_uri': 'http://arkumu.org/data/rsh/properties/gnd-nummer' })
    wikidata_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Wikidata-ID', 'canonical_uri': 'http://arkumu.org/data/properties/wikidata-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/wikidata-id' })
    projekteigenschaft_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Projekteigenschaft-ID', 'canonical_uri': 'http://arkumu.org/data/properties/projekteigenschaft-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/projekteigenschaft-id' })
    kurzbeschreibung_deutsch: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Kurzbeschreibung (deutsch)', 'canonical_uri': 'http://arkumu.org/data/properties/kurzbeschreibung-deutsch', 'local_uri': 'http://arkumu.org/data/rsh/properties/kurzbeschreibung-deutsch' })
    kurzbeschreibung_englisch: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Kurzbeschreibung (englisch)', 'canonical_uri': 'http://arkumu.org/data/properties/kurzbeschreibung-englisch', 'local_uri': 'http://arkumu.org/data/rsh/properties/kurzbeschreibung-englisch' })
    deutscher_name_der_projekteigenschaft: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Deutscher Name der Projekteigenschaft', 'canonical_uri': 'http://arkumu.org/data/properties/deutscher-name-der-projekteigenschaft', 'local_uri': 'http://arkumu.org/data/rsh/properties/deutscher-name-der-projekteigenschaft' })
    englischer_name_der_projekteigenschaft: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Englischer Name der Projekteigenschaft', 'canonical_uri': 'http://arkumu.org/data/properties/englischer-name-der-projekteigenschaft', 'local_uri': 'http://arkumu.org/data/rsh/properties/englischer-name-der-projekteigenschaft' })

@dataclass
class Ereigniseigenschaft:
    """Dataset Ereigniseigenschaft (canonical http://arkumu.org/data/types/ereigniseigenschaft)"""
    einheit: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Einheit', 'canonical_uri': 'http://arkumu.org/data/properties/einheit', 'local_uri': 'http://arkumu.org/data/rsh/properties/einheit' })
    gnd_nummer: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'GND-Nummer', 'canonical_uri': 'http://arkumu.org/data/properties/gnd-nummer', 'local_uri': 'http://arkumu.org/data/rsh/properties/gnd-nummer' })
    wikidata_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Wikidata-ID', 'canonical_uri': 'http://arkumu.org/data/properties/wikidata-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/wikidata-id' })
    ereigniseigenschaft_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Ereigniseigenschaft-ID', 'canonical_uri': 'http://arkumu.org/data/properties/ereigniseigenschaft-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/ereigniseigenschaft-id' })
    kurzbeschreibung_deutsch: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Kurzbeschreibung (deutsch)', 'canonical_uri': 'http://arkumu.org/data/properties/kurzbeschreibung-deutsch', 'local_uri': 'http://arkumu.org/data/rsh/properties/kurzbeschreibung-deutsch' })
    kurzbeschreibung_englisch: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Kurzbeschreibung (englisch)', 'canonical_uri': 'http://arkumu.org/data/properties/kurzbeschreibung-englisch', 'local_uri': 'http://arkumu.org/data/rsh/properties/kurzbeschreibung-englisch' })
    deutscher_name_der_ereigniseigenschaft: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Deutscher Name der Ereigniseigenschaft', 'canonical_uri': 'http://arkumu.org/data/properties/deutscher-name-der-ereigniseigenschaft', 'local_uri': 'http://arkumu.org/data/rsh/properties/deutscher-name-der-ereigniseigenschaft' })
    englischer_name_der_ereigniseigenschaft: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Englischer Name der Ereigniseigenschaft', 'canonical_uri': 'http://arkumu.org/data/properties/englischer-name-der-ereigniseigenschaft', 'local_uri': 'http://arkumu.org/data/rsh/properties/englischer-name-der-ereigniseigenschaft' })

@dataclass
class InformationstrGer:
    """Dataset Informationsträger (canonical http://arkumu.org/data/types/informationstraeger)"""
    ma_e: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Maße', 'canonical_uri': 'http://arkumu.org/data/properties/masse', 'local_uri': 'http://arkumu.org/data/rsh/properties/masse' })
    normdatei: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Normdatei', 'canonical_uri': 'http://arkumu.org/data/properties/normdatei', 'local_uri': 'http://arkumu.org/data/rsh/properties/normdatei' })
    besitzerin: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'BesitzerIn', 'canonical_uri': 'http://arkumu.org/data/properties/besitzerin', 'local_uri': 'http://arkumu.org/data/rsh/properties/besitzerin' })
    provenienz: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Provenienz', 'canonical_uri': 'http://arkumu.org/data/properties/provenienz', 'local_uri': 'http://arkumu.org/data/rsh/properties/provenienz' })
    kompilation: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Kompilation', 'canonical_uri': 'http://arkumu.org/data/properties/kompilation', 'local_uri': 'http://arkumu.org/data/rsh/properties/kompilation' })
    eigent_merin: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'EigentümerIn', 'canonical_uri': 'http://arkumu.org/data/properties/eigentuemerin', 'local_uri': 'http://arkumu.org/data/rsh/properties/eigentuemerin' })
    sprachfassung: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Sprachfassung', 'canonical_uri': 'http://arkumu.org/data/properties/sprachfassung', 'local_uri': 'http://arkumu.org/data/rsh/properties/sprachfassung' })
    originalsprache: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Originalsprache', 'canonical_uri': 'http://arkumu.org/data/properties/originalsprache', 'local_uri': 'http://arkumu.org/data/rsh/properties/originalsprache' })
    aufbewahrungsort: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Aufbewahrungsort', 'canonical_uri': 'http://arkumu.org/data/properties/aufbewahrungsort', 'local_uri': 'http://arkumu.org/data/rsh/properties/aufbewahrungsort' })
    kompilationstitel: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Kompilationstitel', 'canonical_uri': 'http://arkumu.org/data/properties/kompilationstitel', 'local_uri': 'http://arkumu.org/data/rsh/properties/kompilationstitel' })
    untertitelsprache: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Untertitelsprache', 'canonical_uri': 'http://arkumu.org/data/properties/untertitelsprache', 'local_uri': 'http://arkumu.org/data/rsh/properties/untertitelsprache' })
    interner_kommentar: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Interner Kommentar', 'canonical_uri': 'http://arkumu.org/data/properties/interner-kommentar', 'local_uri': 'http://arkumu.org/data/rsh/properties/interner-kommentar' })
    materialschlagwort: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Materialschlagwort', 'canonical_uri': 'http://arkumu.org/data/properties/materialschlagwort', 'local_uri': 'http://arkumu.org/data/rsh/properties/materialschlagwort' })
    deutscher_kommentar: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Deutscher Kommentar', 'canonical_uri': 'http://arkumu.org/data/properties/deutscher-kommentar', 'local_uri': 'http://arkumu.org/data/rsh/properties/deutscher-kommentar' })
    englischer_kommentar: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Englischer Kommentar', 'canonical_uri': 'http://arkumu.org/data/properties/englischer-kommentar', 'local_uri': 'http://arkumu.org/data/rsh/properties/englischer-kommentar' })
    label_handelsmarke: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Label (Handelsmarke)', 'canonical_uri': 'http://arkumu.org/data/properties/label-handelsmarke', 'local_uri': 'http://arkumu.org/data/rsh/properties/label-handelsmarke' })
    deutsche_beschreibung: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Deutsche Beschreibung', 'canonical_uri': 'http://arkumu.org/data/properties/deutsche-beschreibung', 'local_uri': 'http://arkumu.org/data/rsh/properties/deutsche-beschreibung' })
    englische_beschreibung: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Englische Beschreibung', 'canonical_uri': 'http://arkumu.org/data/properties/englische-beschreibung', 'local_uri': 'http://arkumu.org/data/rsh/properties/englische-beschreibung' })
    informationstr_ger_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Informationsträger-ID', 'canonical_uri': 'http://arkumu.org/data/properties/informationstraeger-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/informationstraeger-id' })
    informationstr_gertyp: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Informationsträgertyp', 'canonical_uri': 'http://arkumu.org/data/properties/informationstraegertyp', 'local_uri': 'http://arkumu.org/data/rsh/properties/informationstraegertyp' })
    kompilations_reihennummer: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Kompilations-Reihennummer', 'canonical_uri': 'http://arkumu.org/data/properties/kompilations-reihennummer', 'local_uri': 'http://arkumu.org/data/rsh/properties/kompilations-reihennummer' })
    erhaltungszustand_deutsch: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Erhaltungszustand (deutsch)', 'canonical_uri': 'http://arkumu.org/data/properties/erhaltungszustand-deutsch', 'local_uri': 'http://arkumu.org/data/rsh/properties/erhaltungszustand-deutsch' })
    erhaltungszustand_englisch: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Erhaltungszustand (englisch)', 'canonical_uri': 'http://arkumu.org/data/properties/erhaltungszustand-englisch', 'local_uri': 'http://arkumu.org/data/rsh/properties/erhaltungszustand-englisch' })
    deutsche_produkt_bezeichnung: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Deutsche (Produkt-) Bezeichnung', 'canonical_uri': 'http://arkumu.org/data/properties/deutsche-produkt-bezeichnung', 'local_uri': 'http://arkumu.org/data/rsh/properties/deutsche-produkt-bezeichnung' })
    externe_inventar_signaturnummer: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Externe Inventar-Signaturnummer', 'canonical_uri': 'http://arkumu.org/data/properties/externe-inventar-signaturnummer', 'local_uri': 'http://arkumu.org/data/rsh/properties/externe-inventar-signaturnummer' })
    englische_produkt_bezeichnung: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Englische (Produkt-) Bezeichnung', 'canonical_uri': 'http://arkumu.org/data/properties/englische-produkt-bezeichnung', 'local_uri': 'http://arkumu.org/data/rsh/properties/englische-produkt-bezeichnung' })

@dataclass
class Ereignisbeschreibung:
    """Dataset Ereignisbeschreibung (canonical http://arkumu.org/data/types/ereignisbeschreibung)"""
    sortierung: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Sortierung', 'canonical_uri': 'http://arkumu.org/data/properties/sortierung', 'local_uri': 'http://arkumu.org/data/rsh/properties/sortierung' })
    ereignisbeschreibung: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Ereignisbeschreibung', 'canonical_uri': 'http://arkumu.org/data/properties/ereignisbeschreibung', 'local_uri': 'http://arkumu.org/data/rsh/properties/ereignisbeschreibung' })
    ereignisbeschreibung_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Ereignisbeschreibung-ID', 'canonical_uri': 'http://arkumu.org/data/properties/ereignisbeschreibung-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/ereignisbeschreibung-id' })
    sprache_der_ereignisbeschreibung: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Sprache der Ereignisbeschreibung', 'canonical_uri': 'http://arkumu.org/data/properties/sprache-der-ereignisbeschreibung', 'local_uri': 'http://arkumu.org/data/rsh/properties/sprache-der-ereignisbeschreibung' })

@dataclass
class Organisationseinheit:
    """Dataset Organisationseinheit (canonical http://arkumu.org/data/types/organisationseinheit)"""
    deutsche_beschreibung: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Deutsche Beschreibung', 'canonical_uri': 'http://arkumu.org/data/properties/deutsche-beschreibung', 'local_uri': 'http://arkumu.org/data/rsh/properties/deutsche-beschreibung' })
    englische_beschreibung: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Englische Beschreibung', 'canonical_uri': 'http://arkumu.org/data/properties/englische-beschreibung', 'local_uri': 'http://arkumu.org/data/rsh/properties/englische-beschreibung' })
    organisationseinheit_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Organisationseinheit-ID', 'canonical_uri': 'http://arkumu.org/data/properties/organisationseinheit-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/organisationseinheit-id' })
    deutscher_name_der_organisationseinheit_breadcrumb: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Deutscher Name der Organisationseinheit (Breadcrumb)', 'canonical_uri': 'http://arkumu.org/data/properties/deutscher-name-der-organisationseinheit-breadcrumb', 'local_uri': 'http://arkumu.org/data/rsh/properties/deutscher-name-der-organisationseinheit-breadcrumb' })
    englischer_name_der_organisationseinheit_breadcrumb: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Englischer Name der Organisationseinheit (Breadcrumb)', 'canonical_uri': 'http://arkumu.org/data/properties/englischer-name-der-organisationseinheit-breadcrumb', 'local_uri': 'http://arkumu.org/data/rsh/properties/englischer-name-der-organisationseinheit-breadcrumb' })

@dataclass
class EquipmentUndSoftware:
    """Dataset Equipment_und_Software (canonical http://arkumu.org/data/types/equipment-und-software)"""
    gnd_nummer: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'GND-Nummer', 'canonical_uri': 'http://arkumu.org/data/properties/gnd-nummer', 'local_uri': 'http://arkumu.org/data/rsh/properties/gnd-nummer' })
    hersteller: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Hersteller', 'canonical_uri': 'http://arkumu.org/data/properties/hersteller', 'local_uri': 'http://arkumu.org/data/rsh/properties/hersteller' })
    wikidata_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Wikidata-ID', 'canonical_uri': 'http://arkumu.org/data/properties/wikidata-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/wikidata-id' })
    equipmentart: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Equipmentart', 'canonical_uri': 'http://arkumu.org/data/properties/equipmentart', 'local_uri': 'http://arkumu.org/data/rsh/properties/equipmentart' })
    deutsche_beschreibung: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Deutsche Beschreibung', 'canonical_uri': 'http://arkumu.org/data/properties/deutsche-beschreibung', 'local_uri': 'http://arkumu.org/data/rsh/properties/deutsche-beschreibung' })
    englische_beschreibung: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Englische Beschreibung', 'canonical_uri': 'http://arkumu.org/data/properties/englische-beschreibung', 'local_uri': 'http://arkumu.org/data/rsh/properties/englische-beschreibung' })
    equipment_und_software_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Equipment und Software-ID', 'canonical_uri': 'http://arkumu.org/data/properties/equipment-und-software-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/equipment-und-software-id' })
    deutsche_produkt_bezeichnung: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Deutsche (Produkt-Bezeichnung)', 'canonical_uri': 'http://arkumu.org/data/properties/deutsche-produkt-bezeichnung', 'local_uri': 'http://arkumu.org/data/rsh/properties/deutsche-produkt-bezeichnung' })
    englische_produkt_bezeichnung: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Englische (Produkt-Bezeichnung)', 'canonical_uri': 'http://arkumu.org/data/properties/englische-produkt-bezeichnung', 'local_uri': 'http://arkumu.org/data/rsh/properties/englische-produkt-bezeichnung' })

@dataclass
class InformationstrGertyp:
    """Dataset Informationsträgertyp (canonical http://arkumu.org/data/types/informationstraegertyp)"""
    aat_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'AAT-ID', 'canonical_uri': 'http://arkumu.org/data/properties/aat-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/aat-id' })
    gnd_nummer: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'GND-Nummer', 'canonical_uri': 'http://arkumu.org/data/properties/gnd-nummer', 'local_uri': 'http://arkumu.org/data/rsh/properties/gnd-nummer' })
    pbcore_link: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'PBCore-Link', 'canonical_uri': 'http://arkumu.org/data/properties/pbcore-link', 'local_uri': 'http://arkumu.org/data/rsh/properties/pbcore-link' })
    wikidata_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Wikidata-ID', 'canonical_uri': 'http://arkumu.org/data/properties/wikidata-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/wikidata-id' })
    informationstr_gertyp_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Informationsträgertyp-ID', 'canonical_uri': 'http://arkumu.org/data/properties/informationstraegertyp-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/informationstraegertyp-id' })
    deutscher_name_des_informationstr_gertyps_breadcrumb: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Deutscher Name des Informationsträgertyps (Breadcrumb)', 'canonical_uri': 'http://arkumu.org/data/properties/deutscher-name-des-informationstraegertyps-breadcrumb', 'local_uri': 'http://arkumu.org/data/rsh/properties/deutscher-name-des-informationstraegertyps-breadcrumb' })
    englischer_name_des_informationstr_gertyps_breadcrumb: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Englischer Name des Informationsträgertyps (Breadcrumb)', 'canonical_uri': 'http://arkumu.org/data/properties/englischer-name-des-informationstraegertyps-breadcrumb', 'local_uri': 'http://arkumu.org/data/rsh/properties/englischer-name-des-informationstraegertyps-breadcrumb' })

@dataclass
class ProduktidKreuztabelle:
    """Dataset ProduktID_Kreuztabelle (canonical http://arkumu.org/data/types/produktid-kreuztabelle)"""
    produkt_id_typ: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Produkt ID-Typ', 'canonical_uri': 'http://arkumu.org/data/properties/produkt-id-typ', 'local_uri': 'http://arkumu.org/data/rsh/properties/produkt-id-typ' })
    produkt_id_wert: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Produkt ID-Wert', 'canonical_uri': 'http://arkumu.org/data/properties/produkt-id-wert', 'local_uri': 'http://arkumu.org/data/rsh/properties/produkt-id-wert' })
    informationstr_ger: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Informationsträger', 'canonical_uri': 'http://arkumu.org/data/properties/informationstraeger', 'local_uri': 'http://arkumu.org/data/rsh/properties/informationstraeger' })
    informationstr_ger_produkt_id_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Informationsträger-Produkt ID-ID', 'canonical_uri': 'http://arkumu.org/data/properties/informationstraeger-produkt-id-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/informationstraeger-produkt-id-id' })

@dataclass
class DigitalesObjektLizenz:
    """Dataset Digitales-Objekt-Lizenz (canonical http://arkumu.org/data/types/digitales-objekt-lizenz)"""
    uri: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'URI', 'canonical_uri': 'http://arkumu.org/data/properties/uri', 'local_uri': 'http://arkumu.org/data/rsh/properties/uri' })
    deutscher_anzeigetext: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Deutscher Anzeigetext', 'canonical_uri': 'http://arkumu.org/data/properties/deutscher-anzeigetext', 'local_uri': 'http://arkumu.org/data/rsh/properties/deutscher-anzeigetext' })
    englischer_anzeigetext: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Englischer Anzeigetext', 'canonical_uri': 'http://arkumu.org/data/properties/englischer-anzeigetext', 'local_uri': 'http://arkumu.org/data/rsh/properties/englischer-anzeigetext' })
    deutscher_name_der_lizenz: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Deutscher Name der Lizenz', 'canonical_uri': 'http://arkumu.org/data/properties/deutscher-name-der-lizenz', 'local_uri': 'http://arkumu.org/data/rsh/properties/deutscher-name-der-lizenz' })
    digitales_objekt_lizenz_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Digitales-Objekt-Lizenz-ID', 'canonical_uri': 'http://arkumu.org/data/properties/digitales-objekt-lizenz-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/digitales-objekt-lizenz-id' })
    englischer_name_der_lizenz: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Englischer Name der Lizenz', 'canonical_uri': 'http://arkumu.org/data/properties/englischer-name-der-lizenz', 'local_uri': 'http://arkumu.org/data/rsh/properties/englischer-name-der-lizenz' })
    zugeh_riges_rechtestatement: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Zugehöriges Rechtestatement', 'canonical_uri': 'http://arkumu.org/data/properties/zugehoeriges-rechtestatement', 'local_uri': 'http://arkumu.org/data/rsh/properties/zugehoeriges-rechtestatement' })

@dataclass
class EinlieferndeHochschule:
    """Dataset Einliefernde_Hochschule (canonical http://arkumu.org/data/types/einliefernde-hochschule)"""
    gnd_nummer: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'GND-Nummer', 'canonical_uri': 'http://arkumu.org/data/properties/gnd-nummer', 'local_uri': 'http://arkumu.org/data/rsh/properties/gnd-nummer' })
    wikidata_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Wikidata-ID', 'canonical_uri': 'http://arkumu.org/data/properties/wikidata-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/wikidata-id' })
    einliefernde_hochschule_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Einliefernde Hochschule-ID', 'canonical_uri': 'http://arkumu.org/data/properties/einliefernde-hochschule-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/einliefernde-hochschule-id' })
    deutscher_name_der_einliefernden_hochschule: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Deutscher Name der Einliefernden Hochschule', 'canonical_uri': 'http://arkumu.org/data/properties/deutscher-name-der-einliefernden-hochschule', 'local_uri': 'http://arkumu.org/data/rsh/properties/deutscher-name-der-einliefernden-hochschule' })
    englischer_name_der_einliefernden_hochschule: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Englischer Name der Einliefernden Hochschule', 'canonical_uri': 'http://arkumu.org/data/properties/englischer-name-der-einliefernden-hochschule', 'local_uri': 'http://arkumu.org/data/rsh/properties/englischer-name-der-einliefernden-hochschule' })

@dataclass
class BestehenderLizenzvertrag:
    """Dataset Bestehender_Lizenzvertrag (canonical http://arkumu.org/data/types/bestehender-lizenzvertrag)"""
    pdf: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'PDF', 'canonical_uri': 'http://arkumu.org/data/properties/pdf', 'local_uri': 'http://arkumu.org/data/rsh/properties/pdf' })
    verantwortliche_hochschule: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Verantwortliche Hochschule', 'canonical_uri': 'http://arkumu.org/data/properties/verantwortliche-hochschule', 'local_uri': 'http://arkumu.org/data/rsh/properties/verantwortliche-hochschule' })
    bestehender_lizenzvertrag_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Bestehender Lizenzvertrag-ID', 'canonical_uri': 'http://arkumu.org/data/properties/bestehender-lizenzvertrag-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/bestehender-lizenzvertrag-id' })
    deutsche_bezeichnung_des_lizenzvertrags: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Deutsche Bezeichnung des Lizenzvertrags', 'canonical_uri': 'http://arkumu.org/data/properties/deutsche-bezeichnung-des-lizenzvertrags', 'local_uri': 'http://arkumu.org/data/rsh/properties/deutsche-bezeichnung-des-lizenzvertrags' })
    englische_bezeichnung_des_lizenzvertrags: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Englische Bezeichnung des Lizenzvertrags', 'canonical_uri': 'http://arkumu.org/data/properties/englische-bezeichnung-des-lizenzvertrags', 'local_uri': 'http://arkumu.org/data/rsh/properties/englische-bezeichnung-des-lizenzvertrags' })
    w_hlt_automatisch_folgenden_lizenzstatus_aus: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Wählt automatisch folgenden Lizenzstatus aus', 'canonical_uri': 'http://arkumu.org/data/properties/waehlt-automatisch-folgenden-lizenzstatus-aus', 'local_uri': 'http://arkumu.org/data/rsh/properties/waehlt-automatisch-folgenden-lizenzstatus-aus' })
    w_hlt_automatisch_folgenden_anzeigestatus_aus: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Wählt automatisch folgenden Anzeigestatus aus', 'canonical_uri': 'http://arkumu.org/data/properties/waehlt-automatisch-folgenden-anzeigestatus-aus', 'local_uri': 'http://arkumu.org/data/rsh/properties/waehlt-automatisch-folgenden-anzeigestatus-aus' })

@dataclass
class ProjektProjektKreuztabelle:
    """Dataset Projekt_Projekt_Kreuztabelle (canonical http://arkumu.org/data/types/projekt-projekt-kreuztabelle)"""
    beziehung: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Beziehung', 'canonical_uri': 'http://arkumu.org/data/properties/beziehung', 'local_uri': 'http://arkumu.org/data/rsh/properties/beziehung' })
    ausgangsprojekt: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Ausgangsprojekt', 'canonical_uri': 'http://arkumu.org/data/properties/ausgangsprojekt', 'local_uri': 'http://arkumu.org/data/rsh/properties/ausgangsprojekt' })
    projekt_projekt_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Projekt-Projekt-ID', 'canonical_uri': 'http://arkumu.org/data/properties/projekt-projekt-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/projekt-projekt-id' })
    verkn_pftes_projekt: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Verknüpftes Projekt', 'canonical_uri': 'http://arkumu.org/data/properties/verknuepftes-projekt', 'local_uri': 'http://arkumu.org/data/rsh/properties/verknuepftes-projekt' })

@dataclass
class AkteurinAkteurinKreuztabelle:
    """Dataset AkteurIn_AkteurIn_Kreuztabelle (canonical http://arkumu.org/data/types/akteurin-akteurin-kreuztabelle)"""
    beziehung: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Beziehung', 'canonical_uri': 'http://arkumu.org/data/properties/beziehung', 'local_uri': 'http://arkumu.org/data/rsh/properties/beziehung' })
    ausgangsakteurin: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'AusgangsakteurIn', 'canonical_uri': 'http://arkumu.org/data/properties/ausgangsakteurin', 'local_uri': 'http://arkumu.org/data/rsh/properties/ausgangsakteurin' })
    akteurin_akteurin_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'AkteurIn-AkteurIn-ID', 'canonical_uri': 'http://arkumu.org/data/properties/akteurin-akteurin-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/akteurin-akteurin-id' })
    verkn_pfter_akteurin: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'VerknüpfteR AkteurIn', 'canonical_uri': 'http://arkumu.org/data/properties/verknuepfter-akteurin', 'local_uri': 'http://arkumu.org/data/rsh/properties/verknuepfter-akteurin' })

@dataclass
class AkteurinEreignisKreuztabelle:
    """Dataset AkteurIn_Ereignis_Kreuztabelle (canonical http://arkumu.org/data/types/akteurin-ereignis-kreuztabelle)"""
    im_ereignis: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'im Ereignis', 'canonical_uri': 'http://arkumu.org/data/properties/im-ereignis', 'local_uri': 'http://arkumu.org/data/rsh/properties/im-ereignis' })
    ist_urheberin: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'ist UrheberIn', 'canonical_uri': 'http://arkumu.org/data/properties/ist-urheberin', 'local_uri': 'http://arkumu.org/data/rsh/properties/ist-urheberin' })
    akteurin_im_ereignis: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'AkteurIn im Ereignis', 'canonical_uri': 'http://arkumu.org/data/properties/akteurin-im-ereignis', 'local_uri': 'http://arkumu.org/data/rsh/properties/akteurin-im-ereignis' })
    akteurin_ereignis_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'AkteurIn-Ereignis-ID', 'canonical_uri': 'http://arkumu.org/data/properties/akteurin-ereignis-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/akteurin-ereignis-id' })
    ungesicherte_zuschreibung: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Ungesicherte Zuschreibung', 'canonical_uri': 'http://arkumu.org/data/properties/ungesicherte-zuschreibung', 'local_uri': 'http://arkumu.org/data/rsh/properties/ungesicherte-zuschreibung' })
    besitzt_leistungsschutzrechte: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'besitzt Leistungsschutzrechte', 'canonical_uri': 'http://arkumu.org/data/properties/besitzt-leistungsschutzrechte', 'local_uri': 'http://arkumu.org/data/rsh/properties/besitzt-leistungsschutzrechte' })
    rollen_der_akteurin_im_ereignis: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Rollen der AkteurIn im Ereignis', 'canonical_uri': 'http://arkumu.org/data/properties/rollen-der-akteurin-im-ereignis', 'local_uri': 'http://arkumu.org/data/rsh/properties/rollen-der-akteurin-im-ereignis' })

@dataclass
class EreignisEreignisKreuztabelle:
    """Dataset Ereignis_Ereignis_Kreuztabelle (canonical http://arkumu.org/data/types/ereignis-ereignis-kreuztabelle)"""
    beziehung: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Beziehung', 'canonical_uri': 'http://arkumu.org/data/properties/beziehung', 'local_uri': 'http://arkumu.org/data/rsh/properties/beziehung' })
    ausgangsereignis: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Ausgangsereignis', 'canonical_uri': 'http://arkumu.org/data/properties/ausgangsereignis', 'local_uri': 'http://arkumu.org/data/rsh/properties/ausgangsereignis' })
    ereignis_ereignis_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Ereignis-Ereignis-ID', 'canonical_uri': 'http://arkumu.org/data/properties/ereignis-ereignis-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/ereignis-ereignis-id' })
    verkn_pftes_ereignis: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Verknüpftes Ereignis', 'canonical_uri': 'http://arkumu.org/data/properties/verknuepftes-ereignis', 'local_uri': 'http://arkumu.org/data/rsh/properties/verknuepftes-ereignis' })

@dataclass
class InformationstrGereigenschaft:
    """Dataset Informationsträgereigenschaft (canonical http://arkumu.org/data/types/informationstraegereigenschaft)"""
    wikidata_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Wikidata-ID', 'canonical_uri': 'http://arkumu.org/data/properties/wikidata-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/wikidata-id' })
    kurzbeschreibung_deutsch: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Kurzbeschreibung (deutsch)', 'canonical_uri': 'http://arkumu.org/data/properties/kurzbeschreibung-deutsch', 'local_uri': 'http://arkumu.org/data/rsh/properties/kurzbeschreibung-deutsch' })
    kurzbeschreibung_englisch: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Kurzbeschreibung (englisch)', 'canonical_uri': 'http://arkumu.org/data/properties/kurzbeschreibung-englisch', 'local_uri': 'http://arkumu.org/data/rsh/properties/kurzbeschreibung-englisch' })
    informationstr_gereigenschaft_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Informationsträgereigenschaft-ID', 'canonical_uri': 'http://arkumu.org/data/properties/informationstraegereigenschaft-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/informationstraegereigenschaft-id' })
    deutscher_name_der_informationstr_gereigenschaft: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Deutscher Name der Informationsträgereigenschaft', 'canonical_uri': 'http://arkumu.org/data/properties/deutscher-name-der-informationstraegereigenschaft', 'local_uri': 'http://arkumu.org/data/rsh/properties/deutscher-name-der-informationstraegereigenschaft' })
    englischer_name_der_informationstr_gereigenschaft: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Englischer Name der Informationsträgereigenschaft', 'canonical_uri': 'http://arkumu.org/data/properties/englischer-name-der-informationstraegereigenschaft', 'local_uri': 'http://arkumu.org/data/rsh/properties/englischer-name-der-informationstraegereigenschaft' })

@dataclass
class ProjekteigenschaftKreuztabelle:
    """Dataset Projekteigenschaft_Kreuztabelle (canonical http://arkumu.org/data/types/projekteigenschaft-kreuztabelle)"""
    wert: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Wert', 'canonical_uri': 'http://arkumu.org/data/properties/wert', 'local_uri': 'http://arkumu.org/data/rsh/properties/wert' })
    projekt: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Projekt', 'canonical_uri': 'http://arkumu.org/data/properties/projekt', 'local_uri': 'http://arkumu.org/data/rsh/properties/projekt' })
    eigenschaft: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Eigenschaft', 'canonical_uri': 'http://arkumu.org/data/properties/eigenschaft', 'local_uri': 'http://arkumu.org/data/rsh/properties/eigenschaft' })
    projekt_projekteigenschaft_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Projekt-Projekteigenschaft-ID', 'canonical_uri': 'http://arkumu.org/data/properties/projekt-projekteigenschaft-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/projekt-projekteigenschaft-id' })

@dataclass
class EreigniseigenschaftKreuztabelle:
    """Dataset Ereigniseigenschaft_Kreuztabelle (canonical http://arkumu.org/data/types/ereigniseigenschaft-kreuztabelle)"""
    wert: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Wert', 'canonical_uri': 'http://arkumu.org/data/properties/wert', 'local_uri': 'http://arkumu.org/data/rsh/properties/wert' })
    ereignis: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Ereignis', 'canonical_uri': 'http://arkumu.org/data/properties/ereignis', 'local_uri': 'http://arkumu.org/data/rsh/properties/ereignis' })
    eigenschaft: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Eigenschaft', 'canonical_uri': 'http://arkumu.org/data/properties/eigenschaft', 'local_uri': 'http://arkumu.org/data/rsh/properties/eigenschaft' })
    ereignis_ereigniseigenschaft_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Ereignis-Ereigniseigenschaft-ID', 'canonical_uri': 'http://arkumu.org/data/properties/ereignis-ereigniseigenschaft-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/ereignis-ereigniseigenschaft-id' })

@dataclass
class InformationstrGerKreuztabelle:
    """Dataset Informationsträger_Kreuztabelle (canonical http://arkumu.org/data/types/informationstraeger-kreuztabelle)"""
    wert: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Wert', 'canonical_uri': 'http://arkumu.org/data/properties/wert', 'local_uri': 'http://arkumu.org/data/rsh/properties/wert' })
    eigenschaft: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Eigenschaft', 'canonical_uri': 'http://arkumu.org/data/properties/eigenschaft', 'local_uri': 'http://arkumu.org/data/rsh/properties/eigenschaft' })
    informationstr_ger: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Informationsträger', 'canonical_uri': 'http://arkumu.org/data/properties/informationstraeger', 'local_uri': 'http://arkumu.org/data/rsh/properties/informationstraeger' })
    informationstr_ger_informationstr_gereigenschaft_id: list[str] = field(default_factory=list, metadata={ 'dataset_property': 'Informationsträger-Informationsträgereigenschaft-ID', 'canonical_uri': 'http://arkumu.org/data/properties/informationstraeger-informationstraegereigenschaft-id', 'local_uri': 'http://arkumu.org/data/rsh/properties/informationstraeger-informationstraegereigenschaft-id' })

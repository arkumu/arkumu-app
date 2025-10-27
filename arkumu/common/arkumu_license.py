from __future__ import annotations

import re
from typing import Any, Dict, Optional
from urllib.parse import urlparse

ARKUMU_LICENSE_LABELS: Dict[str, str] = {
    "1": "Lizenz arkumu-A 1.0",
    "2": "Lizenz arkumu-A+B 1.0",
}

ARKUMU_LICENSE_URIS: Dict[str, str] = {
    "1": "https://docs.arkumu.nrw/resolver/arkumu-a-1.0",
    "2": "https://docs.arkumu.nrw/resolver/arkumu-a+b-1.0",
}

ARKUMU_LICENSE_TEXTS: Dict[str, str] = {
    "1": (
        "Die Hochschule erwirbt das einfache (nicht-exklusive) zeitlich, räumlich und inhaltlich unbeschränkte Recht, "
        "das Werk oder werkähnliche \"Projekt\" zum Zweck der Langzeitverfügbarkeit zu vervielfältigen (§16 UrhG), zu "
        "speichern und gegebenenfalls in langzeitstabile Dateiformate zu überführen. Dies umfasst auch das Recht, ein "
        "Werk erstmalig zu digitalisieren oder eine digitale Dokumentation des Werkes zu erstellen. Sofern für Zwecke "
        "der Langzeitverfügbarkeit eine Umwandlung bestehender Dateiformate in andere Dateiformate erforderlich ist und "
        "diese Umwandlung eine Bearbeitung darstellen sollte, werden ebenfalls die für diese Zwecke erforderlichen "
        "Bearbeitungsrechte eingeräumt.\n\n"
        "(Lizenz arkumu-A 1.0)"
    ),
    "2": (
        "Die Hochschule erwirbt das einfache (nicht-exklusive) zeitlich, räumlich und inhaltlich unbeschränkte Recht, "
        "das Werk oder werkähnliche \"Projekt\" zum Zweck der Langzeitverfügbarkeit zu vervielfältigen (§16 UrhG), zu "
        "speichern und gegebenenfalls in langzeitstabile Dateiformate zu überführen. Dies umfasst auch das Recht, ein "
        "Werk erstmalig zu digitalisieren oder eine digitale Dokumentation des Werkes zu erstellen. Sofern für Zwecke "
        "der Langzeitverfügbarkeit eine Umwandlung bestehender Dateiformate in andere Dateiformate erforderlich ist und "
        "diese Umwandlung eine Bearbeitung darstellen sollte, werden ebenfalls die für diese Zwecke erforderlichen "
        "Bearbeitungsrechte eingeräumt.\n\n"
        "Zusätzlich räumt der/die Lizenzgeber:in der Hochschule an dem Werk oder \"Projekt\" das einfache "
        "(nicht-exklusive) zeitlich, räumlich und inhaltlich unbeschränkte Recht ein, das Werk oder \"Projekt\" zu nicht "
        "kommerziellen Zwecken öffentlich zugänglich zu machen (§19a UrhG), d.h. das Werk oder \"Projekt\" der "
        "Öffentlichkeit in einer Weise zugänglich zu machen, dass es Mitgliedern der Öffentlichkeit drahtgebunden und/oder "
        "drahtlos von Orten und Zeiten ihrer Wahl zugänglich ist, über weltweite und/oder räumlich begrenzte, offene und/"
        "oder geschlossene Netzwerke unabhängig von der Art der Übertragungstechnik (analoge, digitale und/oder sonstige "
        "Übertragungstechnik), unabhängig von der Art des Endgeräts (PC, Laptops/Notebooks, Tablet PCs, Smartphones, TV "
        "etc.) und ohne intendierte dauerhafte Speicherung auf dem Endgerät. Diese Nutzungsrechtseinräumung bezieht sich "
        "auch auf derzeit noch nicht bekannte Nutzungsarten.\n\n"
        "Sofern für Zwecke der öffentlichen Zugänglichmachung eine Umwandlung bestehender Dateiformate in andere "
        "Dateiformate erforderlich ist und diese Umwandlung eine Bearbeitung darstellen sollte, räumt der/die "
        "Lizenzgeber:in der Hochschule für diese Zwecke die dafür erforderlichen Bearbeitungsrechte ein.\n\n"
        "Die Hochschule ist berechtigt, dieses Nutzungsrecht auch im Rahmen des Projekts arkumu.nrw zu nutzen und den "
        "beteiligten Projektpartnern (andere Kunst- und Musikhochschulen, technische Partner wie z.B. Rechenzentren) für "
        "die Zwecke von arkumu.nrw entsprechende einfache Nutzungsrechte einzuräumen."
    ),
}


def extract_license_token(value: Optional[Any]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    lowered = text.lower()
    if lowered in ARKUMU_LICENSE_LABELS:
        return lowered

    parsed = urlparse(text)
    path_segment = parsed.path.rstrip('/').split('/')[-1] if parsed.path else ""
    for candidate in (path_segment, text):
        normalized_candidate = str(candidate).strip().lower()
        if normalized_candidate in ARKUMU_LICENSE_LABELS:
            return normalized_candidate

    normalized = lowered.replace('_', '-').replace('%2b', '+')
    if "arkumu-a+b" in normalized:
        return "2"
    if "arkumu-a" in normalized and "arkumu-a+b" not in normalized:
        return "1"

    if any(keyword in normalized for keyword in ("lizenz", "license", "arkumu", "digitales-objekt-lizenz")):
        match = re.search(r'([12])(?:\.0)?(?:[^0-9]|$)', normalized)
        if match:
            token = match.group(1)
            if token in ARKUMU_LICENSE_LABELS:
                return token

    return None


def license_token_from_license_info(license_info: Optional[Any]) -> Optional[str]:
    if not license_info:
        return None
    candidates = [
        getattr(license_info, "identifier", None),
        getattr(license_info, "uri", None),
        getattr(license_info, "label_de", None),
        getattr(license_info, "label_en", None),
        getattr(license_info, "rights_statement", None),
    ]
    for candidate in candidates:
        token = extract_license_token(candidate)
        if token:
            return token
    return None

"""
Wikidata service for resolving entity information.
"""

import logging
import time
import requests
from typing import Dict, Optional, Any, List
from django.core.cache import cache

logger = logging.getLogger(__name__)


class WikidataService:
    """Service for resolving Wikidata entities to human-readable information."""

    WIKIDATA_API = "https://www.wikidata.org/w/api.php"
    CACHE_TIMEOUT = 86400  # 24 hours
    _cache_warmed = False
    _circuit_breaker_until = None  # Timestamp when to retry after failures

    @classmethod
    def warm_cache_from_db(cls) -> int:
        """Load all Wikidata labels from DB into memory cache."""
        from arkumu.metadata.models import ExternalSourcesEntity

        if cls._cache_warmed:
            return 0

        entries = ExternalSourcesEntity.objects.filter(
            source=ExternalSourcesEntity.SourceEnum.WIKIDATA,
            property__startswith="label_",
        )

        count = 0
        for entry in entries:
            # property is "label_de" -> extract language
            language = entry.property.split("_")[-1] if "_" in entry.property else "de"
            cache_key = f"wikidata_label:{entry.data_id}:{language}"
            cache.set(cache_key, entry.datum or "", cls.CACHE_TIMEOUT)
            count += 1

        cls._cache_warmed = True
        logger.info(f"WikidataService: warmed cache with {count} labels from DB")
        return count

    def get_location_info(self, wikidata_id: str, language: str = 'de') -> Dict[str, Any]:
        """
        Get location information from Wikidata ID.

        Args:
            wikidata_id: Wikidata Q-identifier (e.g., 'Q2103' for Essen)
            language: Language code for labels (default: 'de' for German)

        Returns:
            Dict with location name, coordinates, and other info
        """

        # Check cache first
        cache_key = f"wikidata_location:{wikidata_id}:{language}"
        cached_data = cache.get(cache_key)
        if cached_data:
            logger.debug(f"Cache hit for Wikidata location {wikidata_id}")
            return cached_data

        try:
            # Ensure we have proper Q-format
            if not wikidata_id.startswith('Q'):
                wikidata_id = f'Q{wikidata_id}'

            # Query Wikidata API
            params = {
                'action': 'wbgetentities',
                'ids': wikidata_id,
                'format': 'json',
                'languages': language,
                'props': 'labels|descriptions|claims'
            }

            headers = {
                'User-Agent': 'arkumu/1.0 (https://arkumu.nrw; arkumu@arkumu.nrw)'
            }
            response = requests.get(self.WIKIDATA_API, params=params, headers=headers, timeout=1)
            response.raise_for_status()
            data = response.json()

            if 'entities' not in data or wikidata_id not in data['entities']:
                logger.warning(f"No data found for Wikidata ID {wikidata_id}")
                return {'id': wikidata_id, 'name': wikidata_id}

            entity = data['entities'][wikidata_id]

            # Extract basic info
            result = {
                'id': wikidata_id,
                'name': self._get_label(entity, language, wikidata_id),
                'description': self._get_description(entity, language),
            }

            # Extract coordinates if available (P625)
            if 'claims' in entity and 'P625' in entity['claims']:
                coords = self._extract_coordinates(entity['claims']['P625'])
                if coords:
                    result['coordinates'] = coords
                    result['latitude'] = coords['latitude']
                    result['longitude'] = coords['longitude']

            # Extract country if available (P17)
            if 'claims' in entity and 'P17' in entity['claims']:
                country_id = self._extract_entity_id(entity['claims']['P17'])
                if country_id:
                    country_info = self.get_entity_label(country_id, language)
                    if country_info:
                        result['country'] = country_info

            # Cache the result
            cache.set(cache_key, result, self.CACHE_TIMEOUT)

            logger.info(f"Resolved Wikidata {wikidata_id} to: {result['name']}")
            return result

        except requests.RequestException as e:
            logger.error(f"Error fetching Wikidata info for {wikidata_id}: {e}")
            return {'id': wikidata_id, 'name': wikidata_id}
        except Exception as e:
            logger.error(f"Unexpected error processing Wikidata {wikidata_id}: {e}")
            return {'id': wikidata_id, 'name': wikidata_id}

    def get_entity_label(self, wikidata_id: str, language: str = 'de') -> Optional[str]:
        """Get just the label for a Wikidata entity."""
        from arkumu.metadata.models import ExternalSourcesEntity

        if not wikidata_id:
            return None

        # Normalize ID
        if not wikidata_id.startswith('Q'):
            wikidata_id = f'Q{wikidata_id}'

        property_key = f"label_{language}"

        # 1. Check in-memory cache first (fastest)
        cache_key = f"wikidata_label:{wikidata_id}:{language}"
        cached_label = cache.get(cache_key)
        if cached_label is not None:
            return cached_label if cached_label != "" else None

        # 2. Check database (ExternalSourcesEntity)
        db_entry = ExternalSourcesEntity.objects.filter(
            data_id=wikidata_id,
            property=property_key,
            source=ExternalSourcesEntity.SourceEnum.WIKIDATA,
        ).first()

        if db_entry:
            label = db_entry.datum if db_entry.datum else None
            cache.set(cache_key, label or "", self.CACHE_TIMEOUT)
            return label

        # 3. Fetch from Wikidata API (with circuit breaker)
        if WikidataService._circuit_breaker_until and time.time() < WikidataService._circuit_breaker_until:
            # Circuit breaker is open - skip API call
            cache.set(cache_key, "", 60)  # Short cache for circuit breaker period
            return None

        try:
            params = {
                'action': 'wbgetentities',
                'ids': wikidata_id,
                'format': 'json',
                'languages': language,
                'props': 'labels'
            }

            headers = {
                'User-Agent': 'arkumu/1.0 (https://arkumu.nrw; arkumu@arkumu.nrw)'
            }
            response = requests.get(self.WIKIDATA_API, params=params, headers=headers, timeout=1)
            response.raise_for_status()
            data = response.json()
            # Success - reset circuit breaker
            WikidataService._circuit_breaker_until = None

            if 'entities' not in data or wikidata_id not in data['entities']:
                # Store negative result in DB and cache
                ExternalSourcesEntity.objects.update_or_create(
                    data_id=wikidata_id,
                    property=property_key,
                    source=ExternalSourcesEntity.SourceEnum.WIKIDATA,
                    defaults={"datum": ""},
                )
                cache.set(cache_key, "", 3600)
                return None

            entity = data['entities'][wikidata_id]
            label = self._get_label(entity, language, wikidata_id)

            # Persist to database
            ExternalSourcesEntity.objects.update_or_create(
                data_id=wikidata_id,
                property=property_key,
                source=ExternalSourcesEntity.SourceEnum.WIKIDATA,
                defaults={"datum": label},
            )
            cache.set(cache_key, label, self.CACHE_TIMEOUT)
            return label

        except requests.exceptions.ConnectionError as e:
            logger.error(f"Network error fetching label for {wikidata_id}: {e}")
            # Trip circuit breaker for 5 minutes on connection errors
            WikidataService._circuit_breaker_until = time.time() + 300
            cache.set(cache_key, "", 300)
            return None
        except Exception as e:
            logger.error(f"Error fetching label for {wikidata_id}: {e}")
            cache.set(cache_key, "", 300)
            return None

    def resolve_multiple_locations(self, wikidata_ids: List[str], language: str = 'de') -> Dict[str, Dict[str, Any]]:
        """
        Resolve multiple Wikidata location IDs at once.

        Returns:
            Dict mapping Wikidata ID to location info
        """

        results = {}
        for wikidata_id in wikidata_ids:
            results[wikidata_id] = self.get_location_info(wikidata_id, language)
        return results

    def _get_label(self, entity: Dict, language: str, default: str) -> str:
        """Extract label from entity data."""
        if 'labels' in entity and language in entity['labels']:
            return entity['labels'][language]['value']
        elif 'labels' in entity and 'en' in entity['labels']:
            return entity['labels']['en']['value']
        return default

    def _get_description(self, entity: Dict, language: str) -> Optional[str]:
        """Extract description from entity data."""
        if 'descriptions' in entity and language in entity['descriptions']:
            return entity['descriptions'][language]['value']
        elif 'descriptions' in entity and 'en' in entity['descriptions']:
            return entity['descriptions']['en']['value']
        return None

    def _extract_coordinates(self, claim: List[Dict]) -> Optional[Dict[str, float]]:
        """Extract coordinates from P625 claim."""
        try:
            if claim and len(claim) > 0:
                mainsnak = claim[0].get('mainsnak', {})
                if mainsnak.get('datatype') == 'globe-coordinate':
                    value = mainsnak.get('datavalue', {}).get('value', {})
                    return {
                        'latitude': value.get('latitude'),
                        'longitude': value.get('longitude'),
                        'precision': value.get('precision'),
                        'globe': value.get('globe', 'http://www.wikidata.org/entity/Q2')
                    }
        except Exception as e:
            logger.error(f"Error extracting coordinates: {e}")
        return None

    def _extract_entity_id(self, claim: List[Dict]) -> Optional[str]:
        """Extract entity ID from a claim."""
        try:
            if claim and len(claim) > 0:
                mainsnak = claim[0].get('mainsnak', {})
                if mainsnak.get('datatype') == 'wikibase-item':
                    value = mainsnak.get('datavalue', {}).get('value', {})
                    return value.get('id')
        except Exception as e:
            logger.error(f"Error extracting entity ID: {e}")
        return None
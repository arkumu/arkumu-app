# FUK-HBZ URN:NBN:DE Identifier Mapping Guide

## Overview
This guide documents how to map German National Library (DNB) persistent identifiers, specifically URNs from the HBZ NRW (Hochschulbibliothekszentrum des Landes Nordrhein-Westfalen) namespace "urn:nbn:de:hbz:", to the Dublin Core identifier field (dc:identifier) using the existing FUK (Folkwang Universität der Künste) mapping configuration.

## URN:NBN:DE:HBZ Structure

HBZ NRW uses URNs with the following structure:
```
urn:nbn:de:hbz:[institution_code]-[unique_identifier]
```

### HBZ Institution Codes
- `061` - University of Cologne
- `101` - University of Duisburg-Essen
- `466` - RWTH Aachen University
- `385` - University of Düsseldorf
- `929` - Folkwang University of the Arts (FUK)
- `832` - University of Paderborn

### Example HBZ URN:NBN:DE Identifiers
```
urn:nbn:de:hbz:061-20180301-123456
urn:nbn:de:hbz:929-folkwang-123456
urn:nbn:de:hbz:466-opus-123456
urn:nbn:de:hbz:101-duepublico-123456
```

## FUK Database Tables for Identifier Mapping

Based on the FUK mapping structure, these tables contain identifier-related fields:

### 1. ProduktID_Kreuztabelle.csv
**Purpose**: Product ID cross-reference table linking different identifier types
**Potential Fields**:
- `ProduktID` - Primary product identifier
- `URN` - URN identifier field
- `Handle` - Handle identifier
- `DOI` - Digital Object Identifier
- `URL` - Web URL identifier

### 2. Nummernart.csv
**Purpose**: Number/identifier type definitions
**Potential Fields**:
- `ID` - Type identifier
- `Name` - Type name (e.g., "URN", "DOI", "Handle")
- `Beschreibung` - Description of identifier type
- `Pattern` - Validation pattern for the identifier type

### 3. Digitales_Objekt.csv
**Purpose**: Digital object records with their identifiers
**Potential Fields**:
- `ID` - Object ID
- `URN` - URN identifier
- `Handle` - Handle identifier
- `URL` - Access URL
- `PersistentURL` - Persistent URL

## Mapping Configuration for FUK System

### 1. Basic URN:NBN:DE:HBZ Mapping
```json
{
  "mapping_config": {
    "workspace_columns": {
      "digitales_objekt_urn": {
        "dataset_id": "digitales_objekt_dataset",
        "column_name": "URN",
        "data_type": "string",
        "mapping": {
          "target_field": "dc:identifier",
          "identifier_type": "urn:nbn:de:hbz",
          "transformation": "validate_hbz_urn",
          "validation_rules": {
            "pattern": "^urn:nbn:de:hbz:[0-9]+-[a-zA-Z0-9-]+$",
            "required": true,
            "unique": true
          }
        }
      }
    },
    "workspace_datasets": ["digitales_objekt_dataset"],
    "fk_relationships": {
      "urn_to_object": {
        "source_dataset": "produktid_kreuztabelle_dataset",
        "source_column": "ProduktID",
        "target_dataset": "digitales_objekt_dataset",
        "target_column": "ID",
        "relationship_type": "one_to_one"
      }
    }
  }
}
```

### 2. Multiple Identifier Types Mapping
```json
{
  "mapping_config": {
    "workspace_columns": {
      "hbz_urn": {
        "dataset_id": "produktid_kreuztabelle_dataset",
        "column_name": "URN",
        "data_type": "string",
        "mapping": {
          "target_field": "dc:identifier",
          "identifier_type": "urn:nbn:de:hbz",
          "priority": 1,
          "transformation": "format_hbz_urn"
        }
      },
      "handle_id": {
        "dataset_id": "produktid_kreuztabelle_dataset",
        "column_name": "Handle",
        "data_type": "string",
        "mapping": {
          "target_field": "dc:identifier",
          "identifier_type": "handle",
          "priority": 2,
          "transformation": "format_handle"
        }
      },
      "doi_id": {
        "dataset_id": "produktid_kreuztabelle_dataset",
        "column_name": "DOI",
        "data_type": "string",
        "mapping": {
          "target_field": "dc:identifier",
          "identifier_type": "doi",
          "priority": 3,
          "transformation": "format_doi"
        }
      }
    }
  }
}
```

### 3. Identifier Type Validation Using Nummernart
```json
{
  "mapping_config": {
    "workspace_columns": {
      "identifier_type": {
        "dataset_id": "nummernart_dataset",
        "column_name": "Name",
        "data_type": "string",
        "mapping": {
          "target_field": "dc:identifier.type",
          "transformation": "normalize_identifier_type"
        }
      },
      "identifier_pattern": {
        "dataset_id": "nummernart_dataset",
        "column_name": "Pattern",
        "data_type": "string",
        "mapping": {
          "target_field": "validation_pattern",
          "transformation": "compile_regex"
        }
      }
    },
    "fk_relationships": {
      "product_to_type": {
        "source_dataset": "produktid_kreuztabelle_dataset",
        "source_column": "NummernartID",
        "target_dataset": "nummernart_dataset",
        "target_column": "ID",
        "relationship_type": "many_to_one"
      }
    }
  }
}
```

## Field Mapping Recommendations

### For FUK-HBZ Integration

1. **Primary Identifier Source**: `ProduktID_Kreuztabelle.URN`
   - Map to: `dc:identifier`
   - Type: `urn:nbn:de:hbz`
   - Priority: High (primary persistent identifier)

2. **Identifier Type Validation**: `Nummernart.Name`
   - Use to validate identifier types
   - Ensure URN identifiers are properly categorized

3. **Digital Object Linking**: `Digitales_Objekt.URN`
   - Cross-reference with ProduktID table
   - Ensure consistency across object records

4. **Alternative Identifiers**:
   - Handle: `ProduktID_Kreuztabelle.Handle`
   - DOI: `ProduktID_Kreuztabelle.DOI`
   - URL: `ProduktID_Kreuztabelle.URL`

## HBZ Resolver Configuration

### Primary HBZ Resolver
```
https://nbn-resolving.org/[URN]
https://nbn-resolving.org/urn:nbn:de:hbz:929-folkwang-123456
```

### HBZ Specific Resolvers
```
https://kups.ub.uni-koeln.de/[local_id] (University of Cologne)
https://duepublico2.uni-due.de/[local_id] (University of Duisburg-Essen)
https://publications.rwth-aachen.de/[local_id] (RWTH Aachen)
https://docserv.uni-duesseldorf.de/[local_id] (University of Düsseldorf)
```

## Sample Implementation for FUK

```python
def configure_fuk_hbz_identifier_mapping(mapping_instance):
    """
    Configure FUK mapping for HBZ URN:NBN:DE identifiers
    """
    mapping_instance.mapping_config = {
        "workspace_columns": {
            # Primary URN from cross-reference table
            "urn_hbz_identifier": {
                "dataset_id": "produktid_kreuztabelle",
                "column_name": "URN",
                "data_type": "string",
                "mapping": {
                    "target_field": "dc:identifier",
                    "identifier_type": "urn:nbn:de:hbz",
                    "transformation": "validate_hbz_urn",
                    "validation_rules": {
                        "pattern": r"^urn:nbn:de:hbz:[0-9]+-[a-zA-Z0-9-]+$",
                        "required": True,
                        "unique": True
                    },
                    "enrichment": {
                        "add_resolver_url": True,
                        "resolver_base": "https://nbn-resolving.org/",
                        "institution_code": "hbz:929"  # Folkwang specific
                    }
                }
            },
            # Digital object URN for cross-validation
            "digital_object_urn": {
                "dataset_id": "digitales_objekt",
                "column_name": "URN",
                "data_type": "string",
                "mapping": {
                    "target_field": "dc:identifier",
                    "identifier_type": "urn:nbn:de:hbz",
                    "transformation": "cross_validate_urn"
                }
            }
        },
        "workspace_datasets": [
            "produktid_kreuztabelle",
            "digitales_objekt",
            "nummernart"
        ],
        "fk_relationships": {
            "product_to_digital_object": {
                "source_dataset": "produktid_kreuztabelle",
                "source_column": "ProduktID",
                "target_dataset": "digitales_objekt",
                "target_column": "ID",
                "relationship_type": "one_to_one"
            },
            "product_to_number_type": {
                "source_dataset": "produktid_kreuztabelle",
                "source_column": "NummernartID",
                "target_dataset": "nummernart",
                "target_column": "ID",
                "relationship_type": "many_to_one"
            }
        }
    }

    mapping_instance.organization_id = "fuk"
    mapping_instance.validation_status = "validated"
    mapping_instance.save()
    return mapping_instance
```

## Dublin Core Output Format

```xml
<!-- Primary URN identifier -->
<dc:identifier>urn:nbn:de:hbz:929-folkwang-123456</dc:identifier>

<!-- Resolver URLs -->
<dc:identifier>https://nbn-resolving.org/urn:nbn:de:hbz:929-folkwang-123456</dc:identifier>

<!-- Alternative identifiers -->
<dc:identifier>https://handle.net/1234/567890</dc:identifier>
<dc:identifier>https://doi.org/10.1234/example.doi</dc:identifier>
```

## Validation Rules for HBZ URNs

1. **Pattern Validation**: Must match `^urn:nbn:de:hbz:[0-9]+-[a-zA-Z0-9-]+$`
2. **Institution Code**: Must be valid HBZ institution (061, 101, 466, 385, 929, 832)
3. **Uniqueness**: Each URN must be unique within the system
4. **Cross-Reference**: URN in ProduktID_Kreuztabelle must match Digitales_Objekt.URN
5. **Type Consistency**: Nummernart.Name must be "URN" for URN identifiers

## References

- [HBZ Library Service Center](https://www.hbz-nrw.de/)
- [URN:NBN:DE Resolver](https://nbn-resolving.org/)
- [Dublin Core Metadata Terms](https://www.dublincore.org/specifications/dublin-core/dcmi-terms/#identifier)
- [Folkwang University Repository](https://www.folkwang-uni.de/)
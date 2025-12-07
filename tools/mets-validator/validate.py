#!/usr/bin/env python3
"""Rosetta METS XSD 1.1 Validator using xmlschema library."""

import sys
import xmlschema
from pathlib import Path


def main():
    if len(sys.argv) < 3:
        print("Usage: validate.py <schema.xsd> <document.xml>", file=sys.stderr)
        print("Example: validate.py /schema/rosettaMets.xsd /data/mets.xml", file=sys.stderr)
        sys.exit(1)

    schema_path = Path(sys.argv[1])
    xml_path = Path(sys.argv[2])

    if not schema_path.exists():
        print(f"ERROR: Schema not found: {schema_path}", file=sys.stderr)
        sys.exit(2)

    if not xml_path.exists():
        print(f"ERROR: XML file not found: {xml_path}", file=sys.stderr)
        sys.exit(2)

    try:
        # Load schema with XSD 1.1 support
        schema = xmlschema.XMLSchema11(
            str(schema_path),
            allow="local",
            locations={
                "http://www.w3.org/1999/xlink": str(schema_path.parent / "xlink.xsd"),
                "http://www.exlibrisgroup.com/dps/dnx": str(schema_path.parent / "dnx_sip.xsd"),
            },
        )

        # Validate
        errors = list(schema.iter_errors(str(xml_path)))

        if errors:
            print(f"INVALID: {len(errors)} error(s) found", file=sys.stderr)
            for i, err in enumerate(errors[:10], 1):
                reason = err.reason or err.message
                path = getattr(err, "path", None)
                loc = f" at {path}" if path else ""
                print(f"  {i}. {reason}{loc}", file=sys.stderr)
            if len(errors) > 10:
                print(f"  ... and {len(errors) - 10} more errors", file=sys.stderr)
            sys.exit(1)
        else:
            print("VALID: Document conforms to schema")
            sys.exit(0)

    except xmlschema.XMLSchemaException as e:
        print(f"SCHEMA ERROR: {e}", file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print(f"ERROR: {type(e).__name__} - {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()

#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SCHEMA_DIR="$REPO_ROOT/arkumu/oaipmh/schema"
IMAGE_NAME="arkumu-mets-validator"

usage() {
    echo "Usage: $0 [OPTIONS] <mets.xml | oai-url>"
    echo ""
    echo "Validate METS XML against Rosetta XSD 1.1 schema"
    echo ""
    echo "Options:"
    echo "  -s, --schema NAME   Schema to use: rosetta (default), mets, dnx"
    echo "  -b, --build         Force rebuild of Docker image"
    echo "  -h, --help          Show this help"
    echo ""
    echo "Examples:"
    echo "  # Validate a local METS file"
    echo "  $0 /path/to/mets.xml"
    echo ""
    echo "  # Validate from OAI endpoint (extracts METS automatically)"
    echo "  $0 'http://localhost:8000/oai/?verb=GetRecord&identifier=oai:arkumu:resource:http%3A//arkumu.org/data/fuk/entities/projekt/676&metadataPrefix=mets'"
    echo ""
    echo "  # Use standard METS schema instead of Rosetta"
    echo "  $0 -s mets /path/to/mets.xml"
}

SCHEMA="rosetta"
BUILD=0

while [[ $# -gt 0 ]]; do
    case $1 in
        -s|--schema)
            SCHEMA="$2"
            shift 2
            ;;
        -b|--build)
            BUILD=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            INPUT="$1"
            shift
            ;;
    esac
done

if [ -z "$INPUT" ]; then
    usage
    exit 1
fi

# Select schema file
case $SCHEMA in
    rosetta)
        SCHEMA_FILE="rosettaMets.xsd"
        ;;
    mets)
        SCHEMA_FILE="mets.xsd"
        ;;
    dnx)
        SCHEMA_FILE="dnx_sip.xsd"
        ;;
    *)
        echo "Unknown schema: $SCHEMA"
        exit 1
        ;;
esac

# Build image if needed
if [ $BUILD -eq 1 ] || ! docker image inspect "$IMAGE_NAME" &>/dev/null; then
    echo "Building validator image..."
    docker build -t "$IMAGE_NAME" "$SCRIPT_DIR"
fi

# Prepare input file
TEMP_DIR=$(mktemp -d)
trap "rm -rf $TEMP_DIR" EXIT

if [[ "$INPUT" == http* ]]; then
    echo "Fetching from OAI endpoint..."
    curl -sS "$INPUT" -o "$TEMP_DIR/response.xml"

    # Extract METS element from OAI response
    if command -v xmllint &>/dev/null; then
        xmllint --xpath "//*[local-name()='mets']" "$TEMP_DIR/response.xml" > "$TEMP_DIR/mets.xml" 2>/dev/null || {
            echo "ERROR: Could not extract METS element from response"
            exit 1
        }
    else
        echo "ERROR: xmllint required to extract METS from OAI response"
        echo "Install with: apt-get install libxml2-utils"
        exit 1
    fi
    XML_FILE="$TEMP_DIR/mets.xml"
else
    if [ ! -f "$INPUT" ]; then
        echo "ERROR: File not found: $INPUT"
        exit 1
    fi
    XML_FILE="$INPUT"
fi

echo "Validating against $SCHEMA_FILE..."
docker run --rm \
    -v "$XML_FILE:/data/input.xml:ro" \
    -v "$SCHEMA_DIR:/schema:ro" \
    --network host \
    "$IMAGE_NAME" "/schema/$SCHEMA_FILE" "/data/input.xml"

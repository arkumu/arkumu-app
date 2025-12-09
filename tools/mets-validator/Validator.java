import javax.xml.XMLConstants;
import javax.xml.transform.stream.StreamSource;
import javax.xml.validation.Schema;
import javax.xml.validation.SchemaFactory;
import java.io.File;
import java.io.FileInputStream;

/**
 * XML Schema Validator with XSD 1.0 support.
 *
 * Note: Full XSD 1.1 validation (for xsd:alternative, assertions, etc.)
 * requires Saxon-EE (commercial). This validator uses standard XSD 1.0
 * which covers most structural validation needs.
 */
public class Validator {
    public static void main(String[] args) throws Exception {
        if (args.length < 2) {
            System.err.println("Usage: Validator <schema.xsd> <document.xml>");
            System.err.println("Example: Validator /schema/rosettaMets.xsd /data/mets.xml");
            System.exit(1);
        }

        String schemaPath = args[0];
        String xmlPath = args[1];

        try {
            // Use standard XSD 1.0 factory
            SchemaFactory factory = SchemaFactory.newInstance(XMLConstants.W3C_XML_SCHEMA_NS_URI);

            // Set resource resolver for importing related schemas (xlink, dnx, etc.)
            factory.setResourceResolver((type, namespaceURI, publicId, systemId, baseURI) -> {
                if (systemId != null && !systemId.startsWith("http")) {
                    File schemaFile = new File(schemaPath);
                    File resolved = new File(schemaFile.getParentFile(), systemId);
                    if (resolved.exists()) {
                        return new org.w3c.dom.ls.LSInput() {
                            public java.io.Reader getCharacterStream() { return null; }
                            public void setCharacterStream(java.io.Reader r) {}
                            public java.io.InputStream getByteStream() {
                                try { return new FileInputStream(resolved); }
                                catch (Exception e) { return null; }
                            }
                            public void setByteStream(java.io.InputStream is) {}
                            public String getStringData() { return null; }
                            public void setStringData(String s) {}
                            public String getSystemId() { return resolved.toURI().toString(); }
                            public void setSystemId(String s) {}
                            public String getPublicId() { return publicId; }
                            public void setPublicId(String s) {}
                            public String getBaseURI() { return baseURI; }
                            public void setBaseURI(String s) {}
                            public String getEncoding() { return "UTF-8"; }
                            public void setEncoding(String s) {}
                            public boolean getCertifiedText() { return false; }
                            public void setCertifiedText(boolean b) {}
                        };
                    }
                }
                return null;
            });

            Schema schema = factory.newSchema(new File(schemaPath));
            javax.xml.validation.Validator validator = schema.newValidator();

            validator.validate(new StreamSource(new File(xmlPath)));
            System.out.println("VALID: Document conforms to schema");
            System.exit(0);

        } catch (org.xml.sax.SAXParseException e) {
            System.err.println("INVALID at line " + e.getLineNumber() + ", column " + e.getColumnNumber() + ":");
            System.err.println("  " + e.getMessage());
            System.exit(1);
        } catch (org.xml.sax.SAXException e) {
            System.err.println("INVALID: " + e.getMessage());
            System.exit(1);
        } catch (Exception e) {
            System.err.println("ERROR: " + e.getClass().getSimpleName() + " - " + e.getMessage());
            e.printStackTrace();
            System.exit(2);
        }
    }
}

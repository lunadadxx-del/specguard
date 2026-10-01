import tempfile
import unittest
from pathlib import Path

from specguard.parser import RefResolver, SpecError, load_spec


class TestLoadSpec(unittest.TestCase):
    def _tmp(self, text, suffix=".yaml"):
        f = tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False)
        f.write(text)
        f.close()
        return f.name

    def test_load_yaml(self):
        p = self._tmp("openapi: 3.0.0\ninfo:\n  title: t\n  version: '1'\n")
        self.assertEqual(load_spec(p)["openapi"], "3.0.0")

    def test_load_json(self):
        p = self._tmp('{"openapi": "3.1.0"}', suffix=".json")
        self.assertEqual(load_spec(p)["openapi"], "3.1.0")

    def test_missing_file(self):
        with self.assertRaises(SpecError):
            load_spec("/nonexistent/spec.yaml")

    def test_invalid_yaml(self):
        p = self._tmp("openapi: [unclosed\n  bad: : :\n")
        with self.assertRaises(SpecError):
            load_spec(p)


class TestRefResolver(unittest.TestCase):
    def test_resolves_internal_ref(self):
        doc = {
            "paths": {
                "/a": {
                    "get": {
                        "responses": {
                            "200": {
                                "description": "ok",
                                "content": {
                                    "application/json": {
                                        "schema": {"$ref": "#/components/schemas/Item"}
                                    }
                                },
                            }
                        }
                    }
                }
            },
            "components": {
                "schemas": {"Item": {"type": "object", "properties": {"id": {"type": "string"}}}}
            },
        }
        resolved = RefResolver(doc).resolve(doc)
        schema = resolved["paths"]["/a"]["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]
        self.assertEqual(schema["type"], "object")
        self.assertIn("id", schema["properties"])

    def test_nested_and_repeated_refs(self):
        doc = {
            "components": {
                "schemas": {
                    "A": {"$ref": "#/components/schemas/B"},
                    "B": {"type": "string"},
                }
            }
        }
        resolved = RefResolver(doc).resolve(doc)
        self.assertEqual(resolved["components"]["schemas"]["A"]["type"], "string")

    def test_recursive_ref_does_not_hang(self):
        doc = {"components": {"schemas": {"Node": {
            "type": "object",
            "properties": {"child": {"$ref": "#/components/schemas/Node"}},
        }}}}
        resolved = RefResolver(doc).resolve(doc)  # must terminate
        self.assertEqual(resolved["components"]["schemas"]["Node"]["type"], "object")

    def test_external_ref_rejected(self):
        doc = {"schema": {"$ref": "other.yaml#/components/x"}}
        with self.assertRaises(SpecError):
            RefResolver(doc).resolve(doc)

    def test_unresolvable_ref(self):
        doc = {"schema": {"$ref": "#/components/schemas/Missing"}}
        with self.assertRaises(SpecError):
            RefResolver(doc).resolve(doc)


if __name__ == "__main__":
    unittest.main()

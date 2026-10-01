import unittest

from specguard.diff import BREAKING, INFO, NON_BREAKING, diff_specs


def make_spec(paths):
    return {"openapi": "3.0.0", "info": {"title": "t", "version": "1"}, "paths": paths}


def op(**kw):
    base = {"responses": {"200": {"description": "ok"}}}
    base.update(kw)
    return base


def param(name, location="query", required=False, schema=None):
    return {"name": name, "in": location, "required": required,
            "schema": schema or {"type": "string"}}


def body(schema, required=True):
    return {"required": required,
            "content": {"application/json": {"schema": schema}}}


def resp_body(schema):
    return {"description": "ok", "content": {"application/json": {"schema": schema}}}


def sev_set(changes):
    return {(c.severity, c.location, c.message) for c in changes}


class TestEndpointDiff(unittest.TestCase):
    def test_identical_specs_no_changes(self):
        spec = make_spec({"/a": {"get": op()}})
        self.assertEqual(diff_specs(spec, spec), [])

    def test_endpoint_removed_is_breaking(self):
        old = make_spec({"/a": {"get": op()}, "/b": {"get": op()}})
        new = make_spec({"/a": {"get": op()}})
        changes = diff_specs(old, new)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].severity, BREAKING)
        self.assertIn("GET /b", changes[0].location)

    def test_endpoint_added_is_non_breaking(self):
        old = make_spec({"/a": {"get": op()}})
        new = make_spec({"/a": {"get": op()}, "/b": {"post": op()}})
        changes = diff_specs(old, new)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].severity, NON_BREAKING)

    def test_operation_id_change_is_info(self):
        old = make_spec({"/a": {"get": op(operationId="one")}})
        new = make_spec({"/a": {"get": op(operationId="two")}})
        changes = diff_specs(old, new)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].severity, INFO)


class TestParameterDiff(unittest.TestCase):
    def _specs(self, old_params, new_params):
        old = make_spec({"/a": {"get": op(parameters=old_params)}})
        new = make_spec({"/a": {"get": op(parameters=new_params)}})
        return diff_specs(old, new)

    def test_required_param_added_is_breaking(self):
        changes = self._specs([], [param("ws", required=True)])
        self.assertTrue(any(c.severity == BREAKING and "Required parameter added" in c.message
                            for c in changes))

    def test_optional_param_added_is_non_breaking(self):
        changes = self._specs([], [param("sort")])
        self.assertTrue(all(c.severity == NON_BREAKING for c in changes))

    def test_param_removed_is_breaking(self):
        changes = self._specs([param("limit")], [])
        self.assertTrue(any(c.severity == BREAKING and "removed" in c.message for c in changes))

    def test_param_became_required_is_breaking(self):
        changes = self._specs([param("q")], [param("q", required=True)])
        self.assertTrue(any(c.severity == BREAKING and "became required" in c.message
                            for c in changes))

    def test_param_type_change_is_breaking(self):
        changes = self._specs([param("n", schema={"type": "integer"})],
                              [param("n", schema={"type": "string"})])
        self.assertTrue(any(c.severity == BREAKING and "Type changed" in c.message
                            for c in changes))


class TestSchemaDiff(unittest.TestCase):
    def _specs(self, old_schema, new_schema, where="request"):
        if where == "request":
            old = make_spec({"/a": {"post": op(requestBody=body(old_schema))}})
            new = make_spec({"/a": {"post": op(requestBody=body(new_schema))}})
        else:
            old = make_spec({"/a": {"get": op(responses={"200": resp_body(old_schema)})}})
            new = make_spec({"/a": {"get": op(responses={"200": resp_body(new_schema)})}})
        return diff_specs(old, new)

    def test_new_required_request_field_is_breaking(self):
        old = {"type": "object", "properties": {"a": {"type": "string"}}}
        new = {"type": "object", "required": ["a", "b"],
               "properties": {"a": {"type": "string"}, "b": {"type": "string"}}}
        changes = self._specs(old, new)
        self.assertTrue(any(c.severity == BREAKING and "`b`" in c.message for c in changes))

    def test_optional_request_field_added_is_non_breaking(self):
        old = {"type": "object", "properties": {"a": {"type": "string"}}}
        new = {"type": "object",
               "properties": {"a": {"type": "string"}, "b": {"type": "string"}}}
        changes = self._specs(old, new)
        self.assertTrue(changes and all(c.severity == NON_BREAKING for c in changes))

    def test_enum_narrowed_is_breaking(self):
        old = {"type": "string", "enum": ["a", "b", "c"]}
        new = {"type": "string", "enum": ["a", "b"]}
        changes = self._specs(old, new)
        self.assertTrue(any(c.severity == BREAKING and "Enum values removed" in c.message
                            for c in changes))

    def test_response_field_removed_is_breaking(self):
        old = {"type": "object", "properties": {"a": {"type": "string"},
                                                "b": {"type": "string"}}}
        new = {"type": "object", "properties": {"a": {"type": "string"}}}
        changes = self._specs(old, new, where="response")
        self.assertTrue(any(c.severity == BREAKING and "Response property removed" in c.message
                            for c in changes))

    def test_nested_property_type_change(self):
        old = {"type": "object", "properties": {"addr": {"type": "object", "properties": {
            "zip": {"type": "string"}}}}}
        new = {"type": "object", "properties": {"addr": {"type": "object", "properties": {
            "zip": {"type": "integer"}}}}}
        changes = self._specs(old, new)
        self.assertTrue(any(c.severity == BREAKING and ".addr.zip" in c.location
                            for c in changes))

    def test_array_item_change(self):
        old = {"type": "array", "items": {"type": "string"}}
        new = {"type": "array", "items": {"type": "integer"}}
        changes = self._specs(old, new)
        self.assertTrue(any(c.severity == BREAKING for c in changes))

    def test_additional_properties_disallowed_is_breaking(self):
        old = {"type": "object", "additionalProperties": True}
        new = {"type": "object", "additionalProperties": False}
        changes = self._specs(old, new)
        self.assertTrue(any(c.severity == BREAKING and "Additional properties disallowed" in c.message
                            for c in changes))


class TestResponseDiff(unittest.TestCase):
    def test_response_code_removed_is_breaking(self):
        old = make_spec({"/a": {"get": op(responses={"200": {"description": "ok"},
                                                          "404": {"description": "nf"}})}})
        new = make_spec({"/a": {"get": op(responses={"200": {"description": "ok"}})}})
        changes = diff_specs(old, new)
        self.assertTrue(any(c.severity == BREAKING and "404" in c.message for c in changes))

    def test_response_code_added_is_non_breaking(self):
        old = make_spec({"/a": {"get": op(responses={"200": {"description": "ok"}})}})
        new = make_spec({"/a": {"get": op(responses={"200": {"description": "ok"},
                                                          "429": {"description": "rl"}})}})
        changes = diff_specs(old, new)
        self.assertTrue(changes and all(c.severity == NON_BREAKING for c in changes))


if __name__ == "__main__":
    unittest.main()

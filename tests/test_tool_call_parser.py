import unittest

from neudev.tool_call_parser import extract_text_tool_calls


class ToolCallParserTests(unittest.TestCase):
    def test_extracts_xml_style_tool_call(self):
        text = """
I should inspect the README first.
<tool_call>
<function=read_file>
<parameter=path>
README.md
</parameter>
</tool_call>
"""
        calls, cleaned = extract_text_tool_calls(text, {"read_file"})

        self.assertEqual(
            calls,
            [{"name": "read_file", "arguments": {"path": "README.md"}}],
        )
        self.assertEqual(cleaned, "I should inspect the README first.")

    def test_extracts_json_tool_call(self):
        text = """```json
{"tool": "list_directory", "arguments": {"path": ".", "max_depth": 2}}
```"""
        calls, cleaned = extract_text_tool_calls(text, {"list_directory"})

        self.assertEqual(
            calls,
            [{"name": "list_directory", "arguments": {"path": ".", "max_depth": 2}}],
        )
        self.assertEqual(cleaned, "")

    def test_extracts_inline_json_tool_call(self):
        text = """{"name": "write_file", "arguments": {"path": "src/main.py", "content": "print('hello')\\n"}}"""
        calls, cleaned = extract_text_tool_calls(text, {"write_file"})

        self.assertEqual(
            calls,
            [{"name": "write_file", "arguments": {"path": "src/main.py", "content": "print('hello')\n"}}],
        )
        self.assertEqual(cleaned, "")


if __name__ == "__main__":
    unittest.main()

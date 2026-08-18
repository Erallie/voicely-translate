import ast
import unittest
from pathlib import Path


SOURCE = Path(__file__).parents[1] / "voicely-translate.py"


def call_path(call):
    node = call.func
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def command_methods():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    command_class = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "TranslationCommands"
    )
    return {
        node.name: node for node in command_class.body
        if isinstance(node, ast.AsyncFunctionDef)
    }


class InteractionLifecycleTests(unittest.TestCase):
    def test_slow_commands_defer_before_slow_work(self):
        slow_prefixes = {
            "sync_kofi_topups_safely",
            "sync_kofi_topups",
            "register_topup_code",
            "asyncio.to_thread",
            "self.bot.voice_bridge.join",
        }
        expected_deferred = {
            "join", "topup", "balance", "usage",
            "defaultlanguages", "timeout", "leave",
        }
        methods = command_methods()
        for name in expected_deferred:
            method = methods[name]
            awaits = [node for node in ast.walk(method) if isinstance(node, ast.Await)]
            defer_lines = [
                node.lineno for node in awaits
                if isinstance(node.value, ast.Call)
                and call_path(node.value) == "interaction.response.defer"
            ]
            self.assertTrue(defer_lines, f"/{name} does not defer")
            slow_lines = [
                node.lineno for node in awaits
                if isinstance(node.value, ast.Call)
                and call_path(node.value) in slow_prefixes
            ]
            if slow_lines:
                self.assertLess(
                    min(defer_lines), min(slow_lines),
                    f"/{name} performs slow work before deferring",
                )

    def test_no_initial_response_is_sent_after_defer(self):
        for name, method in command_methods().items():
            calls = [node for node in ast.walk(method) if isinstance(node, ast.Call)]
            defer_lines = [
                node.lineno for node in calls
                if call_path(node) == "interaction.response.defer"
            ]
            if not defer_lines:
                continue
            late_initial_responses = [
                node.lineno for node in calls
                if call_path(node) == "interaction.response.send_message"
                and node.lineno > min(defer_lines)
            ]
            self.assertEqual(
                late_initial_responses, [],
                f"/{name} sends an initial response after deferring",
            )

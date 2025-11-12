# agentic_patterns/reflection_agent.py
"""
ReflectionAgent with a lightweight verification step.

What changed / added:
- verify_code: extracts python code blocks from the last generation and runs
  syntax checks (ast.parse). If a function name containing "sort" is found,
  it runs small sorting tests against that function.
- verify_last_generation: convenience wrapper to verify the last generation
  produced in a round-like dict.
- The run(...) method is unchanged in behaviour but the agent exposes the
  verification API so the UI can call it after each generation round.

Security note:
- verify_code executes generated code with exec() to run unit-style checks.
  This is inherently unsafe for untrusted code. Use only in a controlled
  environment. For production, run verification in an isolated sandbox or a
  dedicated service (e.g., container, restricted subprocess, evaluator).
"""

from typing import Any, Dict, List, Optional, Tuple
import os
import time
import re
import ast
import traceback

# Minimal Mock client to be used if no real client is provided.
class MockClient:
    class chat:
        class completions:
            @staticmethod
            def create(messages, model):
                sys_text = " ".join(m.get("content", "") for m in messages if m["role"] == "system").lower()
                user_text = " ".join(m.get("content", "") for m in messages if m["role"] == "user")
                # Generation: return toy merge sort
                if "programmer" in sys_text or "generate" in sys_text:
                    content = (
                        "```python\n"
                        "def merge_sort(arr):\n"
                        "    if len(arr) <= 1:\n"
                        "        return arr\n"
                        "    mid = len(arr)//2\n"
                        "    left = merge_sort(arr[:mid])\n"
                        "    right = merge_sort(arr[mid:])\n"
                        "    merged = []\n"
                        "    i = j = 0\n"
                        "    while i < len(left) and j < len(right):\n"
                        "        if left[i] <= right[j]:\n"
                        "            merged.append(left[i]); i += 1\n"
                        "        else:\n"
                        "            merged.append(right[j]); j += 1\n"
                        "    merged.extend(left[i:]); merged.extend(right[j:])\n"
                        "    return merged\n"
                        "```\n"
                    )
                    return {"choices": [{"message": {"content": content}}]}
                # Reflection: basic critique or OK
                if "review" in sys_text or "expert" in sys_text:
                    if "```python" in user_text or "<ok>" in user_text.lower():
                        return {"choices": [{"message": {"content": "<OK>"}}]}
                    return {"choices": [{"message": {"content": "Looks fine. Consider adding type hints and tests. <OK>"}}]}
                return {"choices": [{"message": {"content": "<OK>"}}]}


class ReflectionAgent:
    """
    ReflectionAgent runs alternating generation and reflection steps.

    client: object implementing .chat.completions.create(messages=..., model=...)
            If client is None, a MockClient is used.
    model: model id string
    stop_on_ok: whether to stop early when reflection returns '<OK>' or 'OK'
    """

    CODE_BLOCK_RE = re.compile(r"```(?:python)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)

    def __init__(self, client: Any = None, model: str = "llama-3.3-70b-versatile", stop_on_ok: bool = True):
        self.client = client if client is not None else MockClient()
        self.model = model
        self.stop_on_ok = stop_on_ok

    def _call_model(self, messages: List[Dict[str, str]]) -> str:
        """
        Call the configured client and return assistant content text.
        Handles both Groq/OpenAI-like dict responses and attr-style responses.
        """
        resp = self.client.chat.completions.create(messages=messages, model=self.model)
        # robust extraction
        try:
            # attr-style
            choice = resp.choices[0]
            content = getattr(choice, "message", None)
            if content is not None:
                return content.content
        except Exception:
            pass
        try:
            # dict-style
            if isinstance(resp, dict):
                return resp["choices"][0]["message"]["content"]
        except Exception:
            pass
        # fallback to string
        return str(resp)

    @staticmethod
    def _should_stop(critique_text: str) -> bool:
        if not critique_text:
            return False
        lowered = critique_text.strip().lower()
        if "<ok>" in lowered:
            return True
        if lowered == "ok":
            return True
        for line in critique_text.splitlines():
            if line.strip().lower() == "ok":
                return True
        return False

    def run(
        self,
        user_msg: str,
        generation_system_prompt: str,
        reflection_system_prompt: str,
        n_steps: int = 3,
        verbose: bool = False,
        delay_between_steps: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Execute the reflection loop. Returns structured result with rounds list.
        """
        generation_history: List[Dict[str, str]] = [
            {"role": "system", "content": generation_system_prompt},
            {"role": "user", "content": user_msg},
        ]

        rounds: List[Dict[str, str]] = []
        final_assistant = ""

        for step in range(1, n_steps + 1):
            if verbose:
                print("=" * 50)
                print(f"STEP {step}/{n_steps}")
                print("=" * 50)
                print("\nGENERATION\n")

            # Generation step
            generation_text = self._call_model(generation_history)
            generation_history.append({"role": "assistant", "content": generation_text})

            if verbose:
                print(generation_text)
                print("\nREFLECTION\n")

            # Reflection step: send generation_text to reflection system
            reflection_history = [
                {"role": "system", "content": reflection_system_prompt},
                {"role": "user", "content": generation_text},
            ]
            critique_text = self._call_model(reflection_history)
            generation_history.append({"role": "user", "content": critique_text})

            rounds.append(
                {
                    "generation_text": generation_text,
                    "critique_text": critique_text,
                    "step": step,
                }
            )

            if verbose:
                print(critique_text)
                print()

            final_assistant = generation_text

            if self.stop_on_ok and self._should_stop(critique_text):
                if verbose:
                    print("Stop token detected in reflection. Ending loop.")
                break

            if delay_between_steps > 0:
                time.sleep(delay_between_steps)

        return {
            "final_assistant": final_assistant,
            "rounds": rounds,
            "generation_history": generation_history,
        }

    def extract_code_blocks(self, text: str) -> List[str]:
        """
        Return list of python code blocks extracted from the text.
        """
        return [m.strip() for m in self.CODE_BLOCK_RE.findall(text)]

    def verify_code(self, code: str) -> Dict[str, Any]:
        """
        Verify the provided python code:
         - syntax_ok: True if ast.parse succeeds
         - tests_run: number of simple tests attempted
         - tests_passed: number passed
         - errors: list of error messages if any

        Heuristic tests:
         - If a function name containing "sort" is found, run sorting tests:
           call func([3,1,2]) and check equals [1,2,3], etc.

        NOTE: This executes code with exec() inside this process. That can be
        dangerous for untrusted code. Use only in controlled environments.
        """
        result = {"syntax_ok": False, "tests_run": 0, "tests_passed": 0, "errors": [], "function_tested": None}
        try:
            ast.parse(code)
            result["syntax_ok"] = True
        except Exception as e:
            result["errors"].append(f"SyntaxError: {e}")
            return result

        # Find function names
        try:
            tree = ast.parse(code)
            func_names = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
        except Exception as e:
            result["errors"].append(f"AST walk error: {e}")
            return result

        if not func_names:
            # Nothing to run; syntax-only verification
            return result

        # Pick first function to run heuristics against
        fn = func_names[0]
        result["function_tested"] = fn

        # Heuristic: if function name suggests sorting, run sorting tests
        tests = []
        if "sort" in fn.lower():
            tests = [
                ([3, 1, 2], [1, 2, 3]),
                ([], []),
                ([5, 4, 3, 2, 1], [1, 2, 3, 4, 5]),
                ([1], [1]),
            ]
        else:
            # Generic simple tests: if function accepts ints or returns predictable result
            # We cannot infer signature reliably; attempt zero-arg call and single-arg integer list
            tests = []

        # Execute code in a restricted namespace (best-effort)
        ns: Dict[str, Any] = {}
        try:
            exec(compile(code, "<generated>", "exec"), ns, ns)
        except Exception as e:
            tb = traceback.format_exc()
            result["errors"].append(f"RuntimeError on exec: {e}\n{tb}")
            return result

        func = ns.get(fn)
        if func is None or not callable(func):
            result["errors"].append(f"Function {fn} not found after exec.")
            return result

        # Run tests
        passed = 0
        run_count = 0
        for inp, expected in tests:
            run_count += 1
            try:
                out = func(inp)
                if out == expected:
                    passed += 1
                else:
                    result["errors"].append(f"Test failed for input {inp}: got {out}, expected {expected}")
            except Exception as e:
                result["errors"].append(f"Exception when testing input {inp}: {e}\n{traceback.format_exc()}")

        result["tests_run"] = run_count
        result["tests_passed"] = passed
        return result

    def verify_generation_text(self, generation_text: str) -> Dict[str, Any]:
        """
        Convenience method: extract code blocks and verify first block found.
        """
        codes = self.extract_code_blocks(generation_text)
        if not codes:
            return {"found_code": False, "verification": {"syntax_ok": False, "errors": ["No code block found"]}}
        code = codes[0]
        verification = self.verify_code(code)
        return {"found_code": True, "verification": verification}
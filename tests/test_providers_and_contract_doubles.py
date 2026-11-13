# =============================================================================
# HYDRA-UMC-OPS-AGENT - tests/test_providers_and_contract_doubles.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The two built-in model providers and the contract check, run against test doubles of the packages they import lazily
(`anthropic`, `openai`, the SDK), so the success and failure paths run with no network and no optional package installed."""
import contextlib
import io
import sys
import types
import unittest
from unittest import mock

from hydra_umc_ops_agent import contract_check
from hydra_umc_ops_agent.diagnosis import (
    DiagnosisError,
    diagnose_incident,
    AnthropicProvider,
    MissingApiKeyError,
    OpenAIProvider,
    ProviderRequestError,
    ProviderResponseError,
    ProviderUnavailableError,
)


def _module(name: str, **attrs) -> types.ModuleType:
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


class _Block:
    def __init__(self, text):
        self.text = text


def _anthropic_double(content=None, error=None, seen=None):
    class Messages:
        def create(self, **kwargs):
            if seen is not None:
                seen.append(kwargs)
            if error is not None:
                raise error
            return types.SimpleNamespace(content=content)

    class Client:
        def __init__(self, **kwargs):
            self.messages = Messages()
            if seen is not None:
                seen.append({"client": kwargs})

    return _module("anthropic", Anthropic=Client)


def _openai_double(choices=None, error=None, seen=None):
    class Completions:
        def create(self, **kwargs):
            if seen is not None:
                seen.append(kwargs)
            if error is not None:
                raise error
            return types.SimpleNamespace(choices=choices)

    class Client:
        def __init__(self, **kwargs):
            self.chat = types.SimpleNamespace(completions=Completions())

    return _module("openai", OpenAI=Client)


CALL = {"system_prompt": "sys", "user_prompt": "user", "model": "m", "max_tokens": 50}


class AnthropicProviderTests(unittest.TestCase):
    def test_no_key_anywhere_is_refused(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(MissingApiKeyError):
                AnthropicProvider()

    def test_the_key_comes_from_the_environment_when_not_given(self):
        with mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": "from-env"}, clear=True):
            self.assertEqual(AnthropicProvider()._api_key, "from-env")

    def test_a_missing_package_is_reported_as_unavailable(self):
        with mock.patch.dict(sys.modules, {"anthropic": None}):
            with self.assertRaises(ProviderUnavailableError):
                AnthropicProvider(api_key="k").complete(**CALL)

    def test_the_text_of_the_first_block_is_returned_and_the_request_is_bounded(self):
        seen = []
        with mock.patch.dict(sys.modules, {"anthropic": _anthropic_double([_Block("diagnosis")], seen=seen)}):
            self.assertEqual(AnthropicProvider(api_key="k").complete(**CALL), "diagnosis")
        request = [item for item in seen if "model" in item][0]
        self.assertEqual((request["model"], request["max_tokens"], request["system"]), ("m", 50, "sys"))
        client = [item for item in seen if "client" in item][0]["client"]
        self.assertGreater(client["timeout"], 0)
        self.assertGreaterEqual(client["max_retries"], 0)

    def test_a_failing_request_becomes_a_provider_error(self):
        with mock.patch.dict(sys.modules, {"anthropic": _anthropic_double(error=RuntimeError("down"))}):
            with self.assertRaises(ProviderRequestError):
                AnthropicProvider(api_key="k").complete(**CALL)

    def test_an_answer_with_no_blocks_or_no_text_is_refused(self):
        for content in ([], None, [_Block("")], [_Block(None)]):
            with mock.patch.dict(sys.modules, {"anthropic": _anthropic_double(content)}):
                with self.assertRaises(ProviderResponseError, msg=repr(content)):
                    AnthropicProvider(api_key="k").complete(**CALL)


class OpenAIProviderTests(unittest.TestCase):
    def test_no_key_anywhere_is_refused(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(MissingApiKeyError):
                OpenAIProvider()

    def test_a_missing_package_is_reported_as_unavailable(self):
        with mock.patch.dict(sys.modules, {"openai": None}):
            with self.assertRaises(ProviderUnavailableError):
                OpenAIProvider(api_key="k").complete(**CALL)

    def test_the_message_text_is_returned_with_both_prompts_sent(self):
        seen = []
        choice = types.SimpleNamespace(message=types.SimpleNamespace(content="diagnosis"))
        with mock.patch.dict(sys.modules, {"openai": _openai_double([choice], seen=seen)}):
            self.assertEqual(OpenAIProvider(api_key="k").complete(**CALL), "diagnosis")
        roles = [message["role"] for message in seen[0]["messages"]]
        self.assertEqual(roles, ["system", "user"])

    def test_a_failing_request_becomes_a_provider_error(self):
        with mock.patch.dict(sys.modules, {"openai": _openai_double(error=RuntimeError("down"))}):
            with self.assertRaises(ProviderRequestError):
                OpenAIProvider(api_key="k").complete(**CALL)

    def test_an_answer_with_no_choice_or_no_content_is_refused(self):
        no_message = types.SimpleNamespace()
        empty = types.SimpleNamespace(message=types.SimpleNamespace(content=""))
        for choices in ([], None, [no_message], [empty]):
            with mock.patch.dict(sys.modules, {"openai": _openai_double(choices)}):
                with self.assertRaises(ProviderResponseError, msg=repr(choices)):
                    OpenAIProvider(api_key="k").complete(**CALL)


class ModelResolutionTests(unittest.TestCase):
    def test_a_custom_provider_with_no_default_model_needs_one_to_be_named(self):
        class Custom:
            name = "custom-local"

            def complete(self, **kwargs):
                return "text"

        with self.assertRaises(DiagnosisError):
            diagnose_incident(object(), provider=Custom())  # refused before the incident is even read


class _ContractError(Exception):
    pass


def _sdk_doubles(fail_with=None):
    def make(name):
        def validate(payload):
            if fail_with is not None:
                raise _ContractError(f"{name} rejected")
        return validate

    maintenance = _module(
        "hydra_umc_sdk.maintenance_agent",
        validate_node_snapshot=make("NodeSnapshot"), validate_change_proposal=make("ChangeProposal"),
        validate_canary_deploy_result=make("CanaryDeployResult"),
    )
    validation = _module("hydra_umc_sdk.validation", ContractValidationError=_ContractError)
    package = _module("hydra_umc_sdk", maintenance_agent=maintenance, validation=validation)
    return {"hydra_umc_sdk": package, "hydra_umc_sdk.maintenance_agent": maintenance, "hydra_umc_sdk.validation": validation}


class ContractCheckDoubleTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(setattr, contract_check, "_mode", contract_check._mode)
        self.addCleanup(setattr, contract_check, "_said_missing", contract_check._said_missing)
        contract_check._said_missing = False

    def test_an_unknown_mode_falls_back_to_off(self):
        contract_check.set_mode("loud")
        self.assertEqual(contract_check.current_mode(), "off")
        contract_check.set_mode("strict")
        self.assertEqual(contract_check.current_mode(), "strict")

    def test_off_checks_nothing_even_without_the_sdk(self):
        with mock.patch.dict(sys.modules, {"hydra_umc_sdk": None}):
            contract_check.check("NodeSnapshot", {}, "file", mode="off")

    def test_strict_without_the_sdk_refuses(self):
        with mock.patch.dict(sys.modules, {"hydra_umc_sdk": None}):
            with self.assertRaises(contract_check.ContractCheckError):
                contract_check.check("NodeSnapshot", {}, "file", mode="strict")

    def test_warn_without_the_sdk_says_so_only_once(self):
        err = io.StringIO()
        with mock.patch.dict(sys.modules, {"hydra_umc_sdk": None}), contextlib.redirect_stderr(err):
            contract_check.check("NodeSnapshot", {}, "file", mode="warn")
            contract_check.check("NodeSnapshot", {}, "file", mode="warn")
        self.assertEqual(err.getvalue().count("not installed"), 1)

    def test_a_valid_file_passes_in_every_mode(self):
        err = io.StringIO()
        with mock.patch.dict(sys.modules, _sdk_doubles()), contextlib.redirect_stderr(err):
            for contract in ("NodeSnapshot", "ChangeProposal", "CanaryDeployResult"):
                for mode in ("warn", "strict"):
                    contract_check.check(contract, {}, "file", mode=mode)
        self.assertEqual(err.getvalue(), "")

    def test_a_rejected_file_is_refused_in_strict_and_warned_in_warn(self):
        with mock.patch.dict(sys.modules, _sdk_doubles(fail_with=True)):
            with self.assertRaises(contract_check.ContractCheckError) as caught:
                contract_check.check("ChangeProposal", {}, "proposal.json", mode="strict")
            self.assertIn("proposal.json", str(caught.exception))
            self.assertIn("ChangeProposal", str(caught.exception))
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                contract_check.check("CanaryDeployResult", {}, "result.json", mode="warn")
            self.assertIn("result.json", err.getvalue())

    def test_the_module_mode_is_used_when_none_is_given(self):
        contract_check.set_mode("strict")
        with mock.patch.dict(sys.modules, _sdk_doubles(fail_with=True)):
            with self.assertRaises(contract_check.ContractCheckError):
                contract_check.check("NodeSnapshot", {}, "file")


if __name__ == "__main__":
    unittest.main()

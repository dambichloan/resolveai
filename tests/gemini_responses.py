"""Scripted HTTP responses for exercising the real Gemini workflow offline."""
import copy
import json

from app.gemini_agent import GeminiAgent


def response(**values):
    return {"candidates": [{"content": {"role": "model", "parts": [
        {"text": json.dumps(values, ensure_ascii=False)}]}}]}


def tool(name, **args):
    return {"candidates": [{"content": {"role": "model", "parts": [
        {"functionCall": {"name": name, "args": args}}]}}]}


def agent(settings):
    responses, requests = [], []

    def post(url, headers, body, timeout):
        requests.append(copy.deepcopy(body))
        if responses:
            return responses.pop(0)
        return response(decision="smalltalk", reply="Chào bạn!", intent="Tư vấn", llm_confidence=1)

    result = GeminiAgent(settings, post=post, sleep=lambda _: None)
    result.responses, result.requests = responses, requests
    return result


# This helper is imported as ``test_agent`` by API tests.  Tell pytest it is
# a helper, not a test function requiring a ``settings`` fixture.
agent.__test__ = False

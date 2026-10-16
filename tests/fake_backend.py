"""A backend for tests: counts its calls and answers like uniform, optionally slowly or badly."""

import threading
import time

from decision_router.backends import Backend, Reply, Uniform


class Fake(Backend):
    def __init__(self, name, entry=None, delay=0.0):
        super().__init__(name, entry)
        self.calls = 0
        self.delay = delay
        self.fail = None  # an exception to raise instead of answering
        self.bad = False  # answer no questions
        self._lock = threading.Lock()

    def call(self, wire, request):
        with self._lock:
            self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise self.fail
        if self.bad:
            return Reply({"model": self.name, "answers": {}})
        reply = Uniform(self.name).call(wire, request)
        return Reply(reply.response, raw={"wrapped": reply.response}, cost=0.001, provenance={"generation": "gen-1"})

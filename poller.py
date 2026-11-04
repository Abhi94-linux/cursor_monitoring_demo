"""Background polling. This is not an HTTP route."""

import time

from collector import CollectError

POLL_INTERVAL = 15
SECRET_FIELDS = {"password", "username"}


def poll_once(store, collector):
    for server in store.servers_for_poll():
        poll_server(store, collector, server)


def poll_server(store, collector, server):
    try:
        sample, baseline = collector(server, store.baseline(server["id"]))
    except CollectError as exc:
        store.mark_offline(server["id"], public_error(str(exc)))
        return
    except Exception:
        store.mark_offline(server["id"], "connection failed")
        return
    store.mark_online(server["id"], public_sample(sample), baseline)


def poll_loop(store, collector, interval=POLL_INTERVAL, clock=time.monotonic, pause=None, should_stop=None):
    """Poll every server, then wait. Tests pass a fake clock and pause."""
    if pause is None:
        pause = time.sleep
    if should_stop is None:
        should_stop = lambda: False
    while not should_stop():
        started = clock()
        poll_once(store, collector)
        if should_stop():
            return
        pause(max(0.0, interval - (clock() - started)))
        if should_stop():
            return


def public_sample(sample):
    return {key: value for key, value in sample.items() if key not in SECRET_FIELDS}


def public_error(message):
    text = " ".join(str(message).split())
    return (text or "connection failed")[:180]

from uuid import NAMESPACE_URL, uuid5


def entity_id(drawing_id: str, handle: str, layout: str = "Model") -> str:
    # The logical drawing ID is caller-owned; revision is a separate concurrency guard.
    return "entity:" + str(uuid5(NAMESPACE_URL, f"{drawing_id}/{layout}/{handle.upper()}"))

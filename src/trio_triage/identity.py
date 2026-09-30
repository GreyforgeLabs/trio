from .errors import TrioError

def actor(identity,kind="human"):
    if not isinstance(identity,str) or not identity or len(identity)>128 or kind not in ("human","agent"):
        raise TrioError("INVALID_ACTOR",exit_code=2)
    return {"id":identity,"kind":kind,"trust":"claimed"}

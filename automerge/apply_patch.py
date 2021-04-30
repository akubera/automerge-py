from functools import cmp_to_key
from typing import NamedTuple
import re
from .datatypes import Map, List, Counter

OpId = NamedTuple("OpId", [("counter", int), ("actorId", str)])
OP_ID_RE = re.compile("^(\d+)@(.*)$")


def parse_op_id(op_id):
    match = OP_ID_RE.match(op_id)
    if not match:
        # TODO: proper exception type
        raise Exception(f"Not a valid op_id: {op_id}")
    return OpId(int(match.group(1)), match.group(2))


def lamport_compare(ts1, ts2):
    """
    Compares two strings, interpreted as Lamport timestamps of the form
    'counter@actorId'. Returns a postive integer if ts1 is greater, or a negative integer if ts2 is greater.
    """
    time1 = parse_op_id(ts1)
    time2 = parse_op_id(ts2)
    if time1.counter != time2.counter:
        return time1.counter - time2.counter
    if time1.actorId != time2.actorId:
        return 1 if time1.actorId > time2.actorId else -1
    return 0


def get_value(conflict, patch):
    if "objectId" in patch:
        if conflict and conflict.object_id != patch["objectId"]:
            # if the object ids are different then the patch is
            # replacing the object with a new one made from scratch
            if patch["type"] == "map":
                conflict = Map([], patch["objectId"])
            else:
                assert patch["type"] == "list"
                conflict = List([], patch["objectId"])
        return apply_patch(conflict, patch)
    elif "datatype" in patch:
        return Counter(patch["value"])
    else:
        # primitive (number, string, boolean, null)
        return patch["value"]


def apply_properties(obj, props):
    our_recent_ops = obj.recent_ops
    for key, patch_recent_ops in props.items():
        # Sort the lamport timestamps in increasing order & reverse the result
        # so the highest timestamp is first
        values, patch_op_ids = {}, list(patch_recent_ops.keys())
        patch_op_ids.sort(key=cmp_to_key(lamport_compare))
        patch_op_ids.reverse()

        for patch_op_id in patch_op_ids:
            subpatch = patch_recent_ops[patch_op_id]
            have_key_entry = (
                key in our_recent_ops
                if isinstance(our_recent_ops, dict)
                # `key` is an idx & `our_recent_ops` is an array
                #  we need to check that `our_recent_ops[key]` is not None
                #  (to prevent exception on next line) b/c in `update_list_obj`
                #  we fill `our_recent_ops` with None values
                else (key < len(our_recent_ops) and our_recent_ops[key])
            )
            if have_key_entry and (patch_op_id in our_recent_ops[key]):
                # TODO: Explain when this case happens
                values[patch_op_id] = get_value(
                    our_recent_ops[key][patch_op_id], subpatch
                )
            else:
                v = None
                if "objectId" in subpatch:
                    new_val = (
                        Map([], subpatch["objectId"])
                        if subpatch["type"] == "map"
                        else List([], subpatch["objectId"])
                    )
                    v = get_value(new_val, subpatch)
                else:
                    v = get_value(None, subpatch)
                values[patch_op_id] = v

        if len(patch_op_ids) == 0:
            # an empty subpatch signals "delete"
            del obj[key]
            del our_recent_ops[key]
        else:
            # B/c the highest lamport timestamp is 1st
            # the default value will have been created at the highest lamport timestamp
            obj[key] = values[patch_op_ids[0]]
            our_recent_ops[key] = values


def update_list_obj(listobj, props, edits):
    our_recent_ops, elem_ids = listobj.recent_ops, listobj.elem_ids
    for edit in edits:
        idx = edit["index"]
        if edit["action"] == "insert":
            elem_ids.insert(idx, edit["elemId"])
            listobj.insert(idx, None)
            our_recent_ops.insert(idx, None)
        elif edit["action"] == "remove":
            del elem_ids[idx]
            del listobj[idx]
            del our_recent_ops[idx]
    apply_properties(listobj, props)


def apply_patch(obj, patch):
    not_none = obj is not None
    if not_none:
        obj._frozen = False

    if not_none and "props" not in patch and "edits" not in patch:
        # TODO: for some reason, this property was mysteriously set
        # even when it was never implemented on the `Map` datatype
        obj._frozen = True
        return obj

    # don't need the `ret` thing now, but in the future we might
    # (probably a bad reason??)
    ret = None
    if patch["type"] == "map":
        apply_properties(obj, patch["props"])
        ret = obj
    elif patch["type"] == "list":
        update_list_obj(obj, patch["props"], patch["edits"])
        ret = obj
    else:
        raise Exception(f"Unknown object type in patch: {patch['type']}")

    if not_none:
        obj._frozen = True
    return ret
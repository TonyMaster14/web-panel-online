#!/usr/bin/env python3
"""Safely patch WPO's installed controller to avoid losing freshly enrolled nodes.

A concurrent /nodes-status request can read the old registry, spend seconds
checking HTTPS/GeoIP, and overwrite a node inserted by /node-enroll. Merge only
the changed status/GeoIP fields of still-existing IDs into the latest registry.
"""
import argparse
from pathlib import Path

MARKER="# wpo-node-enrollment-race-v1"
OLD_BEGIN='now=int(time.time()); current=node_api.load_nodes(NODES_FILE); changed=wpo_node_geo.enrich(current,now)'
NEW_BEGIN='''now=int(time.time()); current=node_api.load_nodes(NODES_FILE)
             # Snapshot taken BEFORE network/GeoIP calls; it must not be saved
             # wholesale after a concurrent /node-enroll or rename.
             node_status_snapshot={str(n.get("id")):dict(n) for n in current if isinstance(n,dict)}
             changed=wpo_node_geo.enrich(current,now)'''
OLD_SAVE='if changed: node_api.save_nodes(NODES_FILE,current)\n            pending=wpo_pending_load(); pending_rows=[]'
NEW_SAVE='''if changed:
                 # # wpo-node-enrollment-race-v1
                 # Hold the same lock used by enrollment and the auto-template
                 # worker, then re-read the latest disk registry under that lock.
                 # Only merge observed field changes if the disk value is still
                 # what was originally observed. Never replace the entire list.
                 with wpo_node_auto.registry_lock:
                     current_live=node_api.load_nodes(NODES_FILE)
                     observed={str(n.get("id")):n for n in current if isinstance(n,dict)}
                     wrote=False
                     fields=("status","status_detail","status_checked_at","version",
                             "capabilities","geo_checked_at","country_code",
                             "country_name","name","name_auto")
                     for live in current_live:
                         uid=str(live.get("id"))
                         before=node_status_snapshot.get(uid)
                         after=observed.get(uid)
                         if before is None or after is None: continue
                         for field in fields:
                             old_value=before.get(field)
                             new_value=after.get(field)
                             if new_value!=old_value and live.get(field)==old_value:
                                 live[field]=new_value
                                 wrote=True
                     if wrote: node_api.save_nodes(NODES_FILE,current_live)
                     current=current_live
             pending=wpo_pending_load(); pending_rows=[]'''

# A true positive HTTP 201 is issued only after disk persistence is verified.
OLD_ENROLL='node_api.save_nodes(NODES_FILE,registered)\n                 pending.pop(digest,None); wpo_pending_save(pending)'
NEW_ENROLL='''node_api.save_nodes(NODES_FILE,registered)
                     confirmed=node_api.load_nodes(NODES_FILE)
                     if not any(n.get("id")==added.get("id") and
                                n.get("url")==info["url"] for n in confirmed):
                         raise node_api.NodeError("Нода не сохранилась в реестре.")
                 pending.pop(digest,None); wpo_pending_save(pending)'''

def patch(source):
    if MARKER in source:
        return source, False
    for old,label in ((OLD_BEGIN,"status snapshot"),(OLD_SAVE,"status stale write"),
                      (OLD_ENROLL,"enrollment persistence")):
        if source.count(old)!=1:
            raise ValueError(f"WPO controller mismatch ({label}): expected 1 anchor, got {source.count(old)}. No changes.")
    result=source.replace(OLD_BEGIN,NEW_BEGIN,1)
    result=result.replace(OLD_SAVE,NEW_SAVE,1)
    result=result.replace(OLD_ENROLL,NEW_ENROLL,1)
    compile(result,"panel.py","exec")
    return result,True

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--panel",required=True)
    parser.add_argument("--out",required=True)
    options=parser.parse_args()
    source=Path(options.panel).read_text(encoding="utf-8")
    value,changed=patch(source)
    output=Path(options.out)
    output.write_text(value,encoding="utf-8")
    print("WPO enrollment race fix "+("ready" if changed else "already present"))

if __name__=="__main__":
    main()

"""Parallel remote subscription revocation tests, no real VPS calls."""
import ast
import importlib.util
from pathlib import Path
import threading
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location(
    "fast_delete_controller_patch",ROOT/"maintenance/users/wpo-fast-delete-controller-patch.py")
patcher=importlib.util.module_from_spec(spec)
spec.loader.exec_module(patcher)

def controller_text():
    src=(ROOT/"install-panel.sh").read_text(encoding="utf-8")
    return src.split('cat > "$APP_FILE" <<\'PY\'\n',1)[1].split("\nPY\n",1)[0]

def compiled_purge():
    original=controller_text()
    patched=patcher.patch(original)
    assert patcher.patch(patched)==patched
    tree=ast.parse(patched)
    fn=next(v for v in tree.body if isinstance(v,ast.FunctionDef)
            and v.name=="purge_remote_profiles")
    return compile(ast.Module(body=[fn],type_ignores=[]),"<fast-remote-revoke>","exec")

CODE=compiled_purge()

class RemotePurgeTests(unittest.TestCase):
    def test_multiple_nodes_revoke_in_parallel(self):
        barrier=threading.Barrier(2,timeout=2)
        calls=[]
        class NodeAPI:
            NodeError=type("NodeError",(Exception,),{})
            def load_nodes(self,path):
                return [{"id":"pl","enabled":True},{"id":"se","enabled":True}]
            def delete_profile(self,node,identity):
                barrier.wait(timeout=2)
                calls.append((node["id"],identity))
        ns={"node_api":NodeAPI(),"NODES_FILE":"ignored","federation_id":lambda s,d:s+"-"+d,
            "sys":None,"print":lambda *args,**kwargs:None}
        exec(CODE,ns)
        ns["purge_remote_profiles"]({"id":"sub","devices":[{"id":"dev"}]})
        self.assertCountEqual(calls,[("pl","sub-dev"),("se","sub-dev")])

    def test_single_node_revoke_remains_serial(self):
        called=[]
        class NodeAPI:
            NodeError=type("NodeError",(Exception,),{})
            def load_nodes(self,path):return [{"id":"only","enabled":True}]
            def delete_profile(self,node,identity):called.append(identity)
        ns={"node_api":NodeAPI(),"NODES_FILE":"ignored","federation_id":lambda s,d:s+"-"+d,
            "sys":None,"print":lambda *args,**kwargs:None}
        exec(CODE,ns)
        ns["purge_remote_profiles"]({"id":"sub","devices":[{"id":"a"},{"id":"b"}]})
        self.assertEqual(called,["sub-a","sub-b"])

    def test_deleted_device_only_selected(self):
        seen=[]
        class NodeAPI:
            NodeError=type("NodeError",(Exception,),{})
            def load_nodes(self,path):return [{"id":"one","enabled":True}]
            def delete_profile(self,node,identity):seen.append(identity)
        ns={"node_api":NodeAPI(),"NODES_FILE":"ignored","federation_id":lambda s,d:s+"-"+d,
            "sys":None,"print":lambda *args,**kwargs:None}
        exec(CODE,ns)
        ns["purge_remote_profiles"]({"id":"s","devices":[{"id":"a"},{"id":"b"}]},"b")
        self.assertEqual(seen,["s-b"])

    def test_unsupported_source_refused(self):
        with self.assertRaises(ValueError):
            patcher.patch("def purge_remote_profiles(s):\n    pass\n")

if __name__=="__main__":
    unittest.main()

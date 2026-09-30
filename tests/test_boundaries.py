# SPDX-License-Identifier: Apache-2.0
import ast,os,subprocess,sys,unittest
from pathlib import Path
class IsolationTests(unittest.TestCase):
    def test_direct_indirect_dynamic_import_routes_forbidden(self):
        code=r"""
import sys,importlib.abc,socket,urllib.request,subprocess,os
class Block(importlib.abc.MetaPathFinder):
 def find_spec(self,name,path=None,target=None):
  if name.startswith('trio_triage.actions') or name=='trio_triage.transport':raise AssertionError('forbidden capability import')
sys.meta_path.insert(0,Block())
def denied(*a,**k):raise AssertionError('forbidden capability execution')
socket.socket=denied;urllib.request.urlopen=denied;subprocess.Popen=denied;os.system=denied
for name in ('trio_triage.evidence','trio_triage.search','trio_triage.triage','trio_triage.team','trio_triage.packets'):
 __import__(name)
assert not any(x.startswith('trio_triage.actions') for x in sys.modules)
"""
        env={"PATH":os.environ.get("PATH",""),"PYTHONDONTWRITEBYTECODE":"1"}
        if os.environ.get("PYTHONPATH"):env["PYTHONPATH"]=os.environ["PYTHONPATH"]
        result=subprocess.run([sys.executable,"-c",code],env=env,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr.decode())
    def test_services_contain_no_writer_shell_network_routes(self):
        import trio_triage
        root=Path(trio_triage.__file__).parent
        forbidden={'eval','exec','__import__','system','popen','Popen','urlopen','getenv'}
        for name in ('evidence','search','triage','team','packets'):
            for p in (root/name).glob('*.py'):
                tree=ast.parse(p.read_text())
                for node in ast.walk(tree):
                    if isinstance(node,ast.Call):
                        call=node.func.id if isinstance(node.func,ast.Name) else node.func.attr if isinstance(node.func,ast.Attribute) else ''
                        self.assertNotIn(call,forbidden,(name,p.name,call))
                    if isinstance(node,ast.Import):self.assertFalse(any(x.name.startswith(('subprocess','trio_triage.actions','trio_triage.transport')) for x in node.names))

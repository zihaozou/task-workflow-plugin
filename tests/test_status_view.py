"""Workflow view contract, privacy, and real stdio coverage."""
import copy
import importlib.util
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/task-workflow/scripts"
sys.path.insert(0, str(SCRIPTS))
import status_view


def record():
    return {"task_id": "task-1", "title": "Example task", "version": 3, "session_id": "session-1",
            "created": "2026-10-25T12:00:00+00:00", "updated": "2026-10-25T12:00:01+00:00",
            "items": {"build": {"title": "Build", "status": "complete"}, "overall": {"title": "Verify", "status": "reviewing", "overall": True}},
            "design": {"digest": "abc", "content": "PRIVATE DESIGN"}, "approval": {"digest": "abc"},
            "task_lifecycle": {"status": "open"}, "experiments": {"experiment-1": {"status": "open", "goal": "PRIVATE GOAL"}},
            "runs": {"run-1": {"status": "running", "resource_id": "resource-1", "argv": ["PRIVATE COMMAND"]}},
            "root": "/private/root", "decisions": ["PRIVATE DECISION"]}


def resources():
    return [{"resource_id": "resource-1", "handle": "PRIVATE HANDLE", "owner": "PRIVATE OWNER", "provided_by": "user", "can_release": False,
             "derived_state": "in_use", "version": 2, "observed_at": "2026-10-25T12:00:00+00:00", "run_refs": [{"task_id": "task-1", "run_id": "run-1", "status": "running"}]}]


class ProjectionTests(unittest.TestCase):
    def core(self, state=None):
        return types.SimpleNamespace(dispatch=mock.Mock(return_value={"ok": True, "state": state or record(), "resources": resources()}))

    def test_whitelist_and_read_only_reference_refresh(self):
        core = self.core()
        store = status_view.ViewStore(core)
        opened = store.open({"root": "/private/root", "task_id": "task-1", "session_id": "session-1"})
        task = opened["tasks"][0]
        self.assertEqual((task["stage"], task["closure"]["status"], task["version"]), ("review", "open", 3))
        self.assertEqual(task["updated"], record()["updated"])
        self.assertEqual(task["resources"][0]["state"], "in_use")
        self.assertEqual(task["resources"][0]["provided_by"], "user")
        for private in ("PRIVATE", "/private", "digest", "handle", '"owner"', "argv"):
            self.assertNotIn(private, json.dumps(opened))
        core.dispatch.assert_called_once_with("status", {"root": "/private/root", "task_id": "task-1"})
        refreshed = store.refresh(opened["view_ref"])
        self.assertEqual(refreshed["tasks"], opened["tasks"])
        self.assertEqual(core.dispatch.call_count, 2)
        self.assertEqual(len(opened["view_ref"]), 43)

    def test_queued_execution_is_projected_without_claiming_running(self):
        state = record()
        state['runs']['run-1']['status'] = 'queued'
        opened = status_view.ViewStore(self.core(state)).open({'root': '/private/root', 'task_id': 'task-1'})
        self.assertEqual(opened['tasks'][0]['runs'][0]['status'], 'queued')
        html = status_view.read_resource()['text']
        self.assertIn("['queued','Queued']", html)
        self.assertIn('10000', html)

    def test_unbound_context_never_falls_back_to_another_task(self):
        core = self.core()
        store = status_view.ViewStore(core)
        for arguments in ({}, {"root": "/private/root"}, {"task_id": "task-1"}, {"root": "/private/root", "task_id": "../other"}):
            self.assertEqual(store.open(arguments)["status"], "unbound")
        self.assertEqual(store.refresh("guessed")["reason"], "unavailable")
        core.dispatch.assert_not_called()
        self.assertEqual(store.open({"root": "/private/root", "task_id": "task-1", "session_id": "other"})["reason"], "context_mismatch")
        core.dispatch.return_value["state"]["task_id"] = "other"
        self.assertEqual(store.open({"root": "/private/root", "task_id": "task-1"})["reason"], "unavailable")

    def test_references_survive_more_than_128_views_and_an_hour(self):
        core = self.core()
        store = status_view.ViewStore(core)
        with mock.patch("time.monotonic", return_value=0):
            first = store.open({"root": "/private/root", "task_id": "task-1"})["view_ref"]
        with mock.patch("time.monotonic", return_value=7200):
            for _ in range(130):
                store.open({"root": "/private/root", "task_id": "task-1"})
            self.assertEqual(store.refresh(first)["status"], "bound")
        self.assertEqual(len(store.views), 131)
        self.assertEqual(status_view.ViewStore(core).refresh(first)["reason"], "unavailable")

    def test_private_errors_and_unknown_source_facts(self):
        core = self.core()
        core.dispatch.side_effect = RuntimeError("PRIVATE /private/error")
        result = status_view.ViewStore(core).open({"root": "/private/root", "task_id": "task-1"})
        self.assertEqual(result["reason"], "unavailable")
        self.assertNotIn("PRIVATE", json.dumps(result))
        task = status_view.project_task({"task_id": "task-1", "title": "Inspect /private/file"}, [{"resource_id": "r", "derived_state": "unexpected", "provided_by": "PRIVATE"}])
        self.assertEqual(task["closure"], {"status": "unknown", "outcome": "unknown", "time": None})
        self.assertIsNone(task["updated"])
        self.assertNotIn("/private", task["title"])
        self.assertEqual(task["resources"][0]["state"], "unknown")
        self.assertEqual(task["resources"][0]["provided_by"], "unknown")

    def test_complete_projection_and_separate_aggregate_closure(self):
        state = record()
        state["items"] = {"item-" + str(i): {"title": "title", "status": "complete"} for i in range(110)}
        state["integration"] = {"status": "complete"}
        before = copy.deepcopy(state)
        result = status_view.project_task(state)
        self.assertEqual(state, before)
        self.assertEqual(len(result["items"]), 110)
        self.assertFalse(result["truncated"])
        self.assertEqual(result["stage"], "integrated")
        self.assertEqual(result["closure"]["status"], "open")
        for outcome in ("completed", "stopped", "abandoned"):
            state["task_lifecycle"] = {"status": "complete", "closure": {"outcome": outcome}}
            self.assertEqual(status_view.project_task(state)["closure"]["outcome"], outcome)

    def test_projection_keeps_all_rows_labels_identifiers_and_counts(self):
        state = record()
        long_id = "task-" + "a" * 200
        state.update(task_id=long_id, title="Full label " * 100, version=10**20)
        state["items"] = {"item-" + str(i): {"title": "Detail " * 100, "status": "complete"} for i in range(150)}
        state["experiments"] = {"experiment-" + str(i): {"status": "open"} for i in range(150)}
        state["runs"] = {"run-" + str(i): {"status": "running"} for i in range(150)}
        source = [dict(resources()[0], resource_id="resource-" + str(i), version=10**20,
                       run_refs=[{"task_id": long_id, "run_id": "run-" + str(j), "status": "running"} for j in range(150)]) for i in range(150)]
        task = status_view.project_task(state, source)
        for key in ("items", "experiments", "runs", "resources"):
            self.assertEqual(len(task[key]), 150)
        self.assertEqual(task["task_id"], long_id)
        self.assertEqual(task["title"], state["title"].strip())
        self.assertEqual(task["version"], 10**20)
        self.assertEqual(task["items"][0]["title"], "Detail " * 99 + "Detail")
        self.assertEqual(len(task["resources"][0]["run_refs"]), 150)
        self.assertEqual(task["resources"][0]["version"], 10**20)
        opened = status_view.ViewStore(self.core(state)).open({"root": "/private/root", "task_id": long_id})
        self.assertEqual(opened["status"], "bound")


class WireTests(unittest.TestCase):
    def request(self, number, method, params=None):
        return {"jsonrpc": "2.0", "id": number, "method": method, "params": params or {}}

    def exchange(self, requests, environment):
        process = subprocess.run([sys.executable, str(SCRIPTS / "mcp_server.py")], input="".join(json.dumps(request) + "\n" for request in requests), text=True, capture_output=True, env=environment, timeout=10)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stderr, "")
        return [json.loads(line) for line in process.stdout.splitlines()]

    def test_stdio_entrypoint_resource_and_unbound_default(self):
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, HOME=directory, PYTHONDONTWRITEBYTECODE="1")
            replies = self.exchange([self.request(1, "initialize"), self.request(2, "tools/list"), self.request(3, "resources/list"), self.request(4, "resources/read", {"uri": status_view.RESOURCE_URI}), self.request(5, "tools/call", {"name": status_view.TOOL_NAME}), self.request(6, "tools/call", {"name": status_view.REFRESH_TOOL, "arguments": {"view_ref": "unknown", "root": "/private"}})], env)
            self.assertEqual(list(Path(directory).iterdir()), [])
            self.assertIn("resources", replies[0]["result"]["capabilities"])
            tools = {tool["name"]: tool for tool in replies[1]["result"]["tools"]}
            self.assertEqual(tools[status_view.TOOL_NAME]["_meta"]["openai/ui"]["entrypoints"], [{"type": "thread"}])
            self.assertEqual(tools[status_view.TOOL_NAME]["_meta"]["ui"]["visibility"], ["model"])
            self.assertEqual(tools[status_view.REFRESH_TOOL]["_meta"]["ui"]["visibility"], ["app"])
            self.assertTrue(tools[status_view.TOOL_NAME]["annotations"]["readOnlyHint"])
            self.assertEqual(replies[2]["result"]["resources"][0]["uri"], status_view.RESOURCE_URI)
            self.assertEqual(replies[3]["result"]["contents"][0]["mimeType"], status_view.MIME_TYPE)
            self.assertEqual(replies[4]["result"]["structuredContent"]["status"], "unbound")
            self.assertEqual(replies[5]["error"]["code"], -32602)

    def test_stdio_bound_refresh_reads_actual_project_without_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            subprocess.run(["git", "init", str(base)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(base), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "--allow-empty", "-m", "initial"], check=True, capture_output=True)
            env = dict(os.environ, HOME=directory, PYTHONDONTWRITEBYTECODE="1")
            init = self.request(1, "initialize")
            enrollment = {"root": str(base), "task_id": "sample", "title": "Sample task", "actor": "test", "authorization_source": "fixture", "project": str(base)}
            enrolled = self.exchange([init, self.request(2, "tools/call", {"name": "init", "arguments": enrollment})], env)
            self.assertFalse(enrolled[-1]["result"]["isError"], enrolled)
            def files():
                return {str(path.relative_to(base)): (path.stat().st_mtime_ns, path.read_bytes()) for path in base.rglob("*") if path.is_file()}
            before = files()
            process = subprocess.Popen([sys.executable, str(SCRIPTS / "mcp_server.py")], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
            def call(request):
                process.stdin.write(json.dumps(request) + "\n"); process.stdin.flush()
                return json.loads(process.stdout.readline())
            try:
                call(init)
                opened = call(self.request(3, "tools/call", {"name": status_view.TOOL_NAME, "arguments": {"root": str(base), "task_id": "sample"}}))["result"]["structuredContent"]
                self.assertEqual(opened["status"], "bound", opened)
                refreshed = call(self.request(4, "tools/call", {"name": status_view.REFRESH_TOOL, "arguments": {"view_ref": opened["view_ref"]}}))["result"]["structuredContent"]
                self.assertEqual(opened["tasks"], refreshed["tasks"])
                self.assertNotIn(str(base), json.dumps(refreshed))
                self.assertEqual(files(), before)
            finally:
                process.stdin.close(); process.wait(timeout=5)
                process.stdout.close(); process.stderr.close()


class BrowserTests(unittest.TestCase):
    def test_host_bridge_dom_layout_and_refresh(self):
        node = os.environ.get("WORKFLOW_TEST_NODE") or shutil.which("node")
        if not node:
            self.skipTest("Node is not available for optional browser verification")
        available = subprocess.run([node, "-e", "require.resolve('playwright')"], capture_output=True)
        if available.returncode:
            self.skipTest("Playwright is not available for optional browser verification")
        script = r"""
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {chromium}=require('playwright');
(async()=>{
const options={headless:true};
if(process.env.WORKFLOW_TEST_BROWSER)options.executablePath=process.env.WORKFLOW_TEST_BROWSER;
const browser=await chromium.launch(options);
try {
const page=await browser.newPage();
let html=fs.readFileSync(process.argv[1],'utf8');
html=html.replace('<script>', '<script>window.testIntervals=new Map();window.setInterval=(fn,delay)=>{window.testIntervals.set(delay,fn);return delay};window.clearInterval=id=>window.testIntervals.delete(id);');
await page.setContent('<html><body style="margin:0"><iframe id="app" style="width:100%;height:100vh;border:0"></iframe></body></html>');
await page.evaluate(({html})=>{
  window.calls=[];window.dropRefresh=false;window.failRefresh=false;window.html=html;
  window.data={schema_version:1,generated_at:'2026-10-25T12:00:00Z',status:'bound',view_ref:'opaque-view-reference',notice:'Recorded states only.',tasks:[{key:'task-1',task_id:'task-1',title:'<img src=x onerror=alert(1)>',version:3,updated:null,stage:'review',closure:{status:'open',outcome:'unknown'},items:[{title:'<script>bad()</script>',status:'reviewing'}],experiments:[],runs:[],resources:[{resource_id:'resource-1',state:'available',provided_by:'user',can_release:false,run_refs:[]}]}]};
  window.addEventListener('message',event=>{
    if(event.source!==document.querySelector('iframe').contentWindow)return;
    const message=event.data;window.calls.push(message);
    const reply=result=>event.source.postMessage({jsonrpc:'2.0',id:message.id,result},'*');
    if(message.method==='ui/initialize')reply({protocolVersion:window.hostProtocol||'2026-01-26',hostInfo:{name:'test',version:'26.1000.30000'},hostCapabilities:window.hostNoRefresh?{}:{serverTools:{}},hostContext:{platform:'desktop',theme:'light',safeAreaInsets:{top:5,right:6,bottom:7,left:8}}});
    if(message.method==='ui/notifications/initialized')event.source.postMessage({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:{structuredContent:window.data}},'*');
    if(message.method==='tools/call'&&!window.dropRefresh){if(window.failRefresh)event.source.postMessage({jsonrpc:'2.0',id:message.id,error:{code:-1,message:'PRIVATE ERROR'}},'*');else reply({structuredContent:window.data});}
  });
  document.querySelector('iframe').srcdoc=html;
},{html});
const frame=page.frameLocator('#app');

await frame.locator('#details').waitFor();
assert.equal(await frame.locator('#details img').count(),0);
assert.equal(await frame.locator('#details script').count(),0);
assert((await frame.locator('#details').textContent()).includes('<script>bad()</script>'));
assert.equal(await frame.locator('#phase').textContent(),'Review');
assert.equal(await frame.locator('main img').count(),0);
const child=page.frames()[1];
await child.evaluate(()=>window.dispatchEvent(new MessageEvent('message',{source:null,data:{jsonrpc:'2.0',method:'ui/notifications/tool-result',params:{structuredContent:{schema_version:1,tasks:[]}}}})));
assert.equal(await frame.locator('#details').isVisible(),true);
await frame.locator('#refresh').click();
await page.waitForFunction(()=>window.calls.some(call=>call.method==='tools/call'));
const refresh=await page.evaluate(()=>window.calls.find(call=>call.method==='tools/call'));
assert.deepEqual(refresh.params,{name:'workflow.refresh_view',arguments:{view_ref:'opaque-view-reference'}});
assert.equal(await frame.locator('#details').isVisible(),true);
await page.evaluate(()=>window.failRefresh=true);
await frame.locator('#refresh').click();
await frame.locator('#connection').filter({hasText:'Refresh unavailable'}).waitFor();
assert.equal(await frame.locator('#details').isVisible(),true);
await page.evaluate(()=>window.failRefresh=false);
await page.evaluate(()=>document.querySelector('iframe').contentWindow.postMessage({jsonrpc:'2.0',method:'ui/notifications/host-context-changed',params:{theme:'dark',safeAreaInsets:{left:20}}},'*'));
await page.waitForTimeout(30);
assert.equal(await child.evaluate(()=>document.documentElement.dataset.theme),'dark');
assert.equal(await child.evaluate(()=>document.documentElement.style.getPropertyValue('--safe-left')),'20px');
async function fixture(stage,closure,runs,expected,detail='') {
  await page.evaluate(({stage,closure,runs})=>{const task=window.data.tasks[0];task.title='Example task';task.items[0].title='Implementation review';task.stage=stage;task.closure=closure;task.runs=runs;document.querySelector('iframe').contentWindow.postMessage({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:{structuredContent:window.data}},'*');},{stage,closure,runs});
  await page.waitForTimeout(15);
  assert.equal(await frame.locator('#phase').textContent(),expected);
  if(detail)assert((await frame.locator('#details').textContent()).includes(detail));
  const visible=await frame.locator('main').innerText();
  for(const absent of ['Example task','Task open','Task closed','Source version','Read 08','Resources','Experiments','Active runs','resource-1'])assert(!visible.includes(absent));
  assert.equal(await frame.locator('footer,details,input,h2').count(),0);
  assert((await frame.locator('main').boundingBox()).height<=120);
}
await fixture('enrolled',{status:'open'},[],'Design');
await fixture('review',{status:'open'},[],'Review','Implementation review');
await fixture('integrated',{status:'open'},[{run_id:'run-1',status:'queued'}],'Queued','run-1');
await fixture('integrated',{status:'open'},[{run_id:'run-1',status:'running'}],'Running','run-1');
await fixture('implementation',{status:'open'},[{run_id:'run-1',status:'running'}],'Implementation · Running');
for(const [outcome,expected] of [['completed','Completed'],['stopped','Stopped'],['abandoned','Abandoned']])await fixture('integrated',{status:'complete',outcome},[{run_id:'run-1',status:'running'}],expected);
await fixture('integrated',{status:'open'},[{run_id:'run-1',status:'running'}],'Running','run-1');
assert.equal(await child.evaluate(()=>window.testIntervals.has(10000)),true);
for(const [width,height] of [[375,812],[768,1024],[1440,900]]){
  await page.setViewportSize({width,height});
  assert(await child.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
  assert((await frame.locator('main').boundingBox()).height<=120);
  assert.equal(await frame.locator('details,footer,input').count(),0);
  assert.equal(await frame.locator('main').getByText('Source version',{exact:false}).count(),0);
  if(process.env.WORKFLOW_TEST_SCREENSHOTS){
    const contentHeight=await child.evaluate(()=>document.documentElement.scrollHeight);
    await page.evaluate(value=>document.querySelector('iframe').style.height=value+'px',contentHeight);
    await page.setViewportSize({width,height:Math.max(height,contentHeight)});
    await frame.locator('main').screenshot({path:process.env.WORKFLOW_TEST_SCREENSHOTS+'/workflow-'+width+'.png'});
    await page.evaluate(()=>document.querySelector('iframe').style.height='100vh');
  }
}
// A delayed reply remains pending beyond the former ten-second deadline.
await child.evaluate(()=>{window.testTimeouts=[];window.setTimeout=(fn,delay)=>{window.testTimeouts.push({fn,delay});return window.testTimeouts.length;};});
await page.evaluate(()=>window.dropRefresh=true);
await frame.locator('#refresh').click();
await page.waitForFunction(()=>window.calls.filter(call=>call.method==='tools/call').length>=3);
await child.evaluate(()=>{for(const timer of window.testTimeouts)if(timer.delay<=20000)timer.fn();});
assert.equal(await child.evaluate(()=>window.testTimeouts.length),0);
assert.equal(await frame.locator('#refresh').isEnabled(),false);
assert.equal(await frame.locator('#connection').isVisible(),false);
const delayed=await page.evaluate(()=>window.calls.filter(call=>call.method==='tools/call').at(-1));
await page.evaluate(id=>{window.data.tasks[0].items[0].title='Long detail '.repeat(50);window.data.tasks[0].stage='review';window.data.tasks[0].runs=[];document.querySelector('iframe').contentWindow.postMessage({jsonrpc:'2.0',id,result:{structuredContent:window.data}},'*');},delayed.id);
await page.waitForFunction(()=>!document.querySelector('iframe').contentDocument.querySelector('#refresh').disabled);
assert.equal(await frame.locator('#details').textContent(),'Long detail '.repeat(50));
// Automatic refresh pauses after an explicit host failure and resumes after a manual read.
await page.evaluate(()=>{window.dropRefresh=false;window.failRefresh=true;});
await frame.locator('#refresh').click();
await frame.locator('#connection').filter({hasText:'Refresh unavailable'}).waitFor();
await page.evaluate(()=>window.beforePaused=window.calls.filter(call=>call.method==='tools/call').length);
await child.evaluate(()=>window.testIntervals.get(10000)());
await page.waitForTimeout(30);
assert.equal(await page.evaluate(()=>window.calls.filter(call=>call.method==='tools/call').length-window.beforePaused),0);
await page.evaluate(()=>window.failRefresh=false);
await frame.locator('#refresh').click();
await frame.locator('#connection').waitFor({state:'hidden'});
// Automatic refresh is visibility-gated and coalesces outstanding reads.
await page.evaluate(()=>{window.dropRefresh=true;window.beforeAuto=window.calls.filter(call=>call.method==='tools/call').length;});
await child.evaluate(()=>{Object.defineProperty(document,'visibilityState',{configurable:true,get:()=> 'hidden'});window.testIntervals.get(10000)();});
await page.waitForTimeout(30);
assert.equal(await page.evaluate(()=>window.calls.filter(call=>call.method==='tools/call').length-window.beforeAuto),0);
await child.evaluate(()=>{Object.defineProperty(document,'visibilityState',{configurable:true,get:()=> 'visible'});window.testIntervals.get(10000)();window.testIntervals.get(10000)();});
await page.waitForTimeout(60);
assert.equal(await page.evaluate(()=>window.calls.filter(call=>call.method==='tools/call').length-window.beforeAuto),1);
await page.evaluate(()=>document.querySelector('iframe').contentWindow.postMessage({jsonrpc:'2.0',id:999,method:'ui/resource-teardown',params:{}},'*'));
await page.waitForTimeout(30);
assert.equal(await child.evaluate(()=>window.testIntervals.size),0);
await page.evaluate(()=>{window.hostProtocol='unsupported';document.querySelector('iframe').srcdoc=window.html;});
await frame.locator('#connection').filter({hasText:'unsupported app protocol'}).waitFor();
assert.equal(await frame.locator('#refresh').isEnabled(),false);
await page.evaluate(()=>{window.hostProtocol='2026-01-26';window.hostNoRefresh=true;document.querySelector('iframe').srcdoc=window.html;});
await frame.locator('#details').waitFor();
await frame.locator('#connection').filter({hasText:'Reopen Workflow'}).waitFor();
assert.equal(await frame.locator('#refresh').isEnabled(),false);
assert.equal(await frame.locator('details,footer,input').count(),0);
assert.equal(await frame.locator('input').count(),0);
console.log('Browser bridge, escaped rendering, current task, read-only refresh, errors, delayed replies, theme and responsive widths passed.');
} finally {await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
"""
        process = subprocess.run([node, "-e", script, str(SCRIPTS.parent / "assets/workflow.html")], text=True, capture_output=True, timeout=45)
        self.assertEqual(process.returncode, 0, process.stderr)


if __name__ == "__main__":
    unittest.main()

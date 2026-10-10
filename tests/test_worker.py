import json
import os
from pathlib import Path
import subprocess
import sys
import pytest
import pyarrow.parquet as pq
from tbs.demo import fixture
from tbs.events import EventParser, CancelledError
from tbs.pipeline import run
from tbs.gui.site_document import SiteDocument
from tbs.gui.result_store import ResultStore


def test_incremental_events_and_limits():
    parser = EventParser()
    data = (json.dumps({"event_version":1,"type":"warning","message":"ภาษาไทย"},ensure_ascii=False)+"\n").encode()
    events=[]
    for byte in data:
        events += parser.feed(bytes([byte]))
    parser.finish()
    assert events[0]["message"]=="ภาษาไทย"
    with pytest.raises(ValueError,match="protocol"):
        EventParser().feed(b'{"event_version":2,"type":"progress"}\n')
    with pytest.raises(ValueError,match="limit"):
        EventParser(limit=5).feed(b'123456')
    parser=EventParser()
    parser.feed(b'{')
    with pytest.raises(ValueError,match="Incomplete"):
        parser.finish()


def test_pipeline_cancellation_closes_files(tmp_path):
    path=fixture(tmp_path/"fixture")
    events=[]
    def update(event):
        events.append(event)
    with pytest.raises(CancelledError):
        run(path,tmp_path/"output",on_progress=update,
            should_cancel=lambda: any(e.get("stage")=="reconstruct" for e in events))
    out=next((tmp_path/"output").iterdir())
    assert json.loads((out/"manifest.json").read_text())["status"]=="cancelled"
    # File handles are released: this also catches Windows locking regressions.
    pq.read_table(out/"detections.parquet")
    for item in out.iterdir():
        item.rename(item.with_name("closed-"+item.name))
    assert not any(e["type"]=="completed" for e in events)


def invoke_worker(tmp_path,extra,session="test"):
    environment=dict(os.environ,PYTHONIOENCODING="cp1252")
    return subprocess.run([sys.executable,"-m","tbs.worker","--session",session,
        "--control",str(tmp_path/"control.json"),"--output",str(tmp_path/"output"),*extra],
        capture_output=True,text=True,encoding="utf-8",timeout=30,env=environment)


def test_worker_demo_protocol_and_results(tmp_path):
    tmp_path=tmp_path/"ข้อมูล ทดสอบ"
    tmp_path.mkdir()
    result=invoke_worker(tmp_path,["--demo"])
    assert result.returncode==0,result.stderr
    events=EventParser().feed(result.stdout.encode())
    assert all(e["session_id"]=="test" for e in events)
    assert events[-1]["type"]=="completed"
    store=ResultStore(events[-1]["output"])
    assert store.counts()[0]["events"]==1
    assert store.frame(25)["t"]==pytest.approx(2.5)
    assert store.frame_detections(25)[0]["track_id"]==1
    assert len(store.page("trajectories",offset=10,limit=3))==3
    destination=tmp_path/"CSV ภาษาไทย"
    store.export_csv(destination)
    assert (destination/"trajectories.csv").read_bytes().startswith(b'\xef\xbb\xbf')
    headers=(destination/"trajectories.csv").read_text(encoding="utf-8-sig").splitlines()[0]
    assert "v_m_s" in headers and "epoch" in headers
    with pytest.raises(ValueError,match="ปลายทาง"):
        store.export_csv(destination)


def test_worker_cancel_before_start_and_failure(tmp_path):
    (tmp_path/"control.json").write_text('{"session_id":"test"}')
    result=invoke_worker(tmp_path,["--demo"])
    assert result.returncode==3
    assert json.loads(result.stdout.splitlines()[-1])["type"]=="cancelled"
    (tmp_path/"control.json").unlink()
    # Every GUI job gets a new session; stale controls must never cancel it.
    result=invoke_worker(tmp_path,["--config",str(tmp_path/"missing.yaml")],session="next-job")
    assert result.returncode==2
    assert json.loads(result.stdout.splitlines()[-1])["type"]=="failed"


def test_config_document_roundtrip_and_snapshot(tmp_path):
    path=fixture(tmp_path/"ข้อมูล ทดสอบ")
    document=SiteDocument()
    document.open(path)
    document.config["description"]="ภาษาไทย"
    document.config["road"]["count_lines"][0]["reid_reference"]=True
    document.save(tmp_path/"saved"/"site.yaml")
    opened=SiteDocument()
    opened.open(document.path)
    assert opened.config["road"]["count_lines"][0]["reid_reference"]
    assert Path(opened.config["videos"][0]["path"]).is_file()
    assert opened.validate(tmp_path/"snapshot.yaml")["description"]=="ภาษาไทย"

"""Offline exact startup-payload tests; fake ros2/python, no Docker or renderer."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/'simulation/ros2_gazebo/scripts/start_sim_backend.sh'


def startup_payload():
    source=SCRIPT.read_text()
    blocks=re.findall(r"bash -lc '\n(.*?)\n'",source,re.S)
    return next(v for v in blocks if 'exec python3 /tmp/tfg_sim_processes.py start' in v)


def run_payload(tmp_path,resource_path=None,exists=True):
    prefix=tmp_path/'installed package';models=prefix/'share/ardupilot_gazebo/models'
    if exists:models.mkdir(parents=True,exist_ok=True)
    bindir=tmp_path/'bin';bindir.mkdir(exist_ok=True)
    ros2=bindir/'ros2'
    ros2.write_text('#!/bin/sh\n[ "$*" = "pkg prefix ardupilot_gazebo" ] || exit 91\nprintf "%s\\n" "$FAKE_PREFIX"\n');ros2.chmod(0o755)
    python=bindir/'python3'
    python.write_text('#!'+sys.executable+'\nimport os,json,sys\nassert sys.argv[1:]==["/tmp/tfg_sim_processes.py","start"]\nprint(json.dumps({"resource_path":os.environ.get("GZ_SIM_RESOURCE_PATH"),"profile":os.environ["TFG_SIM_PROFILE"]}))\n');python.chmod(0o755)
    env={'PATH':str(bindir)+':/usr/bin:/bin','FAKE_PREFIX':str(prefix),'TFG_SIM_PROFILE':'two_drones'}
    if resource_path is not None:env['GZ_SIM_RESOURCE_PATH']=resource_path
    # Only source is a double. The REAL payload is otherwise executed verbatim.
    body='source() { case "$1" in /opt/ros/humble/setup.bash|/root/ardu_ws/install/setup.bash) return 0;; *) return 90;; esac; }\n'+startup_payload()
    return subprocess.run(['bash','-c',body],env=env,capture_output=True,text=True,timeout=5),prefix


@pytest.mark.parametrize('existing',[None,'','/existing/models','/existing/models:/other'])
def test_effective_resource_root_is_scoped_and_preserves_paths(tmp_path,existing):
    result,prefix=run_payload(tmp_path,existing)
    assert result.returncode==0,result.stderr
    paths=json.loads(result.stdout)['resource_path'].split(':')
    assert paths[0]==str(prefix/'share')
    assert paths[1:]==([] if not existing else existing.split(':'))
    assert not any(not p for p in paths)


def test_idempotence_and_no_resource_file_mutation(tmp_path):
    prefix=tmp_path/'installed package';share=str(prefix/'share')
    result,_=run_payload(tmp_path,'/existing:'+share+':/other')
    assert result.returncode==0
    assert json.loads(result.stdout)['resource_path']=='/existing:'+share+':/other'
    # Source no longer mutates installed model XML with sed or backup copies.
    assert 'sed -i' not in SCRIPT.read_text() and 'before_tfg_fix' not in SCRIPT.read_text()
    assert list((prefix/'share/ardupilot_gazebo/models').iterdir())==[]


def test_missing_package_resources_prevents_supervisor(tmp_path):
    result,_=run_payload(tmp_path,exists=False)
    assert result.returncode!=0 and not result.stdout
    assert 'Missing ArduPilot package resources' in result.stderr


@pytest.mark.parametrize('profile',['two_drones','two_drones_rover'])
def test_both_profiles_deliver_resource_path_to_actual_start_payload(tmp_path,profile):
    # Full backend control flow and Docker arguments are reused from drift tests.
    from tests.test_simulation_profiles import _run_shell
    result,calls,_=_run_shell(tmp_path,SCRIPT.read_text(),start=True,TFG_SIM_PROFILE=profile,
                              OFFLINE_TOPICS='/ap/v1/status\n/ap/v2/status\n/ap/v3/status')
    assert result.returncode==0,result.stdout+result.stderr
    starts=[c for c in calls if c[0]=='exec' and 'exec python3 /tmp/tfg_sim_processes.py start' in ' '.join(c)]
    assert len(starts)==1
    assert 'TFG_SIM_PROFILE='+profile in starts[0]
    assert starts[0][-3:-1]==['bash','-lc']
    assert starts[0][-1].strip()==startup_payload().strip()


def test_uri_authority_requires_package_share_parent(tmp_path):
    # Header SystemPaths::FindFileURI contract: authority retained as needed.
    # This tests expected path composition, NOT execution of Gazebo's resolver.
    parent=tmp_path/'share';mesh=parent/'ardupilot_gazebo/models/iris_with_standoffs/meshes/iris_collision.stl'
    mesh.parent.mkdir(parents=True);mesh.write_bytes(b'synthetic-mesh')
    uri='package://ardupilot_gazebo/models/iris_with_standoffs/meshes/iris_collision.stl'
    suffix=uri.removeprefix('package://')
    assert not (parent/'ardupilot_gazebo/models'/suffix).exists()
    assert (parent/suffix).read_bytes()==b'synthetic-mesh'

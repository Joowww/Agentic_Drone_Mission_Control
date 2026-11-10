from pathlib import Path
import hashlib,json,subprocess,time
root=Path('/tmp/tfg-peer-build-20261024-swzvihrs');build=Path(str(root)+'-build')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def cmd(*args):return subprocess.run(args,check=True,capture_output=True,text=True,timeout=10).stdout
meta=json.loads((root/'record.json').read_text())
for name,h in meta['sources']['modified'].items():assert sha(root/'source'/name)==h,name
for file,key in [('trace.hpp','trace_header_sha256'),('peer_endpoint.hpp','peer_header_sha256')]:assert sha(root/'source/include/uxr/agent/diagnostic'/file)==meta['sources'][key]
wrapper=build/'agent-build/micro_ros_agent';lib=(build/'native-build/libmicroxrcedds_agent.so').resolve()
artifacts={}
for name,p in [('wrapper',wrapper),('library',lib)]:
 artifacts[name]={'path':str(p),'sha256':sha(p),'bytes':p.stat().st_size,'elf_dynamic':cmd('readelf','-d',str(p)),'symbols':cmd('nm','-D',str(p))}
assert 'libmicroxrcedds_agent.so.2.4' in artifacts['wrapper']['elf_dynamic']
assert '(SONAME)' in artifacts['library']['elf_dynamic'] and 'libmicroxrcedds_agent.so.2.4' in artifacts['library']['elf_dynamic']
assert 'librmw_fastrtps_shared_cpp.so' in artifacts['library']['elf_dynamic']
assert str(build/'native-build') in artifacts['wrapper']['elf_dynamic']
# Verify the native undefined symbols referenced by wrapper are exported by new native library.
undefined={line.split()[-1] for line in artifacts['wrapper']['symbols'].splitlines() if ' U ' in line}
exported={line.split()[-1] for line in artifacts['library']['symbols'].splitlines() if len(line.split())==3 and line.split()[1] in {'T','W','V','B','D'}}
native_required={sym for sym in undefined if sym.startswith('_ZN8eprosima3uxr') or sym.startswith('_ZTIN8eprosima3uxr')}
assert native_required and native_required<=exported,sorted(native_required-exported)
# Dependency files and compile flags must use the copied ABI-changing public headers.
deps=list((build/'agent-build/CMakeFiles/micro_ros_agent.dir').rglob('*.o.d'))
all_deps='\n'.join(p.read_text() for p in deps)
native_headers=sorted({word.rstrip('\\') for word in all_deps.split() if '/uxr/agent/' in word})
assert native_headers
assert all(h.startswith(str(root/'source/include')+'/') or h.startswith(str(build/'native-build/include')+'/') for h in native_headers),native_headers
native_deps='\n'.join(p.read_text() for p in (build/'native-build/CMakeFiles/microxrcedds_agent.dir').rglob('*.o.d'))
assert str(root/'source/include/uxr/agent/message/InputMessage.hpp') in native_deps
assert str(root/'source/include/uxr/agent/diagnostic/peer_endpoint.hpp') in native_deps
flags=(build/'agent-build/CMakeFiles/micro_ros_agent.dir/flags.make').read_text()
assert flags.index(str(root/'source/include')) < flags.index('/root/ardu_ws/install/micro_ros_agent/include')
wrapper_source=Path('/root/ardu_ws/src/micro_ros_agent/micro_ros_agent')
refs={str(p):sha(p) for p in wrapper_source.rglob('*') if p.is_file() and p.suffix in {'.cpp','.hpp','.h','.txt','.xml'}}
result={'kind':'REAL_NATIVE_AND_ROS_WRAPPER_COMPILE_LINK_STATIC_ELF_ONLY','return_code':0,'agent_executed':False,'installed':False,'artifacts':artifacts,'native_required_symbols_resolved':sorted(native_required),'wrapper_compile_flags':flags,'wrapper_native_headers':native_headers,'wrapper_source_hashes':refs,'build_recipe_sha256':sha(root/'build.sh'),'input_record':meta,'dependencies':{str(p):sha(p) for p in [Path('/opt/ros/humble/include/rmw_fastrtps_shared_cpp/rmw_fastrtps_shared_cpp/create_rmw_gid.hpp'),Path('/opt/ros/humble/lib/librmw_fastrtps_shared_cpp.so'),Path('/root/ardu_ws/install/micro_ros_agent/lib/micro_ros_agent/micro_ros_agent'),Path('/root/ardu_ws/install/micro_ros_agent/lib/libmicroxrcedds_agent.so')]},'read_at_wall_ns':time.time_ns()}
(root/'verification.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:{'path':v['path'],'sha256':v['sha256']} for k,v in artifacts.items()},indent=2))
